# Project Terms Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现论文级术语表最小闭环：首次翻译前生成 `project_terms.csv` 和 `project_terms_decisions.json`，翻译使用论文级术语，用户修改 CSV 后可显式全量重译。

**Architecture:** 新增独立 `TerminologyAgent` 和共享 CSV/术语 helper，避免继续把术语扫描职责塞进 `TranslatorAgent`。`CoordinatorAgent` 在 parser 后调用术语生成，`TranslatorAgent` 只负责按优先级加载词表和翻译，CLI/runtime 提供复用已解析输出目录的全量重译入口。术语 CSV 是用户编辑和重译的权威输入，JSON 只做审计日志。

**Tech Stack:** Python 3.10+、standard `unittest`、`pandas`、`aiohttp`、现有 agent 架构、TOML config。

---

## 文件结构

- Create: `src/terminology.py`  
  纯 helper 模块，负责 terminology 配置、CSV 读写、语言安全去重、项目输出目录检查、术语表合并。

- Create: `src/agents/tool_agents/terminology_agent.py`  
  新 agent，读取 parser map，抽取论文上下文和候选术语，调用 LLM 生成目标语候选译名，写 `project_terms.csv` 与 `project_terms_decisions.json`。

- Modify: `src/agents/tool_agents/translator_agent.py`  
  改造 `build_term_dict()`：加载 `user_term`、`project_terms.csv`、English-to-Chinese 默认词表、placeholder，支持 project terms 触发术语 prompt。

- Modify: `src/agents/coordinator_agent.py`  
  在 parser 后接入 `TerminologyAgent`，支持审核暂停结果，新增复用 parser map 的全量重译 workflow helper。

- Modify: `src/runtime.py`  
  增加 `retranslate_with_terms` override 和运行入口，准备项目时支持复用输出目录重译。

- Modify: `main.py`  
  增加 `--retranslate-with-terms` 参数，并让 CLI 调用 runtime 的共享准备与运行语义，避免与 runtime 分叉。

- Modify: `config/default.toml` and `config/template.toml`  
  增加 `[terminology]` 默认配置。

- Create: `tests/test_terminology.py`  
  覆盖 CSV/helper 语义、语言安全去重、项目输出目录检查。

- Create: `tests/test_terminology_agent.py`  
  覆盖 `TerminologyAgent` 的上下文抽取、候选生成、LLM prompt、CSV/JSON 写出、失败降级。

- Modify: `tests/test_multilingual_language_support.py`  
  覆盖 project terms 在非 English-to-Chinese 语言对可加载，默认 English-to-Chinese 词表不会误加载。

- Modify: `tests/test_coordinator_messages.py`  
  覆盖审核暂停结果和重译工作流 helper。

- Modify: `tests/test_runtime_project_results.py`  
  覆盖 `retranslate_with_terms` 路径和错误分类。

---

### Task 1: 术语配置与 CSV Helper

**Files:**
- Create: `src/terminology.py`
- Create: `tests/test_terminology.py`
- Modify: `config/default.toml`
- Modify: `config/template.toml`

- [ ] **Step 1: 写 failing tests**

Create `tests/test_terminology.py`:

```python
import json
import tempfile
import unittest
from pathlib import Path

from src.terminology import (
    PROJECT_TERMS_FILENAME,
    TerminologyConfig,
    casefold_language,
    load_term_csv,
    merge_term_pairs,
    project_terms_path,
    require_retranslation_inputs,
    write_project_terms_csv,
)


class TerminologyConfigTests(unittest.TestCase):
    def test_defaults_are_enabled_without_config(self):
        config = TerminologyConfig.from_config({})

        self.assertTrue(config.enabled)
        self.assertFalse(config.review_before_translate)
        self.assertEqual(config.max_llm_candidates, 30)

    def test_config_values_can_be_overridden(self):
        config = TerminologyConfig.from_config({
            "terminology": {
                "enabled": False,
                "review_before_translate": True,
                "max_llm_candidates": 5,
            }
        })

        self.assertFalse(config.enabled)
        self.assertTrue(config.review_before_translate)
        self.assertEqual(config.max_llm_candidates, 5)

    def test_invalid_max_llm_candidates_raises(self):
        with self.assertRaisesRegex(ValueError, "max_llm_candidates"):
            TerminologyConfig.from_config({
                "terminology": {"max_llm_candidates": -1}
            })


class TermCsvTests(unittest.TestCase):
    def test_load_term_csv_with_header_and_bad_rows(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            term_path = Path(tmp_dir) / PROJECT_TERMS_FILENAME
            term_path.write_text(
                "Source Term,Target Translation\n"
                "Graph,グラフ\n"
                "\n"
                "bad-only-one-column\n"
                "Model,モデル\n",
                encoding="utf-8",
            )

            result = load_term_csv(term_path, source_language="en")

        self.assertEqual(result.terms, {"Graph": "グラフ", "Model": "モデル"})
        self.assertEqual(len(result.warnings), 1)
        self.assertIn("bad-only-one-column", result.warnings[0])

    def test_load_term_csv_without_header(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            term_path = Path(tmp_dir) / PROJECT_TERMS_FILENAME
            term_path.write_text("Graph,グラフ\n", encoding="utf-8")

            result = load_term_csv(term_path, source_language="en")

        self.assertEqual(result.terms, {"Graph": "グラフ"})

    def test_casefold_language_for_latin_but_not_cjk(self):
        self.assertEqual(casefold_language("Graph", "en"), "graph")
        self.assertEqual(casefold_language("Graph", "de"), "graph")
        self.assertEqual(casefold_language("グラフ", "jp"), "グラフ")
        self.assertEqual(casefold_language("图模型", "ch"), "图模型")

    def test_merge_term_pairs_preserves_higher_priority(self):
        merged = merge_term_pairs(
            [("Graph", "用户图")],
            [("graph", "项目图")],
            [("Tree", "树")],
            source_language="en",
        )

        self.assertEqual(merged, {"Graph": "用户图", "Tree": "树"})

    def test_write_project_terms_csv_uses_source_target_header(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            term_path = Path(tmp_dir) / PROJECT_TERMS_FILENAME
            write_project_terms_csv(term_path, {"Graph": "グラフ", "Model": "モデル"})

            content = term_path.read_text(encoding="utf-8")

        self.assertIn("Source Term,Target Translation", content)
        self.assertIn("Graph,グラフ", content)


class RetranslationInputTests(unittest.TestCase):
    def test_require_retranslation_inputs_returns_paths_when_present(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_dir = Path(tmp_dir)
            for name in [
                "sections_map.json",
                "captions_map.json",
                "envs_map.json",
                PROJECT_TERMS_FILENAME,
            ]:
                (output_dir / name).write_text("[]" if name.endswith(".json") else "Graph,图\n", encoding="utf-8")

            result = require_retranslation_inputs(output_dir)

        self.assertEqual(result.project_terms_path.name, PROJECT_TERMS_FILENAME)
        self.assertTrue(result.sections_path.name.endswith("sections_map.json"))

    def test_require_retranslation_inputs_raises_for_missing_project_terms(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_dir = Path(tmp_dir)
            for name in ["sections_map.json", "captions_map.json", "envs_map.json"]:
                (output_dir / name).write_text("[]", encoding="utf-8")

            with self.assertRaisesRegex(FileNotFoundError, "project_terms.csv"):
                require_retranslation_inputs(output_dir)

    def test_project_terms_path_uses_output_dir(self):
        self.assertEqual(
            project_terms_path(Path("outputs") / "ch_paper"),
            Path("outputs") / "ch_paper" / PROJECT_TERMS_FILENAME,
        )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```powershell
python -m unittest tests.test_terminology
```

Expected: FAIL with `ModuleNotFoundError: No module named 'src.terminology'`.

- [ ] **Step 3: 实现 `src/terminology.py`**

Create `src/terminology.py`:

```python
import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple


PROJECT_TERMS_FILENAME = "project_terms.csv"
PROJECT_TERMS_DECISIONS_FILENAME = "project_terms_decisions.json"
TERM_CSV_HEADER = ("Source Term", "Target Translation")
CASEFOLD_LANGUAGES = {"en", "de", "fr", "es", "it", "pt", "ru"}


@dataclass(frozen=True)
class TerminologyConfig:
    enabled: bool = True
    review_before_translate: bool = False
    max_llm_candidates: int = 30

    @classmethod
    def from_config(cls, config: Dict[str, Any]) -> "TerminologyConfig":
        raw = (config or {}).get("terminology", {}) or {}
        max_llm_candidates = raw.get("max_llm_candidates", 30)
        if not isinstance(max_llm_candidates, int) or max_llm_candidates < 0:
            raise ValueError("terminology.max_llm_candidates must be a non-negative integer")
        return cls(
            enabled=bool(raw.get("enabled", True)),
            review_before_translate=bool(raw.get("review_before_translate", False)),
            max_llm_candidates=max_llm_candidates,
        )


@dataclass(frozen=True)
class TermCsvLoadResult:
    terms: Dict[str, str]
    warnings: List[str]


@dataclass(frozen=True)
class RetranslationInputs:
    sections_path: Path
    captions_path: Path
    envs_path: Path
    project_terms_path: Path


def project_terms_path(output_dir: Path) -> Path:
    return Path(output_dir) / PROJECT_TERMS_FILENAME


def project_terms_decisions_path(output_dir: Path) -> Path:
    return Path(output_dir) / PROJECT_TERMS_DECISIONS_FILENAME


def casefold_language(term: str, source_language: str) -> str:
    normalized_language = str(source_language or "").strip().lower()
    if normalized_language in CASEFOLD_LANGUAGES:
        return term.casefold()
    return term


def _is_header(row: List[str]) -> bool:
    if len(row) < 2:
        return False
    return row[0].strip().casefold() == TERM_CSV_HEADER[0].casefold() and row[1].strip().casefold() == TERM_CSV_HEADER[1].casefold()


def load_term_csv(path: Path, source_language: str) -> TermCsvLoadResult:
    terms: Dict[str, str] = {}
    seen = set()
    warnings: List[str] = []
    with Path(path).open("r", encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        for line_number, row in enumerate(reader, start=1):
            if not row or all(not item.strip() for item in row):
                continue
            if line_number == 1 and _is_header(row):
                continue
            if len(row) != 2:
                warnings.append(f"Skipped malformed term CSV row {line_number}: {','.join(row)}")
                continue
            source_term = row[0].strip()
            target_translation = row[1].strip()
            if not source_term or not target_translation:
                warnings.append(f"Skipped empty term CSV row {line_number}: {','.join(row)}")
                continue
            key = casefold_language(source_term, source_language)
            if key in seen:
                continue
            seen.add(key)
            terms[source_term] = target_translation
    return TermCsvLoadResult(terms=terms, warnings=warnings)


def merge_term_pairs(*sources: Iterable[Tuple[str, str]], source_language: str) -> Dict[str, str]:
    merged: Dict[str, str] = {}
    seen = set()
    for source in sources:
        for source_term, target_translation in source:
            if not source_term or not target_translation:
                continue
            key = casefold_language(str(source_term), source_language)
            if key in seen:
                continue
            seen.add(key)
            merged[str(source_term)] = str(target_translation)
    return merged


def write_project_terms_csv(path: Path, terms: Dict[str, str]) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with Path(path).open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(TERM_CSV_HEADER)
        for source_term, target_translation in terms.items():
            writer.writerow([source_term, target_translation])


def require_retranslation_inputs(output_dir: Path) -> RetranslationInputs:
    base = Path(output_dir)
    inputs = RetranslationInputs(
        sections_path=base / "sections_map.json",
        captions_path=base / "captions_map.json",
        envs_path=base / "envs_map.json",
        project_terms_path=base / PROJECT_TERMS_FILENAME,
    )
    missing = [
        str(path)
        for path in [
            inputs.sections_path,
            inputs.captions_path,
            inputs.envs_path,
            inputs.project_terms_path,
        ]
        if not path.exists()
    ]
    if missing:
        raise FileNotFoundError("Missing required retranslation inputs: " + ", ".join(missing))
    return inputs
```

- [ ] **Step 4: 增加默认配置**

Modify `config/default.toml` after `user_term = ""`:

```toml
[terminology]
enabled = true
review_before_translate = false
max_llm_candidates = 30
```

Modify `config/template.toml` in the same location with the same block.

- [ ] **Step 5: 运行术语 helper 测试**

Run:

```powershell
python -m unittest tests.test_terminology
```

Expected: PASS.

- [ ] **Step 6: Commit**

Run:

```powershell
git add src/terminology.py tests/test_terminology.py config/default.toml config/template.toml
git commit -m "feat(terms): 增加论文术语表基础工具"
```

---

### Task 2: TerminologyAgent 生成 CSV 与决策日志

**Files:**
- Create: `src/agents/tool_agents/terminology_agent.py`
- Create: `tests/test_terminology_agent.py`

- [ ] **Step 1: 写 failing tests**

Create `tests/test_terminology_agent.py`:

```python
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.agents.tool_agents.terminology_agent import TerminologyAgent
from src.terminology import PROJECT_TERMS_DECISIONS_FILENAME, PROJECT_TERMS_FILENAME


class TerminologyAgentContextTests(unittest.TestCase):
    def test_extracts_paper_context_from_captions_and_sections(self):
        agent = TerminologyAgent(
            config={
                "source_language": "en",
                "target_language": "ch",
                "category": {"paper": ["cs.AI"]},
                "llm_config": {},
            },
            project_dir="paper",
            output_dir="unused",
        )
        sections = [
            {
                "section": "0",
                "content": r"\begin{abstract}We propose power sampling for reasoning.\end{abstract}",
                "trans_content": "",
            },
            {
                "section": "1",
                "content": r"\section{Introduction} Power sampling improves diversity.",
                "trans_content": "",
            },
        ]
        captions = [
            {
                "placeholder": "<PLACEHOLDER_CAP_1>",
                "cap_type": "title",
                "content": r"\title{Reasoning by Sampling}",
                "trans_content": "",
            },
            {
                "placeholder": "<PLACEHOLDER_CAP_2>",
                "cap_type": "keywords",
                "content": r"\keywords{sampling, reasoning}",
                "trans_content": "",
            },
        ]

        context = agent._extract_paper_context(sections=sections, captions=captions)

        self.assertEqual(context["project_name"], "paper")
        self.assertIn("Reasoning by Sampling", context["title"])
        self.assertIn("power sampling", context["abstract"])
        self.assertEqual(context["keywords"], ["sampling", "reasoning"])
        self.assertEqual(context["category"], ["cs.AI"])

    def test_english_candidate_extraction_finds_multiword_terms(self):
        agent = TerminologyAgent(
            config={"source_language": "en", "target_language": "ch", "llm_config": {}},
            project_dir="paper",
            output_dir="unused",
        )
        records = [
            {
                "part": "sec",
                "id": "1",
                "text": "Power sampling uses a power distribution. Power sampling improves reasoning.",
            }
        ]

        candidates = agent._extract_rule_candidates(records)

        self.assertIn("power sampling", candidates)
        self.assertIn("power distribution", candidates)
        self.assertNotIn("this paper", candidates)

    def test_non_english_candidate_extraction_does_not_use_english_rules(self):
        agent = TerminologyAgent(
            config={"source_language": "de", "target_language": "jp", "llm_config": {}},
            project_dir="paper",
            output_dir="unused",
        )

        candidates = agent._extract_rule_candidates([
            {"part": "sec", "id": "1", "text": "Power sampling appears in an English-looking sentence."}
        ])

        self.assertEqual(candidates, [])


class _FakeLlmTerminologyAgent(TerminologyAgent):
    def _request_llm_for_term_decisions(self, candidates, paper_context, term_contexts, known_terms):
        self.llm_request = {
            "candidates": candidates,
            "paper_context": paper_context,
            "term_contexts": term_contexts,
            "known_terms": known_terms,
        }
        return [
            {
                "source_term": "power sampling",
                "candidate_translations": ["幂采样", "功率采样"],
                "selected_translation": "幂采样",
                "reason": "Uses a power distribution in the paper context.",
            }
        ]


class TerminologyAgentExecuteTests(unittest.TestCase):
    def _write_maps(self, output_dir: Path) -> None:
        (output_dir / "sections_map.json").write_text(
            json.dumps([
                {
                    "section": "0",
                    "content": r"\begin{abstract}We propose power sampling for power distributions.\end{abstract}",
                    "trans_content": "",
                },
                {
                    "section": "1",
                    "content": r"\section{Method} Power sampling uses a power distribution. Power sampling works.",
                    "trans_content": "",
                },
            ]),
            encoding="utf-8",
        )
        (output_dir / "captions_map.json").write_text(
            json.dumps([
                {
                    "placeholder": "<PLACEHOLDER_CAP_1>",
                    "cap_type": "title",
                    "content": r"\title{Reasoning by Sampling}",
                    "trans_content": "",
                }
            ]),
            encoding="utf-8",
        )
        (output_dir / "envs_map.json").write_text("[]", encoding="utf-8")

    def test_execute_writes_project_terms_and_decision_log_with_context(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_dir = Path(tmp_dir)
            self._write_maps(output_dir)
            agent = _FakeLlmTerminologyAgent(
                config={
                    "source_language": "en",
                    "target_language": "ch",
                    "category": {"paper": ["cs.AI"]},
                    "llm_config": {},
                    "terminology": {"max_llm_candidates": 10},
                },
                project_dir="paper",
                output_dir=str(output_dir),
            )

            result = agent.execute()

            terms_content = (output_dir / PROJECT_TERMS_FILENAME).read_text(encoding="utf-8")
            decisions = json.loads((output_dir / PROJECT_TERMS_DECISIONS_FILENAME).read_text(encoding="utf-8"))

        self.assertTrue(result["ok"])
        self.assertIn("Source Term,Target Translation", terms_content)
        self.assertIn("power sampling,幂采样", terms_content)
        self.assertEqual(decisions["source_language"], "en")
        self.assertEqual(decisions["target_language"], "ch")
        self.assertIn("power sampling", agent.llm_request["term_contexts"])
        self.assertIn("abstract", agent.llm_request["paper_context"])
        self.assertEqual(decisions["decisions"][0]["candidate_translations"], ["幂采样", "功率采样"])
        self.assertEqual(decisions["decisions"][0]["selected_translation"], "幂采样")
        self.assertIn("power distribution", decisions["decisions"][0]["reason"])

    def test_llm_failure_records_failure_and_does_not_write_unconfirmed_candidate(self):
        class FailingTerminologyAgent(TerminologyAgent):
            def _request_llm_for_term_decisions(self, candidates, paper_context, term_contexts, known_terms):
                raise RuntimeError("llm down")

        with tempfile.TemporaryDirectory() as tmp_dir:
            output_dir = Path(tmp_dir)
            self._write_maps(output_dir)
            agent = FailingTerminologyAgent(
                config={
                    "source_language": "en",
                    "target_language": "ch",
                    "llm_config": {},
                    "terminology": {"max_llm_candidates": 10},
                },
                project_dir="paper",
                output_dir=str(output_dir),
            )

            result = agent.execute()
            terms_content = (output_dir / PROJECT_TERMS_FILENAME).read_text(encoding="utf-8")
            decisions = json.loads((output_dir / PROJECT_TERMS_DECISIONS_FILENAME).read_text(encoding="utf-8"))

        self.assertTrue(result["ok"])
        self.assertNotIn("power sampling,", terms_content)
        self.assertEqual(decisions["decisions"][0]["decision_source"], "llm_failed")
        self.assertIn("llm down", decisions["decisions"][0]["reason"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```powershell
python -m unittest tests.test_terminology_agent
```

Expected: FAIL with `ModuleNotFoundError: No module named 'src.agents.tool_agents.terminology_agent'`.

- [ ] **Step 3: 实现 `TerminologyAgent`**

Create `src/agents/tool_agents/terminology_agent.py`:

```python
import json
import re
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List

import requests

import src.formats.latex.prompts as pm
from src.agents.tool_agents.base_tool_agent import BaseToolAgent
from src.formats.latex.utils import LatexNodes2Text, delete_ph, replace_href, replace_includegraphics
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


class TerminologyAgent(BaseToolAgent):
    def __init__(self, config: Dict[str, Any], project_dir: str = None, output_dir: str = None):
        super().__init__(agent_name="TerminologyAgent", config=config)
        self.config = config or {}
        self.project_dir = project_dir
        self.output_dir = output_dir
        self.term_config = TerminologyConfig.from_config(self.config)
        self.model = self.config.get("llm_config", {}).get("model", "gpt-4o")
        self.base_url = self.config.get("llm_config", {}).get("base_url")
        self.api_key = self.config.get("llm_config", {}).get("api_key")

    def execute(self) -> Dict[str, Any]:
        sections = self.read_file(Path(self.output_dir, "sections_map.json"), "json")
        captions = self.read_file(Path(self.output_dir, "captions_map.json"), "json")
        envs = self.read_file(Path(self.output_dir, "envs_map.json"), "json")

        records = self._collect_text_records(sections=sections, captions=captions, envs=envs)
        paper_context = self._extract_paper_context(sections=sections, captions=captions)
        known_terms: Dict[str, str] = {}
        candidates = self._extract_rule_candidates(records)
        candidates = candidates[: self.term_config.max_llm_candidates]
        term_contexts = self._build_term_contexts(candidates=candidates, records=records)

        llm_terms: Dict[str, str] = {}
        decisions = []
        if candidates:
            try:
                llm_decisions = self._request_llm_for_term_decisions(
                    candidates=candidates,
                    paper_context=paper_context,
                    term_contexts=term_contexts,
                    known_terms=known_terms,
                )
                for decision in llm_decisions:
                    source_term = str(decision.get("source_term", "")).strip()
                    selected = str(decision.get("selected_translation", "")).strip()
                    if not source_term or not selected:
                        continue
                    llm_terms[source_term] = selected
                    decisions.append({
                        "source_term": source_term,
                        "candidate_translations": decision.get("candidate_translations", [selected]),
                        "selected_translation": selected,
                        "reason": decision.get("reason", ""),
                        "decision_source": "llm",
                        "contexts": term_contexts.get(source_term, []),
                    })
            except Exception as e:
                for candidate in candidates:
                    decisions.append({
                        "source_term": candidate,
                        "candidate_translations": [],
                        "selected_translation": "",
                        "reason": str(e),
                        "decision_source": "llm_failed",
                        "contexts": term_contexts.get(candidate, []),
                    })

        terms = merge_term_pairs(
            known_terms.items(),
            llm_terms.items(),
            source_language=self.config.get("source_language", "en"),
        )
        write_project_terms_csv(project_terms_path(Path(self.output_dir)), terms)
        self._write_decision_log(paper_context=paper_context, decisions=decisions)
        self.log(f"Generated project terms: {project_terms_path(Path(self.output_dir))}")
        return {
            "ok": True,
            "project_terms_path": str(project_terms_path(Path(self.output_dir))),
            "project_terms_decisions_path": str(project_terms_decisions_path(Path(self.output_dir))),
        }

    def _process_latex_to_text(self, latex_code: str) -> str:
        latex_code = replace_href(latex_code or "")
        latex_code = replace_includegraphics(latex_code)
        text = LatexNodes2Text().latex_to_text(latex_code)
        return delete_ph(text).strip()

    def _collect_text_records(self, sections: List[Dict[str, Any]], captions: List[Dict[str, Any]], envs: List[Dict[str, Any]]) -> List[Dict[str, str]]:
        records: List[Dict[str, str]] = []
        for section in sections:
            if section.get("section") == "-1":
                continue
            text = self._process_latex_to_text(section.get("content", ""))
            if text:
                records.append({"part": "sec", "id": str(section.get("section", "")), "text": text})
        for caption in captions:
            text = self._process_latex_to_text(caption.get("content", ""))
            if text:
                records.append({"part": "cap", "id": str(caption.get("placeholder", "")), "text": text})
        for env in envs:
            if not env.get("need_trans", False):
                continue
            text = self._process_latex_to_text(env.get("content", ""))
            if text:
                records.append({"part": "env", "id": str(env.get("placeholder", "")), "text": text})
        return records

    def _extract_paper_context(self, sections: List[Dict[str, Any]], captions: List[Dict[str, Any]]) -> Dict[str, Any]:
        title = ""
        keywords: List[str] = []
        for caption in captions:
            cap_type = str(caption.get("cap_type", "")).lower()
            text = self._process_latex_to_text(caption.get("content", ""))
            if cap_type in {"title", "icmltitle"} and not title:
                title = text
            if cap_type == "keywords" and text:
                keywords = [item.strip() for item in re.split(r"[,;]", text) if item.strip()]

        abstract = ""
        for section in sections:
            text = self._process_latex_to_text(section.get("content", ""))
            if "abstract" in section.get("content", "").lower() or str(section.get("section")) == "0":
                abstract = text
                break

        category_map = self.config.get("category") or {}
        project_name = Path(self.project_dir or "").name
        return {
            "project_name": project_name,
            "title": title,
            "abstract": abstract,
            "keywords": keywords,
            "category": category_map.get(project_name, []),
        }

    def _extract_rule_candidates(self, records: List[Dict[str, str]]) -> List[str]:
        source_language = str(self.config.get("source_language", "en")).lower()
        if source_language != "en":
            return []
        counter: Counter[str] = Counter()
        pattern = re.compile(r"\b[a-zA-Z][a-zA-Z-]*(?:\s+[a-zA-Z][a-zA-Z-]*){1,4}\b")
        for record in records:
            for match in pattern.finditer(record.get("text", "")):
                phrase = re.sub(r"\s+", " ", match.group(0).strip().lower())
                if phrase in STOP_PHRASES:
                    continue
                if not any(word in phrase.split() for word in DOMAIN_WORDS):
                    continue
                counter[phrase] += 1
        return [phrase for phrase, _ in counter.most_common()]

    def _build_term_contexts(self, candidates: List[str], records: List[Dict[str, str]]) -> Dict[str, List[str]]:
        contexts: Dict[str, List[str]] = defaultdict(list)
        for candidate in candidates:
            pattern = re.compile(re.escape(candidate), re.IGNORECASE)
            for record in records:
                text = record.get("text", "")
                match = pattern.search(text)
                if not match:
                    continue
                start = max(0, match.start() - 120)
                end = min(len(text), match.end() + 120)
                contexts[candidate].append(text[start:end])
                if len(contexts[candidate]) >= 3:
                    break
        return dict(contexts)

    def _request_llm_for_term_decisions(
        self,
        candidates: List[str],
        paper_context: Dict[str, Any],
        term_contexts: Dict[str, List[str]],
        known_terms: Dict[str, str],
    ) -> List[Dict[str, Any]]:
        source_label = pm.language_label(self.config.get("source_language", "en"))
        target_label = pm.language_label(self.config.get("target_language", "ch"))
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        f"You are a {source_label}-{target_label} academic terminology expert. "
                        "Return only JSON with a decisions array. Each decision must include "
                        "source_term, candidate_translations, selected_translation, and reason."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "source_language": source_label,
                            "target_language": target_label,
                            "paper_context": paper_context,
                            "candidates": candidates,
                            "term_contexts": term_contexts,
                            "known_terms": known_terms,
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            "temperature": 0.2,
            "max_new_tokens": 4096,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        for attempt in range(1, 4):
            try:
                response = requests.post(self.base_url, json=payload, headers=headers, timeout=100)
                response.raise_for_status()
                content = response.json()["choices"][0]["message"]["content"].strip()
                data = json.loads(content)
                return data.get("decisions", [])
            except Exception:
                if attempt < 3:
                    time.sleep(3)
                    continue
                raise
        return []

    def _write_decision_log(self, paper_context: Dict[str, Any], decisions: List[Dict[str, Any]]) -> None:
        data = {
            "source_language": self.config.get("source_language", "en"),
            "target_language": self.config.get("target_language", "ch"),
            "paper_context": paper_context,
            "decisions": decisions,
        }
        path = project_terms_decisions_path(Path(self.output_dir))
        try:
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError as e:
            self.log(f"Failed to write project term decisions: {e}", level="warning")
```

- [ ] **Step 4: 运行 TerminologyAgent 测试**

Run:

```powershell
python -m unittest tests.test_terminology_agent
```

Expected: PASS.

- [ ] **Step 5: Commit**

Run:

```powershell
git add src/agents/tool_agents/terminology_agent.py tests/test_terminology_agent.py
git commit -m "feat(terms): 生成论文级术语表"
```

---

### Task 3: TranslatorAgent 读取 project_terms.csv 并启用术语模式

**Files:**
- Modify: `src/agents/tool_agents/translator_agent.py`
- Modify: `tests/test_multilingual_language_support.py`
- Modify: `tests/test_translator_retry_prompt.py`

- [ ] **Step 1: 写 failing tests**

Append to `MultilingualTerminologyTests` in `tests/test_multilingual_language_support.py`:

```python
    def test_project_terms_are_loaded_for_non_english_chinese_pair(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_dir = Path(tmp_dir)
            (output_dir / "project_terms.csv").write_text(
                "Source Term,Target Translation\nGraphmodell,グラフモデル\n",
                encoding="utf-8",
            )
            agent = TranslatorAgent(
                config={
                    "source_language": "de",
                    "target_language": "jp",
                    "llm_config": {},
                },
                project_dir="paper",
                output_dir=str(output_dir),
            )

            agent.build_term_dict()

        self.assertEqual(agent.term_dict, {"Graphmodell": "グラフモデル"})

    def test_user_terms_override_project_terms(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_dir = Path(tmp_dir) / "output"
            output_dir.mkdir()
            user_terms = Path(tmp_dir) / "user_terms.csv"
            user_terms.write_text("Graph,用户图\n", encoding="utf-8")
            (output_dir / "project_terms.csv").write_text(
                "Source Term,Target Translation\nGraph,项目图\nTree,树\n",
                encoding="utf-8",
            )
            agent = TranslatorAgent(
                config={
                    "source_language": "en",
                    "target_language": "ch",
                    "user_term": str(user_terms),
                    "llm_config": {},
                },
                project_dir="paper",
                output_dir=str(output_dir),
            )

            agent.build_term_dict()

        self.assertEqual(agent.term_dict["Graph"], "用户图")
        self.assertEqual(agent.term_dict["Tree"], "树")
```

Append to `TranslatorRetryPromptTests` in `tests/test_translator_retry_prompt.py`:

```python
    def test_project_terms_enable_terms_prompt_for_plain_mode(self):
        agent = TranslatorAgent(config={"llm_config": {}}, trans_mode="plain")
        agent.term_dict = {"Graph": "图"}
        agent._project_terms_loaded = True

        self.assertTrue(agent._should_use_terms_prompt())
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```powershell
python -m unittest tests.test_multilingual_language_support tests.test_translator_retry_prompt
```

Expected: FAIL because project terms are not loaded and `_should_use_terms_prompt` does not exist.

- [ ] **Step 3: 修改 TranslatorAgent imports 和初始化**

Modify imports near top of `src/agents/tool_agents/translator_agent.py`:

```python
from src.terminology import load_term_csv, project_terms_path, merge_term_pairs
```

Add in `__init__` after `self.term_dict = {}`:

```python
        self._project_terms_loaded = False
```

- [ ] **Step 4: 替换 `build_term_dict()`**

Replace the whole `build_term_dict()` method with:

```python
    def build_term_dict(self):
        source_language = self.config.get("source_language", "en")
        user_terms = {}
        project_terms = {}
        default_terms = {}

        if self.user_term:
            user_result = load_term_csv(Path(self.user_term), source_language=source_language)
            for warning in user_result.warnings:
                print(f"Warning: {warning}")
            user_terms = user_result.terms

        if self.output_dir:
            terms_path = project_terms_path(Path(self.output_dir))
            if terms_path.exists():
                project_result = load_term_csv(terms_path, source_language=source_language)
                for warning in project_result.warnings:
                    print(f"Warning: {warning}")
                project_terms = project_result.terms
                self._project_terms_loaded = True

        if self._uses_default_english_chinese_terms():
            arxiv_id = os.path.basename(self.project_dir or "")
            category_map = self.category or {}
            if category_map.get(arxiv_id):
                term_dict_loaded = False
                for category in category_map[arxiv_id]:
                    file_path = os.path.join("terms", f"{category}.csv")
                    try:
                        df = pd.read_csv(file_path, header=None, names=["Source Term", "Target Translation"])
                        default_terms.update(zip(df["Source Term"], df["Target Translation"]))
                        term_dict_loaded = True
                    except FileNotFoundError:
                        continue
                if not term_dict_loaded:
                    default_terms.update(self._load_default_terms_file())
            else:
                default_terms.update(self._load_default_terms_file())

        self.term_dict.update(merge_term_pairs(
            user_terms.items(),
            project_terms.items(),
            default_terms.items(),
            source_language=source_language,
        ))
```

Add helper below `build_term_dict()`:

```python
    def _load_default_terms_file(self) -> Dict[str, str]:
        try:
            df = pd.read_csv("terms/default.csv", header=None, names=["Source Term", "Target Translation"])
            return dict(zip(df["Source Term"], df["Target Translation"]))
        except FileNotFoundError as e:
            print(f"Error: Default terminology file not found: {e}")
            return {}

    def _should_use_terms_prompt(self) -> bool:
        return self.trans_mode == "terms" or self._project_terms_loaded
```

- [ ] **Step 5: 使用 `_should_use_terms_prompt()`**

In `src/agents/tool_agents/translator_agent.py`, replace every condition:

```python
elif self.trans_mode == "terms":
```

inside `_translate_section`, `_translate_caption`, and `_translate_env` with:

```python
elif self._should_use_terms_prompt():
```

Replace in `_request_llm_for_retrans_error_parts`:

```python
        if self.trans_mode == "terms":
```

with:

```python
        if self._should_use_terms_prompt():
```

- [ ] **Step 6: 运行 translator 相关测试**

Run:

```powershell
python -m unittest tests.test_multilingual_language_support tests.test_translator_retry_prompt
```

Expected: PASS.

- [ ] **Step 7: Commit**

Run:

```powershell
git add src/agents/tool_agents/translator_agent.py tests/test_multilingual_language_support.py tests/test_translator_retry_prompt.py
git commit -m "feat(translator): 加载论文级术语表"
```

---

### Task 4: Coordinator 首次流程接入术语生成和审核暂停

**Files:**
- Modify: `src/agents/coordinator_agent.py`
- Modify: `tests/test_coordinator_messages.py`

- [ ] **Step 1: 写 failing tests**

Append imports in `tests/test_coordinator_messages.py`:

```python
    build_review_required_result,
    should_run_terminology_scan,
```

Append tests:

```python
    def test_should_run_terminology_scan_respects_config(self):
        self.assertTrue(should_run_terminology_scan({"terminology": {"enabled": True}}))
        self.assertTrue(should_run_terminology_scan({}))
        self.assertFalse(should_run_terminology_scan({"terminology": {"enabled": False}}))

    def test_build_review_required_result_marks_workflow_not_ok(self):
        result = build_review_required_result(
            project_name="paper",
            project_terms_path=r"outputs\ch_paper\project_terms.csv",
            project_terms_decisions_path=r"outputs\ch_paper\project_terms_decisions.json",
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "needs_term_review")
        self.assertIn("project_terms.csv", result["project_terms_path"])
        self.assertIn("project_terms_decisions.json", result["project_terms_decisions_path"])
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```powershell
python -m unittest tests.test_coordinator_messages
```

Expected: FAIL because helper functions do not exist.

- [ ] **Step 3: 添加 Coordinator helper**

Modify imports in `src/agents/coordinator_agent.py`:

```python
from .tool_agents.terminology_agent import TerminologyAgent
from src.terminology import TerminologyConfig
```

Add helper functions near `build_workflow_result`:

```python
def should_run_terminology_scan(config: Dict[str, Any]) -> bool:
    return TerminologyConfig.from_config(config or {}).enabled


def build_review_required_result(
    project_name: str,
    project_terms_path: str,
    project_terms_decisions_path: str,
) -> Dict[str, Any]:
    return {
        "project_name": project_name,
        "ok": False,
        "status": "needs_term_review",
        "pdf_path": None,
        "errors_report_path": None,
        "validation_summary": {"warnings": 0, "errors": 0, "total": 0},
        "error": "Project terms generated; review project_terms.csv before translation.",
        "project_terms_path": project_terms_path,
        "project_terms_decisions_path": project_terms_decisions_path,
    }
```

- [ ] **Step 4: Wire TerminologyAgent into `workflow_latextrans_async()`**

In `workflow_latextrans_async()`, after:

```python
        parser_agent.execute()
```

insert:

```python
        terminology_config = TerminologyConfig.from_config(self.config or {})
        if terminology_config.enabled:
            terminology_agent = TerminologyAgent(
                config=self.config,
                project_dir=self.project_dir,
                output_dir=transed_project_dir,
            )
            terminology_result = terminology_agent.execute()
            if terminology_config.review_before_translate:
                print(
                    f"🤖⏸️ {self.name}: Project terms generated for {base_name}. "
                    f"Review {terminology_result['project_terms_path']} and rerun with --retranslate-with-terms."
                )
                return build_review_required_result(
                    project_name=base_name,
                    project_terms_path=terminology_result["project_terms_path"],
                    project_terms_decisions_path=terminology_result["project_terms_decisions_path"],
                )
```

- [ ] **Step 5: 运行 coordinator tests**

Run:

```powershell
python -m unittest tests.test_coordinator_messages
```

Expected: PASS.

- [ ] **Step 6: Commit**

Run:

```powershell
git add src/agents/coordinator_agent.py tests/test_coordinator_messages.py
git commit -m "feat(coordinator): 接入论文术语生成"
```

---

### Task 5: 全量重译 workflow 与 CLI/runtime 入口

**Files:**
- Modify: `src/agents/coordinator_agent.py`
- Modify: `src/runtime.py`
- Modify: `main.py`
- Modify: `tests/test_runtime_project_results.py`
- Modify: `tests/test_coordinator_messages.py`

- [ ] **Step 1: 写 failing runtime tests**

Append to `RuntimeProjectResultTests` in `tests/test_runtime_project_results.py`:

```python
    def test_run_projects_uses_retranslation_workflow_when_requested(self):
        calls = []

        class FakeCoordinatorAgent:
            def __init__(self, config, project_dir, output_dir):
                self.project_dir = project_dir

            def workflow_latextrans_with_existing_terms(self):
                calls.append(("retranslate", self.project_dir))
                return {
                    "ok": True,
                    "pdf_path": r"outputs\ch_paper\ch_paper.pdf",
                    "validation_summary": {"warnings": 0, "errors": 0, "total": 0},
                    "error": None,
                }

            def workflow_latextrans(self):
                calls.append(("normal", self.project_dir))
                return {"ok": False, "error": "wrong path"}

        with patch("src.runtime.CoordinatorAgent", FakeCoordinatorAgent):
            with redirect_stdout(StringIO()):
                status = run_projects(
                    config={"retranslate_with_terms": True},
                    projects=[r"D:\paper"],
                    output_dir="outputs",
                )

        self.assertEqual(calls, [("retranslate", r"D:\paper")])
        self.assertEqual(len(status["completed_projects"]), 1)
```

- [ ] **Step 2: 写 failing coordinator helper test**

Append to `tests/test_coordinator_messages.py`:

```python
    def test_clear_translated_content_preserves_nontranslated_sections(self):
        from src.agents.coordinator_agent import clear_translated_content

        sections = [
            {"section": "-1", "content": "preamble", "trans_content": "preamble"},
            {"section": "0", "content": "front", "trans_content": "front"},
            {"section": "1", "content": "body", "trans_content": "旧译文"},
        ]
        captions = [{"content": "caption", "trans_content": "旧图题"}]
        envs = [
            {"content": "math", "trans_content": "", "need_trans": False},
            {"content": "env", "trans_content": "旧环境", "need_trans": True},
        ]

        clear_translated_content(sections, captions, envs)

        self.assertEqual(sections[0]["trans_content"], "preamble")
        self.assertEqual(sections[1]["trans_content"], "front")
        self.assertEqual(sections[2]["trans_content"], "")
        self.assertEqual(captions[0]["trans_content"], "")
        self.assertEqual(envs[0]["trans_content"], "")
        self.assertEqual(envs[1]["trans_content"], "")
```

- [ ] **Step 3: 运行测试确认失败**

Run:

```powershell
python -m unittest tests.test_runtime_project_results tests.test_coordinator_messages
```

Expected: FAIL because `workflow_latextrans_with_existing_terms` and `clear_translated_content` do not exist, and `run_projects` always calls normal workflow.

- [ ] **Step 4: 添加 clear helper 和重译 workflow**

Modify imports in `src/agents/coordinator_agent.py`:

```python
from src.terminology import require_retranslation_inputs
```

Add helper near other helpers:

```python
def clear_translated_content(sections: List[Dict[str, Any]], captions: List[Dict[str, Any]], envs: List[Dict[str, Any]]) -> None:
    for section in sections:
        if str(section.get("section")) in {"-1", "0"}:
            section["trans_content"] = section.get("content", section.get("trans_content", ""))
        else:
            section["trans_content"] = ""
    for caption in captions:
        caption["trans_content"] = ""
    for env in envs:
        env["trans_content"] = ""
```

Add method to `CoordinatorAgent`:

```python
    async def workflow_latextrans_with_existing_terms_async(self) -> Dict[str, Any]:
        base_name = os.path.basename(self.project_dir)
        transed_project_dir = os.path.join(self.output_dir, f"{self.target_language}_{base_name}")
        require_retranslation_inputs(Path(transed_project_dir))

        translator_agent = TranslatorAgent(
            config=self.config,
            project_dir=self.project_dir,
            output_dir=transed_project_dir,
            trans_mode=self.mode,
        )

        sections = translator_agent.read_file(Path(transed_project_dir, "sections_map.json"), "json")
        captions = translator_agent.read_file(Path(transed_project_dir, "captions_map.json"), "json")
        envs = translator_agent.read_file(Path(transed_project_dir, "envs_map.json"), "json")
        clear_translated_content(sections, captions, envs)
        translator_agent.save_file(Path(transed_project_dir, "sections_map.json"), "json", sections)
        translator_agent.save_file(Path(transed_project_dir, "captions_map.json"), "json", captions)
        translator_agent.save_file(Path(transed_project_dir, "envs_map.json"), "json", envs)

        await translator_agent.execute()

        validator_agent = ValidatorAgent(
            config=self.config,
            project_dir=self.project_dir,
            output_dir=transed_project_dir,
        )
        errors_report = validator_agent.execute()
        retryable_reports = filter_retryable_reports(errors_report)
        max_retries = self.validation_policy.max_attempts()
        retry_count = 0
        if retryable_reports:
            translator_agent.enable_retranslation()

        while retryable_reports and retry_count < max_retries:
            translator_agent.errors_report = retryable_reports
            await translator_agent.execute(error_retry_count=retry_count, Maxtry=max_retries)
            retry_results = validator_agent.execute(retryable_reports)
            errors_report = merge_validation_reports(errors_report, retryable_reports, retry_results)
            validator_agent.save_file(Path(transed_project_dir, "errors_report.json"), "json", errors_report)
            retryable_reports = filter_retryable_reports(errors_report)
            retry_count += 1

        validation_summary = summarize_validation_reports(errors_report or [])
        validation_failed = self.validation_policy.should_fail(validation_summary)
        errors_report_path = os.path.join(transed_project_dir, "errors_report.json")

        if not should_generate_pdf_after_validation(
            validation_summary=validation_summary,
            generate_pdf_on_error=self.validation_policy.generate_pdf_on_error(),
        ):
            return build_workflow_result(
                project_name=base_name,
                pdf_path=None,
                errors_report_path=errors_report_path,
                validation_summary=validation_summary,
                validation_failed=validation_failed,
            )

        generator_agent = GeneratorAgent(
            config=self.config,
            project_dir=self.project_dir,
            output_dir=transed_project_dir,
        )
        try:
            pdf_file_path = generator_agent.execute()
        except Exception as e:
            return build_workflow_result(
                project_name=base_name,
                pdf_path=None,
                errors_report_path=errors_report_path,
                validation_summary=validation_summary,
                validation_failed=True,
                error=str(e),
            )

        if not pdf_file_path:
            return build_workflow_result(
                project_name=base_name,
                pdf_path=None,
                errors_report_path=errors_report_path,
                validation_summary=validation_summary,
                validation_failed=True,
                error="PDF generation returned no output path",
            )

        new_pdf_path = os.path.join(transed_project_dir, f"{self.target_language}_{base_name}.pdf")
        shutil.move(pdf_file_path, new_pdf_path)
        print(
            format_translation_result_message(
                system_name=self.name,
                base_name=base_name,
                pdf_path=new_pdf_path,
                validation_summary=validation_summary,
                validation_failed=validation_failed,
            )
        )
        return build_workflow_result(
            project_name=base_name,
            pdf_path=new_pdf_path,
            errors_report_path=errors_report_path,
            validation_summary=validation_summary,
            validation_failed=validation_failed,
        )

    def workflow_latextrans_with_existing_terms(self) -> Dict[str, Any]:
        if hasattr(self, "loop") and not self.loop.is_closed():
            self.loop.close()
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        try:
            return self.loop.run_until_complete(self.workflow_latextrans_with_existing_terms_async())
        finally:
            if tasks := asyncio.all_tasks(self.loop):
                self.loop.run_until_complete(asyncio.gather(*tasks, return_exceptions=True))
            if sys.platform == "win32":
                self.loop.run_until_complete(self.loop.shutdown_asyncgens())
            self.loop.run_until_complete(self.loop.shutdown_default_executor())
```

- [ ] **Step 5: Wire runtime**

In `src/runtime.py`, update `load_runtime_config()` after `update_term` handling:

```python
    if overrides.get("retranslate_with_terms") is not None:
        config["retranslate_with_terms"] = bool(overrides["retranslate_with_terms"])
```

In `run_projects()`, replace:

```python
            workflow_result = latex_trans.workflow_latextrans()
```

with:

```python
            if config.get("retranslate_with_terms", False):
                workflow_result = latex_trans.workflow_latextrans_with_existing_terms()
            else:
                workflow_result = latex_trans.workflow_latextrans()
```

- [ ] **Step 6: Wire CLI**

In `main.py`, add parser argument after `--all-existing`:

```python
    parser.add_argument(
        "--retranslate-with-terms",
        action="store_true",
        help="Reuse an existing parsed output directory and project_terms.csv, then fully retranslate.",
    )
```

After output override handling, add:

```python
    if args.retranslate_with_terms:
        config["retranslate_with_terms"] = True
```

No other CLI behavior changes in this task.

- [ ] **Step 7: 运行 tests**

Run:

```powershell
python -m unittest tests.test_runtime_project_results tests.test_coordinator_messages
```

Expected: PASS.

- [ ] **Step 8: Commit**

Run:

```powershell
git add src/agents/coordinator_agent.py src/runtime.py main.py tests/test_runtime_project_results.py tests/test_coordinator_messages.py
git commit -m "feat(cli): 支持术语表全量重译"
```

---

### Task 6: 集成回归与计划修正

**Files:**
- Verify all modified files

- [ ] **Step 1: 运行术语相关测试**

Run:

```powershell
python -m unittest tests.test_terminology tests.test_terminology_agent tests.test_multilingual_language_support tests.test_translator_retry_prompt
```

Expected: PASS.

- [ ] **Step 2: 运行 workflow 相关测试**

Run:

```powershell
python -m unittest tests.test_coordinator_messages tests.test_runtime_project_results
```

Expected: PASS.

- [ ] **Step 3: 运行完整测试**

Run:

```powershell
python -m unittest discover tests
```

Expected: PASS.

- [ ] **Step 4: 检查默认配置解析**

Run:

```powershell
python -c "import toml; from src.terminology import TerminologyConfig; c=toml.load('config/default.toml'); t=TerminologyConfig.from_config(c); print(t.enabled, t.review_before_translate, t.max_llm_candidates)"
```

Expected output:

```text
True False 30
```

- [ ] **Step 5: 检查 git diff**

Run:

```powershell
git status --short
git diff --stat
```

Expected after task commits: working tree is clean.

- [ ] **Step 6: Commit verification fixes if needed**

If any verification fix was needed, commit only task-related files:

```powershell
git add src\terminology.py src\agents\tool_agents\terminology_agent.py src\agents\tool_agents\translator_agent.py src\agents\coordinator_agent.py src\runtime.py main.py config\default.toml config\template.toml tests\test_terminology.py tests\test_terminology_agent.py tests\test_multilingual_language_support.py tests\test_translator_retry_prompt.py tests\test_coordinator_messages.py tests\test_runtime_project_results.py
git commit -m "test(terms): 完成论文术语表回归验证"
```

If no files changed, skip this step.
