from __future__ import annotations

import json
import re
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import requests

from src.agents.tool_agents.base_tool_agent import BaseToolAgent
from src.formats.latex.prompts import language_label
from src.formats.latex.utils import (
    LatexNodes2Text,
    delete_ph,
    replace_href,
    replace_includegraphics,
)
from src.terminology import (
    TerminologyConfig,
    merge_term_pairs,
    project_terms_decisions_path,
    project_terms_path,
    write_project_terms_csv,
)


DOMAIN_WORDS = {
    "algorithm",
    "distribution",
    "likelihood",
    "model",
    "reward",
    "sampling",
    "sampler",
    "verifier",
}
STOP_PHRASES = {"this paper", "our method", "the result", "different tasks"}
FUNCTION_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "in",
    "into",
    "is",
    "of",
    "on",
    "or",
    "the",
    "to",
    "with",
}


class TerminologyAgent(BaseToolAgent):
    def __init__(self, config: dict[str, Any], project_dir: str, output_dir: str):
        super().__init__(agent_name="TerminologyAgent", config=config)
        self.config = config
        self.project_dir = Path(project_dir)
        self.output_dir = Path(output_dir)
        self.terminology_config = TerminologyConfig.from_config(config)
        self.source_language = config.get("source_language", "en")
        self.target_language = config.get("target_language", "ch")

        llm_config = config.get("llm_config") or {}
        self.model = llm_config.get("model", "gpt-4o")
        self.base_url = llm_config.get("base_url")
        self.api_key = llm_config.get("api_key")

    def execute(self) -> dict[str, Any]:
        sections = self.read_file(self.output_dir / "sections_map.json", "json")
        captions = self.read_file(self.output_dir / "captions_map.json", "json")
        envs = self.read_file(self.output_dir / "envs_map.json", "json")

        records = self._collect_text_records(sections, captions, envs)
        paper_context = self._extract_paper_context(sections=sections, captions=captions)
        known_terms: dict[str, str] = {}
        candidates = self._extract_rule_candidates(records)
        candidates = candidates[: self.terminology_config.max_llm_candidates]
        term_contexts = self._build_term_contexts(candidates, records)

        decisions: list[dict[str, Any]] = []
        confirmed_terms: dict[str, str] = {}
        if candidates:
            try:
                decisions = self._request_llm_for_term_decisions(
                    candidates,
                    paper_context,
                    term_contexts,
                    known_terms,
                )
                confirmed_terms = {
                    decision["source_term"]: decision["selected_translation"]
                    for decision in decisions
                    if decision.get("source_term") and decision.get("selected_translation")
                }
                for decision in decisions:
                    decision.setdefault("decision_source", "llm")
            except Exception as exc:
                decisions = [
                    {
                        "source_term": candidate,
                        "candidate_translations": [],
                        "selected_translation": "",
                        "decision_source": "llm_failed",
                        "reason": str(exc),
                    }
                    for candidate in candidates
                ]

        merged_terms = merge_term_pairs(
            confirmed_terms.items(),
            source_language=self.source_language,
        )
        terms_path = project_terms_path(self.output_dir)
        decisions_path = project_terms_decisions_path(self.output_dir)
        write_project_terms_csv(terms_path, merged_terms)
        self._write_decision_log(decisions_path, paper_context, decisions)

        return {
            "ok": True,
            "project_terms_path": str(terms_path),
            "project_terms_decisions_path": str(decisions_path),
        }

    def _process_latex_to_text(self, content: str) -> str:
        if not content:
            return ""
        text = replace_href(content)
        text = replace_includegraphics(text)
        text = LatexNodes2Text().latex_to_text(text)
        return delete_ph(text)

    def _collect_text_records(
        self,
        sections: list[dict[str, Any]],
        captions: list[dict[str, Any]],
        envs: list[dict[str, Any]],
    ) -> list[dict[str, str]]:
        records: list[dict[str, str]] = []
        for section in sections:
            section_id = str(section.get("section", ""))
            if section_id == "-1":
                continue
            text = self._process_latex_to_text(section.get("content", ""))
            if text:
                records.append({"part": "section", "id": section_id, "text": text})

        for caption in captions:
            caption_id = str(caption.get("placeholder", ""))
            text = self._process_latex_to_text(caption.get("content", ""))
            if text:
                records.append({"part": "caption", "id": caption_id, "text": text})

        for env in envs:
            if not env.get("need_trans"):
                continue
            env_id = str(env.get("placeholder", ""))
            text = self._process_latex_to_text(env.get("content", ""))
            if text:
                records.append({"part": "env", "id": env_id, "text": text})
        return records

    def _extract_paper_context(
        self,
        *,
        sections: list[dict[str, Any]],
        captions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        title = ""
        keywords: list[str] = []
        for caption in captions:
            cap_type = str(caption.get("cap_type", "")).lower()
            content = caption.get("content", "")
            if cap_type in {"title", "icmltitle"} and not title:
                title = self._extract_command_text(content, ["title", "icmltitle"])
            elif cap_type == "keywords":
                keyword_text = self._extract_command_text(content, ["keywords"])
                keywords = [item.strip() for item in keyword_text.split(",") if item.strip()]

        abstract = ""
        for section in sections:
            content = section.get("content", "")
            section_id = str(section.get("section", ""))
            if section_id != "0" and "abstract" not in content.lower():
                continue
            abstract = self._extract_abstract_text(content)
            if abstract:
                break

        project_name = self.project_dir.name
        category_config = self.config.get("category") or {}
        category = category_config.get(project_name, []) if isinstance(category_config, dict) else []
        return {
            "project_name": project_name,
            "title": title,
            "abstract": abstract,
            "keywords": keywords,
            "category": category,
        }

    def _extract_abstract_text(self, content: str) -> str:
        env_match = re.search(
            r"\\begin\{abstract\}(.*?)\\end\{abstract\}",
            content,
            flags=re.DOTALL | re.IGNORECASE,
        )
        if env_match:
            return self._process_latex_to_text(env_match.group(1))

        command_match = re.search(
            r"\\abstract\s*\{(.*?)\}",
            content,
            flags=re.DOTALL | re.IGNORECASE,
        )
        if command_match:
            return self._process_latex_to_text(command_match.group(1))

        return self._process_latex_to_text(content)

    def _extract_command_text(self, content: str, command_names: list[str]) -> str:
        for command_name in command_names:
            match = re.search(
                rf"\\{re.escape(command_name)}(?:\[[^\]]*\])?\s*\{{(.*?)\}}",
                content,
                flags=re.DOTALL | re.IGNORECASE,
            )
            if match:
                return self._process_latex_to_text(match.group(1))
        return self._process_latex_to_text(content)

    def _extract_rule_candidates(self, records: list[dict[str, str]]) -> list[str]:
        if str(self.source_language).lower() != "en":
            return []

        counts: Counter[str] = Counter()
        first_seen: dict[str, int] = {}
        seen_index = 0
        for record in records:
            tokens = [token.casefold() for token in re.findall(r"[A-Za-z][A-Za-z-]*", record.get("text", ""))]
            for size in range(2, 6):
                for start in range(0, len(tokens) - size + 1):
                    phrase_tokens = tokens[start : start + size]
                    if phrase_tokens[0] in FUNCTION_WORDS or phrase_tokens[-1] in FUNCTION_WORDS:
                        continue
                    phrase = " ".join(phrase_tokens)
                    if phrase in STOP_PHRASES:
                        continue
                    if not any(token in DOMAIN_WORDS for token in phrase_tokens):
                        continue
                    counts[phrase] += 1
                    if phrase not in first_seen:
                        first_seen[phrase] = seen_index
                        seen_index += 1

        return [
            phrase
            for phrase, _count in sorted(
                counts.items(),
                key=lambda item: (-item[1], first_seen[item[0]], item[0]),
            )
        ]

    def _build_term_contexts(
        self,
        candidates: list[str],
        records: list[dict[str, str]],
    ) -> dict[str, list[str]]:
        contexts: dict[str, list[str]] = defaultdict(list)
        for candidate in candidates:
            pattern = re.compile(rf"\b{re.escape(candidate)}\b", flags=re.IGNORECASE)
            for record in records:
                text = record.get("text", "")
                match = pattern.search(text)
                if not match:
                    continue
                start = max(0, match.start() - 120)
                end = min(len(text), match.end() + 120)
                contexts[candidate].append(text[start:end].strip())
                if len(contexts[candidate]) >= 3:
                    break
        return dict(contexts)

    def _request_llm_for_term_decisions(
        self,
        candidates: list[str],
        paper_context: dict[str, Any],
        term_contexts: dict[str, list[str]],
        known_terms: dict[str, str],
    ) -> list[dict[str, Any]]:
        if not self.api_key:
            raise RuntimeError("llm_config.api_key is required for terminology generation")

        source_label = language_label(self.source_language)
        target_label = language_label(self.target_language)
        system_prompt = (
            "You are an academic terminology reviewer. Select concise, consistent "
            f"{target_label} translations for {source_label} source terms. "
            "Return only JSON with a top-level decisions array."
        )
        user_payload = {
            "source_language": self.source_language,
            "target_language": self.target_language,
            "paper_context": paper_context,
            "candidates": candidates,
            "term_contexts": term_contexts,
            "known_terms": known_terms,
            "schema": {
                "decisions": [
                    {
                        "source_term": "string",
                        "candidate_translations": ["string"],
                        "selected_translation": "string",
                        "reason": "string",
                    }
                ]
            },
        }
        endpoint = (self.base_url or "https://api.openai.com/v1").rstrip("/") + "/chat/completions"
        response = requests.post(
            endpoint,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
                ],
                "temperature": 0,
            },
            timeout=60,
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        parsed = json.loads(self._strip_json_fence(content))
        if isinstance(parsed, list):
            decisions = parsed
        elif isinstance(parsed, dict):
            decisions = parsed.get("decisions", [])
        else:
            decisions = []
        if not isinstance(decisions, list):
            raise ValueError("Terminology LLM response must contain a decisions array")
        return decisions

    def _strip_json_fence(self, content: str) -> str:
        stripped = content.strip()
        if stripped.startswith("```"):
            stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
            stripped = re.sub(r"\s*```$", "", stripped)
        return stripped.strip()

    def _write_decision_log(
        self,
        path: Path,
        paper_context: dict[str, Any],
        decisions: list[dict[str, Any]],
    ) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "source_language": self.source_language,
            "target_language": self.target_language,
            "generated_at": int(time.time()),
            "paper_context": paper_context,
            "decisions": decisions,
        }
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
