"""Terminology generation for Markdown documents in the lite engine."""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any

import requests

from src.agents.tool_agents.terminology_agent import TerminologyAgent
from src.engines.lite_markdown import MarkdownBlock, split_markdown, translatable_markdown
from src.terminology import (
    merge_term_pairs,
    project_terms_decisions_path,
    project_terms_path,
    write_project_terms_csv,
)


_FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
_HEADING_RE = re.compile(r"^ {0,3}(#{1,6})[ \t]+(.+?)\s*#*\s*$")
_INLINE_CODE_RE = re.compile(r"(`+)(.*?)\1", flags=re.DOTALL)
_INLINE_MATH_RE = re.compile(r"(?<!\\)\$(?!\$).*?(?<!\\)\$", flags=re.DOTALL)
_DISPLAY_MATH_RE = re.compile(r"(?<!\\)\$\$.*?(?<!\\)\$\$", flags=re.DOTALL)
_BACKSLASH_MATH_RE = re.compile(r"\\(?:\[.*?\\\]|\(.*?\\\))", flags=re.DOTALL)
_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
_LINK_RE = re.compile(r"(?<!!)\[([^\]]+)\]\([^)]*\)")
_REFERENCE_LINK_RE = re.compile(r"(?<!!)\[([^\]]+)\]\[[^\]]*\]")
_FOOTNOTE_REFERENCE_RE = re.compile(r"\[\^[^\]]+\]")
_URL_RE = re.compile(r"(?:https?://|mailto:)[^\s<>]+", flags=re.IGNORECASE)
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_MARKDOWN_ACADEMIC_NOUN_ENDINGS = {"representation", "representations"}
_ABSTRACT_HEADINGS = {
    "ch": {"摘要"},
    "cn": {"摘要"},
    "de": {"zusammenfassung"},
    "en": {"abstract"},
    "es": {"resumen"},
    "fr": {"résumé", "resume"},
    "it": {"riassunto"},
    "ja": {"概要", "要旨"},
    "jp": {"概要", "要旨"},
    "ko": {"초록"},
    "pt": {"resumo"},
    "ru": {"аннотация"},
    "zh": {"摘要"},
}


class MarkdownTerminologyAgent(TerminologyAgent):
    """Generate project terminology artifacts from one Markdown source."""

    def __init__(
        self,
        config: dict[str, Any],
        markdown_path: Path,
        output_dir: Path,
    ) -> None:
        """Initialize Markdown paths while retaining shared terminology settings."""
        self.markdown_path = Path(markdown_path)
        super().__init__(
            config=config,
            project_dir=str(self.markdown_path.parent),
            output_dir=str(output_dir),
        )
        self.agent_name = "MarkdownTerminologyAgent"

    def execute(self) -> dict[str, Any]:
        """Collect Markdown terms and write CSV and decision JSON artifacts."""
        project_name = self.output_dir.name
        self.log(f"Starting Markdown terminology generation for project: {project_name}.")
        try:
            markdown = self.markdown_path.read_text(encoding="utf-8")
            records = self._collect_markdown_records(markdown)
            paper_context = self._extract_markdown_context(markdown)
            candidates = (
                self._extract_rule_candidates(records)
                if self.terminology_config.enabled
                else []
            )
            candidates = candidates[: self.terminology_config.max_llm_candidates]
            term_contexts = self._build_term_contexts(candidates, records)
            if not self.terminology_config.enabled:
                self.log("Markdown terminology generation is disabled; skipping LLM request.")
            self.log(
                f"Collected {len(records)} Markdown text records and "
                f"{len(candidates)} terminology candidates."
            )

            decisions: list[dict[str, Any]] = []
            confirmed_terms: dict[str, str] = {}
            if candidates:
                self.log("Requesting Markdown terminology decisions from LLM.")
                decisions = self._request_llm_for_term_decisions(
                    candidates,
                    paper_context,
                    term_contexts,
                    {},
                )
                confirmed_terms = {
                    decision["source_term"]: decision["selected_translation"]
                    for decision in decisions
                    if self._is_confirmed_term_decision_valid(decision, candidates)
                }
                for decision in decisions:
                    decision.setdefault("accepted", True)
                    decision.setdefault("decision_source", "llm")
                self.log(
                    f"Confirmed {len(confirmed_terms)} Markdown terminology entries."
                )

            merged_terms = merge_term_pairs(
                confirmed_terms.items(),
                source_language=self.source_language,
            )
            terms_path = project_terms_path(self.output_dir)
            decisions_path = project_terms_decisions_path(self.output_dir)
            write_project_terms_csv(terms_path, merged_terms)
            self._write_decision_log(decisions_path, paper_context, decisions)
            self.log(
                f"Successfully generated Markdown terminology for {project_name}: "
                f"{len(merged_terms)} terms. Terms: {terms_path}. "
                f"Decisions: {decisions_path}."
            )
            return {
                "ok": True,
                "project_terms_path": str(terms_path),
                "project_terms_decisions_path": str(decisions_path),
            }
        except Exception as exc:
            self.log(
                f"Markdown terminology generation failed for {project_name}: {exc}",
                level="error",
            )
            raise

    def _collect_markdown_records(self, markdown: str) -> list[dict[str, str]]:
        """Convert visible Markdown paragraphs into terminology text records."""
        markdown_blocks = self.config.get("_markdown_blocks")
        if isinstance(markdown_blocks, (list, tuple)) and all(
            isinstance(block, MarkdownBlock) for block in markdown_blocks
        ):
            terminology_markdown = translatable_markdown(markdown_blocks)
        else:
            lite_config = self.config.get("lite")
            translate_appendix = self.config.get("translate_appendix")
            if translate_appendix is None and isinstance(lite_config, dict):
                translate_appendix = lite_config.get("translate_appendix", True)
            blocks = split_markdown(
                markdown,
                source_language=str(self.source_language),
                translate_appendix=translate_appendix is not False,
            )
            terminology_markdown = translatable_markdown(blocks)
        visible_text = _markdown_visible_text(terminology_markdown)
        records: list[dict[str, str]] = []
        for index, paragraph in enumerate(re.split(r"\n\s*\n", visible_text)):
            normalized = " ".join(paragraph.split())
            if normalized:
                records.append(
                    {"part": "markdown", "id": str(index), "text": normalized}
                )
        return records

    def _is_rule_candidate_valid(self, phrase_tokens: list[str]) -> bool:
        """Apply shared filtering with Markdown-specific academic noun endings."""
        if super()._is_rule_candidate_valid(phrase_tokens):
            return True
        if not phrase_tokens or phrase_tokens[-1] not in _MARKDOWN_ACADEMIC_NOUN_ENDINGS:
            return False
        return super()._is_rule_candidate_valid([*phrase_tokens[:-1], "model"])

    def _extract_rule_candidates(self, records: list[dict[str, str]]) -> list[str]:
        """Extract English candidates normally and repeated phrases for other languages."""
        if str(self.source_language).casefold() == "en":
            return super()._extract_rule_candidates(records)

        counts: dict[str, int] = {}
        first_seen: dict[str, int] = {}
        for record in records:
            for sentence in re.split(r"[.!?;:，。！？；：\n]+", record.get("text", "")):
                tokens = [
                    token.casefold()
                    for token in re.findall(r"[^\W\d_][\w-]*", sentence, flags=re.UNICODE)
                ]
                for size in range(2, min(5, len(tokens)) + 1):
                    for start in range(len(tokens) - size + 1):
                        candidate = " ".join(tokens[start : start + size])
                        first_seen.setdefault(candidate, len(first_seen))
                        counts[candidate] = counts.get(candidate, 0) + 1

        return sorted(
            (candidate for candidate, count in counts.items() if count >= 2),
            key=lambda candidate: (-counts[candidate], first_seen[candidate]),
        )

    def _extract_markdown_context(self, markdown: str) -> dict[str, Any]:
        """Extract document-level title, abstract, keywords, and category context."""
        title = ""
        abstract_lines: list[str] = []
        abstract_level: int | None = None
        collecting_abstract = False
        keywords: list[str] = []
        abstract_headings = _abstract_headings(str(self.source_language))
        in_fence = False
        fence_character = ""
        fence_length = 0

        for line in markdown.splitlines():
            fence = _FENCE_RE.match(line)
            if fence:
                marker = fence.group(1)
                if not in_fence:
                    in_fence = True
                    fence_character = marker[0]
                    fence_length = len(marker)
                elif marker[0] == fence_character and len(marker) >= fence_length:
                    in_fence = False
                continue
            if in_fence:
                continue

            heading = _HEADING_RE.match(line)
            if heading:
                level = len(heading.group(1))
                heading_text = _markdown_visible_text(heading.group(2)).strip()
                if level == 1 and not title:
                    title = heading_text
                if heading_text.casefold() in abstract_headings:
                    collecting_abstract = True
                    abstract_level = level
                    continue
                if collecting_abstract and abstract_level is not None and level <= abstract_level:
                    collecting_abstract = False
                continue

            if collecting_abstract:
                abstract_lines.append(line)
            keyword_match = re.match(r"^\s*(?:keywords?|关键词)\s*[:：]\s*(.+)$", line, re.IGNORECASE)
            if keyword_match and not keywords:
                keywords = [
                    item.strip()
                    for item in re.split(r"[,，;；]", keyword_match.group(1))
                    if item.strip()
                ]

        category_map = self.config.get("category") or {}
        categories = category_map.get(self.markdown_path.stem, []) if isinstance(category_map, dict) else []
        return {
            "project_name": self.output_dir.name,
            "title": title or self.markdown_path.stem,
            "abstract": " ".join(_markdown_visible_text("\n".join(abstract_lines)).split()),
            "keywords": keywords,
            "category": categories,
        }


def _markdown_visible_text(markdown: str) -> str:
    """Remove protected Markdown syntax while retaining human-readable labels."""
    lines = markdown.splitlines()
    kept_lines: list[str] = []
    in_fence = False
    fence_character = ""
    fence_length = 0
    in_front_matter = bool(lines and lines[0].strip() == "---")

    for line_number, line in enumerate(lines):
        if in_front_matter:
            if line_number > 0 and line.strip() in {"---", "..."}:
                in_front_matter = False
            continue
        fence = _FENCE_RE.match(line)
        if fence:
            marker = fence.group(1)
            if not in_fence:
                in_fence = True
                fence_character = marker[0]
                fence_length = len(marker)
            elif marker[0] == fence_character and len(marker) >= fence_length:
                in_fence = False
            continue
        if not in_fence:
            kept_lines.append(line)

    text = "\n".join(kept_lines)
    text = _DISPLAY_MATH_RE.sub(" ", text)
    text = _INLINE_MATH_RE.sub(" ", text)
    text = _BACKSLASH_MATH_RE.sub(" ", text)
    text = _INLINE_CODE_RE.sub(" ", text)
    text = _IMAGE_RE.sub(r"\1", text)
    text = _REFERENCE_LINK_RE.sub(r"\1", text)
    text = _LINK_RE.sub(r"\1", text)
    text = _FOOTNOTE_REFERENCE_RE.sub(" ", text)
    text = _URL_RE.sub(" ", text)
    text = _HTML_TAG_RE.sub(" ", text)
    text = re.sub(r"(?m)^\s{0,3}(?:#{1,6}|>|[-+*]|\d+[.)])\s*", "", text)
    text = re.sub(r"[*_~]", "", text)
    return text


def _abstract_headings(source_language: str) -> set[str]:
    """Return localized abstract labels plus the conventional English label."""
    return {
        "abstract",
        *(
            heading.casefold()
            for heading in _ABSTRACT_HEADINGS.get(source_language.casefold(), set())
        ),
    }
