# Lite Translation Engine and TUI Modes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a PDF-to-Markdown lite translation engine and adapt the Textual TUI to run and display heavy/lite tasks in isolated modes.

**Architecture:** Keep the existing heavy workflow behavior behind a small engine dispatch boundary, and implement lite as a separate PDF workflow using the MinerU Python SDK, Markdown block translation, and Pandoc/XeLaTeX. Use shared runtime events and task metadata so the TUI can filter history, display engine-specific details, and switch modes without cancelling already-running tasks.

**Tech Stack:** Python 3.10+, standard `unittest`, Textual, asyncio/aiohttp, Requests, TOML, MinerU Python SDK (`mineru-open-sdk`), Pandoc, XeLaTeX, existing LaTeXTrans agents and Zotero Web API adapter.

## Global Constraints

- Use the `latextrans` conda environment for all project runs and tests.
- Use Python 3.10+ style, 4-space indentation, explicit imports, and `pathlib.Path` where practical.
- Every new class and function must have a docstring explaining its purpose.
- Preserve existing heavy CLI behavior; this plan does not add lite arguments to `main.py`.
- TUI engine precedence is `--engine/-e` > `ui.toml.engine` > `heavy`.
- Startup `--engine/-e` and the entry-page mode switch affect only the current TUI session and do not write `ui.toml`.
- `ui.toml.engine` is an editable persisted default in the settings page.
- Heavy uses `outputs/`; lite uses a separate sibling root `output-lite/` by default.
- Lite accepts exactly one arXiv ID/URL, PDF URL, or local PDF path per task; it does not support batch input.
- Lite uses the MinerU Python SDK, not the MinerU CLI.
- Lite Markdown is split at non-fenced `##` headings; `###` remains inside its parent block.
- Lite does not use `ValidatorAgent`, `errors_report.json`, validation retries, or `--retranslate-with-terms`.
- Any lite Markdown or PDF generation failure marks the project failed while retaining intermediate artifacts.
- A lite task stores all artifacts in one timestamped project directory.
- Tests must not mutate the real `config/ui.toml`; mock configuration saves or use a temporary project root.
- Before completion, run the relevant focused tests and `python -m unittest discover tests` when feasible, then verify the final diff contains only task-related changes.

---

## File and Module Map

Create the following focused modules:

- `src/engines/__init__.py`: public engine exports.
- `src/engines/base.py`: engine name validation, common input/result protocol, and engine-independent output metadata.
- `src/engines/heavy.py`: adapter that invokes the existing `CoordinatorAgent` heavy workflow.
- `src/engines/lite.py`: lite orchestration for one prepared PDF project.
- `src/engines/lite_inputs.py`: input recognition, arXiv/PDF URL acquisition, local PDF validation, stable names, and timestamped directories.
- `src/engines/lite_markdown.py`: Markdown scanning, `##` block model, protected regions, and ordered reconstruction.
- `src/engines/lite_pdf.py`: Pandoc/XeLaTeX invocation and output validation.
- `src/agents/tool_agents/markdown_terminology_agent.py`: terminology generation from Markdown while reusing existing terminology semantics.
- `src/agents/tool_agents/markdown_translator_agent.py`: asynchronous Markdown block translation with glossary support.

Modify these existing modules:

- `src/config.py`: shared engine config helpers and validation where runtime config needs them.
- `src/runtime.py`: engine-aware preparation, dispatch, result/event fields, and lite task execution.
- `src/tui/config.py`: new-format UI config defaults and legacy migration.
- `src/tui/config_schema.py`: shared/heavy/lite field definitions and engine filtering.
- `src/tui/input_parser.py`: lite single-input validation.
- `src/tui/runner.py`: pass task engine and select the correct output root/workflow.
- `src/tui/process_runner.py`: carry engine through spawned task processes.
- `src/tui/state.py`: engine and Markdown artifact state.
- `src/tui/history.py`: engine-aware metadata and history loading.
- `src/tui/app.py`: startup parsing, mode switch, dynamic compose/display, filtering, Markdown preview, and Zotero controls.
- `src/tui/zotero_adapter.py`: child-note creation.
- `config/default.toml`, `config/template.toml`, `config/ui.toml`: new shared/heavy/lite layout.
- `requirements.txt`: MinerU SDK dependency.
- `README.md`, `README_ZH.md`: TUI engine usage and configuration documentation.

Modify or add tests under `tests/`, keeping the existing standard-library `unittest` style.

---

## Task 1: Add Engine Names and UI Configuration Migration

**Files:**
- Create: `src/engines/__init__.py`
- Create: `src/engines/base.py`
- Modify: `src/tui/config.py`
- Modify: `src/tui/config_schema.py`
- Modify: `config/default.toml`
- Modify: `config/template.toml`
- Modify: `config/ui.toml`
- Test: `tests/test_engine_config.py`
- Test: `tests/test_tui_config.py`
- Test: `tests/test_tui_config_schema.py`

**Interfaces:**

- Produce `EngineName = Literal["heavy", "lite"]` and `normalize_engine(value: object, default: str = "heavy") -> str` in `src/engines/base.py`; invalid values raise `ValueError` listing `heavy` and `lite`.
- Produce `engine_config(config: dict[str, Any], engine: str) -> dict[str, Any]`, which returns a deep-copied effective config with the selected engine's fields merged into the existing runtime-facing shape without mutating the source config.
- Produce `load_ui_config(project_root: Path) -> dict[str, Any]` that initializes and migrates the file while preserving user paths.
- Produce `config_fields_for_engine(engine: str) -> tuple[ConfigField, ...]` and `grouped_config_fields(engine: str) -> list[tuple[str, list[ConfigField]]]`.

- [x] **Step 1: Write failing tests for engine normalization and migration.**

```python
class EngineConfigTests(unittest.TestCase):
    def test_normalize_engine_accepts_only_heavy_and_lite(self):
        self.assertEqual(normalize_engine("heavy"), "heavy")
        self.assertEqual(normalize_engine("LITE"), "lite")
        with self.assertRaises(ValueError):
            normalize_engine("unknown")

    def test_legacy_config_moves_heavy_fields_and_adds_lite_defaults(self):
        legacy = {
            "source_language": "en",
            "tex_sources_dir": "old-tex",
            "output_dir": "old-output",
            "paper_list": ["2508.18791"],
            "validation": {"retry": {"max_attempts": 4}},
        }
        migrated = migrate_ui_config(legacy)
        self.assertEqual(migrated["engine"], "heavy")
        self.assertEqual(migrated["heavy"]["tex_sources_dir"], "old-tex")
        self.assertEqual(migrated["heavy"]["output_dir"], "old-output")
        self.assertEqual(migrated["heavy"]["paper_list"], ["2508.18791"])
        self.assertEqual(migrated["heavy"]["validation"]["retry"]["max_attempts"], 4)
        self.assertEqual(migrated["lite"]["output_dir"], "output-lite")
```

- [x] **Step 2: Run focused tests and verify they fail.**

Run: `conda run -n latextrans python -m unittest tests.test_engine_config tests.test_tui_config tests.test_tui_config_schema`

Expected: FAIL because the engine helpers and migration behavior do not exist.

- [x] **Step 3: Implement the new config layout and migration.**

Use this effective file shape:

```toml
engine = "heavy"
source_language = "en"
target_language = "ch"
update_term = "False"
mode = "plain"
user_term = ""

[terminology]
...

[llm_config]
...

[zotero]
...

[heavy]
paper_list = []
tex_sources_dir = "tex source"
output_dir = "outputs"
retranslate_with_terms = false

[heavy.validation.retry]
...

[lite]
output_dir = "output-lite"
```

Keep a migration function separate from file I/O so it can be tested with dictionaries. Ensure `ensure_ui_config` writes the migrated structure only when it finds a legacy file; never replace existing values with defaults. Add `engine` to the shared settings field list, keep `validation` fields only under heavy, and keep `retranslate_with_terms` only under heavy.

`engine_config` must merge selected `[heavy]` or `[lite]` values into a new runtime-facing dictionary. Heavy callers receive `tex_sources_dir`, `output_dir`, `paper_list`, `retranslate_with_terms`, and `validation`; lite callers receive `output_dir` plus `engine="lite"` and no heavy validation fields.

- [x] **Step 4: Run focused tests and verify they pass.**

Run: `conda run -n latextrans python -m unittest tests.test_engine_config tests.test_tui_config tests.test_tui_config_schema`

Expected: PASS.

- [x] **Step 5: Commit the configuration foundation.**

Implementation note: Added engine normalization, effective engine config merging, legacy UI configuration migration, and engine-scoped settings fields. Focused configuration tests pass.

```bash
git add src/engines src/tui/config.py src/tui/config_schema.py config/default.toml config/template.toml config/ui.toml tests/test_engine_config.py tests/test_tui_config.py tests/test_tui_config_schema.py
git commit -m "feat(config): add heavy and lite engine settings"
```

---

## Task 2: Implement Lite Input Acquisition and Project Naming

**Files:**
- Create: `src/engines/lite_inputs.py`
- Modify: `src/project_sources.py` only if a small reusable download helper is required; preserve existing heavy behavior.
- Test: `tests/test_lite_inputs.py`

**Interfaces:**

- Produce `LiteInputKind = Literal["arxiv", "pdf_url", "local_pdf"]`.
- Produce `class LiteInputSpec` with `kind`, `original`, `stable_name`, and optional `url` fields.
- Produce `parse_lite_input(value: str) -> LiteInputSpec`.
- Produce `prepare_lite_project(spec: LiteInputSpec, output_root: Path, http_get: Callable[..., Any] | None = None, now: datetime | None = None) -> PreparedLiteProject`.
- `PreparedLiteProject` must expose `project_dir: Path`, `source_pdf: Path`, `project_name: str`, `input_item: str`, and `input_type: str`.

- [x] **Step 1: Write failing tests for all accepted input forms.**

```python
class LiteInputTests(unittest.TestCase):
    def test_arxiv_id_and_urls_normalize_to_arxiv_pdf(self):
        self.assertEqual(parse_lite_input("2508.18791").kind, "arxiv")
        self.assertEqual(parse_lite_input("https://arxiv.org/abs/2508.18791").kind, "arxiv")
        self.assertEqual(parse_lite_input("https://arxiv.org/pdf/2508.18791.pdf").kind, "arxiv")

    def test_non_arxiv_url_is_pdf_url(self):
        spec = parse_lite_input("https://example.org/papers/report.pdf")
        self.assertEqual(spec.kind, "pdf_url")
        self.assertEqual(spec.stable_name, "report")

    def test_local_input_requires_pdf_suffix(self):
        self.assertEqual(parse_lite_input("paper.pdf").kind, "local_pdf")
        with self.assertRaises(ValueError):
            parse_lite_input("paper.tex")

    def test_project_directory_uses_stable_name_and_timestamp(self):
        spec = parse_lite_input("2508.18791")
        prepared = prepare_lite_project(
            spec,
            Path(self.tempdir) / "output-lite",
            now=datetime(2026, 9, 9, 20, 30, 0),
            download_pdf=lambda url, destination: destination.write_bytes(b"%PDF-1.7"),
        )
        self.assertEqual(prepared.project_dir.name, "2508.18791_20260909T203000")
        self.assertEqual(prepared.source_pdf.name, "source.pdf")
```

- [x] **Step 2: Run the focused input tests and verify failure.**

Run: `conda run -n latextrans python -m unittest tests.test_lite_inputs`

Expected: FAIL because lite input parsing and preparation are not implemented.

- [x] **Step 3: Implement input parsing and preparation.**

Recognize versioned arXiv IDs with the existing project convention. For arXiv abstract URLs, derive `https://arxiv.org/pdf/<id>.pdf`; for arXiv PDF URLs, preserve the normalized PDF URL. For non-arXiv HTTP/HTTPS inputs, download the URL into the timestamped project directory as `source.pdf`. For local PDF inputs, copy the source to `source.pdf` and reject missing, non-file, or non-PDF paths.

Sanitize stable names to safe path components while retaining alphanumeric characters, hyphens, underscores, dots, and CJK characters. Use `datetime.now()` when no timestamp is injected. Do not silently overwrite an existing timestamped directory; if the exact timestamp path exists, append a numeric suffix.

Make the HTTP download dependency injectable and ensure partial files are removed on network or `OSError` failures.

- [x] **Step 4: Run focused tests and verify success.**

Run: `conda run -n latextrans python -m unittest tests.test_lite_inputs`

Expected: PASS.

- [x] **Step 5: Commit the lite input module.**

Implementation note: Added Lite PDF/arXiv/local input parsing, self-contained source PDF preparation, safe project names, and failure cleanup.

```bash
git add src/engines/lite_inputs.py tests/test_lite_inputs.py
git commit -m "feat(lite): add pdf input acquisition"
```

---

## Task 3: Implement Markdown Scanning, Protection, and Ordered Blocks

**Files:**
- Create: `src/engines/lite_markdown.py`
- Test: `tests/test_lite_markdown.py`

**Interfaces:**

- Produce `MarkdownBlock(index: int, text: str, translatable: bool = True)`.
- Produce `split_markdown(text: str) -> list[MarkdownBlock]`.
- Produce `rebuild_markdown(blocks: Sequence[MarkdownBlock]) -> str`.
- Produce `protect_markdown(text: str) -> ProtectedMarkdown` and `restore_markdown(text: str, protected: ProtectedMarkdown) -> str`.
- `ProtectedMarkdown` must contain the protected-token mapping and the protected text.

- [x] **Step 1: Write failing tests for the `##` scanner.**

```python
class MarkdownBlockTests(unittest.TestCase):
    def test_splits_before_first_heading_and_at_second_level_headings_only(self):
        source = "front\n\n## First\nbody\n### Child\nchild\n\n## Second\nbody2"
        blocks = split_markdown(source)
        self.assertEqual(len(blocks), 3)
        self.assertEqual(blocks[0].text, "front\n\n")
        self.assertIn("## First", blocks[1].text)
        self.assertIn("### Child", blocks[1].text)
        self.assertIn("## Second", blocks[2].text)

    def test_heading_inside_fenced_code_is_not_a_split(self):
        source = "## A\n```text\n## not a heading\n```\nbody\n## B\nend"
        blocks = split_markdown(source)
        self.assertEqual(len(blocks), 2)
        self.assertIn("## not a heading", blocks[0].text)

    def test_rebuild_preserves_original_order(self):
        blocks = split_markdown("## A\na\n## B\nb")
        blocks[0] = MarkdownBlock(blocks[0].index, "## A\n翻译A\n")
        blocks[1] = MarkdownBlock(blocks[1].index, "## B\n翻译B")
        self.assertEqual(rebuild_markdown(blocks), "## A\n翻译A\n## B\n翻译B")
```

- [x] **Step 2: Run the Markdown tests and verify failure.**

Run: `conda run -n latextrans python -m unittest tests.test_lite_markdown`

Expected: FAIL because the scanner and reconstruction functions do not exist.

- [x] **Step 3: Implement the stateful scanner and protected-region codec.**

Scan line by line with fenced-code state. Recognize only a line whose first non-whitespace characters are exactly `##` followed by whitespace or end-of-line; do not recognize `###`, indented code, or headings inside fences. Preserve all original separators in block text so concatenation does not change Markdown layout.

The protection codec must replace and restore code fences, inline code, math spans, URLs, image destinations, table separator punctuation, front-matter, and footnote reference structure using collision-resistant tokens that cannot be produced by normal Markdown input. The codec must leave headings, paragraphs, link labels, table cell text, image alt text, and footnote bodies available to the translator.

Ensure `rebuild_markdown` sorts by block index and rejects duplicate or missing indices rather than silently producing corrupt output.

- [x] **Step 4: Run focused tests and add protection regression cases.**

Run: `conda run -n latextrans python -m unittest tests.test_lite_markdown`

Expected: PASS, including tests that code, formulas, URLs, table separators, front-matter, and footnote structures survive protect/restore unchanged.

- [x] **Step 5: Commit the Markdown module.**

Implementation note: Added fenced-heading splitting, protected Markdown reconstruction, and regression coverage for links, code, tables, footnotes, and references.

```bash
git add src/engines/lite_markdown.py tests/test_lite_markdown.py
git commit -m "feat(lite): split and protect markdown blocks"
```

---

## Task 4: Add MinerU SDK and Pandoc Adapters

**Files:**
- Create: `src/engines/lite_pdf.py`
- Create: `src/engines/lite_mineru.py`
- Modify: `requirements.txt`
- Test: `tests/test_lite_adapters.py`

**Interfaces:**

- Produce `class MineruMarkdownExtractor` with `extract(source_pdf: Path, output_dir: Path) -> Path`.
- Produce `class PandocPdfGenerator` with `generate(markdown_path: Path, pdf_path: Path, target_language: str) -> Path`.
- Both adapters must accept injected runner/client factories for tests.

- [x] **Step 1: Write failing adapter tests using fakes.**

```python
class LiteAdapterTests(unittest.TestCase):
    def test_mineru_adapter_writes_markdown_and_resources(self):
        client = FakeMineruClient(markdown="# Title\n![x](images/a.png)", resources={"images/a.png": b"png"})
        result = MineruMarkdownExtractor(client_factory=lambda: client).extract(
            Path("source.pdf"), Path(self.tempdir)
        )
        self.assertEqual(result, Path(self.tempdir) / "source.md")
        self.assertTrue((Path(self.tempdir) / "images" / "a.png").is_file())

    def test_pandoc_adapter_requires_a_nonempty_pdf_output(self):
        runner = FakePandocRunner()
        result = PandocPdfGenerator(runner=runner).generate(
            Path("translated.md"), Path(self.tempdir) / "translated.pdf", "ch"
        )
        self.assertEqual(result.name, "translated.pdf")
        self.assertIn("xelatex", runner.command)
```

- [x] **Step 2: Run adapter tests and verify failure.**

Run: `conda run -n latextrans python -m unittest tests.test_lite_adapters`

Expected: FAIL because the adapters do not exist.

- [x] **Step 3: Add and use the documented MinerU SDK dependency.**

Add the SDK package selected from the current MinerU SDK documentation (`mineru-open-sdk`) to `requirements.txt` with a compatible version constraint. Import it lazily inside the adapter so heavy users do not fail during module import when lite is unused. Normalize the SDK result through a small internal protocol that can obtain Markdown text and associated resources, then write `source.md` and resource files under the project directory. Reject missing or empty Markdown and remove partial resources on write failure.

Implement Pandoc execution with `subprocess.run(..., check=True, capture_output=True, text=True)`. Use `pandoc <markdown> -o <pdf> --pdf-engine=xelatex`; add a CJK-capable geometry/font configuration only through explicit arguments/configuration rather than hard-coded platform-specific paths. Log stdout/stderr through the existing project log callback at the orchestration layer. Require an existing, nonempty PDF after the process returns.

- [x] **Step 4: Run adapter tests and verify success.**

Run: `conda run -n latextrans python -m unittest tests.test_lite_adapters`

Expected: PASS.

- [x] **Step 5: Commit the external-tool adapters.**

Implementation note: Added lazy MinerU SDK and Pandoc/XeLaTeX adapters with injected test doubles and artifact cleanup.

```bash
git add src/engines/lite_mineru.py src/engines/lite_pdf.py requirements.txt tests/test_lite_adapters.py
git commit -m "feat(lite): add MinerU and Pandoc adapters"
```

---

## Task 5: Add Markdown Terminology and Translation Agents

**Files:**
- Create: `src/agents/tool_agents/markdown_terminology_agent.py`
- Create: `src/agents/tool_agents/markdown_translator_agent.py`
- Modify: `src/agents/tool_agents/terminology_agent.py` only for shared helper extraction if needed; do not change heavy behavior.
- Test: `tests/test_markdown_terminology_agent.py`
- Test: `tests/test_markdown_translator_agent.py`

**Interfaces:**

- Produce `MarkdownTerminologyAgent(config: dict[str, Any], markdown_path: Path, output_dir: Path)` with `execute() -> dict[str, Any]` returning `project_terms_path` and `project_terms_decisions_path`.
- Produce `MarkdownTranslatorAgent(config: dict[str, Any], source_markdown: Path, output_dir: Path, blocks: Sequence[MarkdownBlock])` with `async execute() -> Path`.
- The translator must expose an injectable async `request_translation(text: str, glossary: dict[str, str], block_index: int) -> str` callback for tests.

- [x] **Step 1: Write failing terminology tests.**

```python
class MarkdownTerminologyTests(unittest.TestCase):
    @patch("src.agents.tool_agents.markdown_terminology_agent.requests.post")
    def test_execute_generates_project_terms_from_markdown(self, post):
        post.return_value = fake_terminology_response(
            [{"source_term": "neural representation", "accepted": True, "selected_translation": "神经表示"}]
        )
        result = MarkdownTerminologyAgent(config, Path("source.md"), output_dir).execute()
        self.assertTrue(Path(result["project_terms_path"]).is_file())
        self.assertEqual(read_terms(output_dir / "project_terms.csv")["neural representation"], "神经表示")
```

- [x] **Step 2: Run terminology tests and verify failure.**

Run: `conda run -n latextrans python -m unittest tests.test_markdown_terminology_agent`

Expected: FAIL because the Markdown terminology agent does not exist.

- [x] **Step 3: Implement Markdown terminology collection.**

Reuse the existing terminology candidate filtering, batching, language labels, merge precedence, CSV format, and decision JSON schema. Replace LaTeX map collection with Markdown text collection. Include source Markdown context around candidates and document-level title/abstract context when present. If the source language is not English, preserve the existing multilingual behavior rather than forcing English-only candidate rules. If the candidate list is empty, write a valid empty CSV and decision JSON and return success. Any LLM request failure raises and lets the lite workflow mark the project failed; `review_before_translate` is ignored for lite.

- [x] **Step 4: Write failing translator tests for concurrency, ordering, glossary, and failure.**

```python
class MarkdownTranslatorTests(unittest.IsolatedAsyncioTestCase):
    async def test_blocks_translate_concurrently_but_rebuild_in_original_order(self):
        calls = []
        async def request(text, glossary, block_index):
            calls.append(block_index)
            await asyncio.sleep(0.01 * (3 - block_index))
            return text.replace("body", "译文")
        output = await MarkdownTranslatorAgent(
            config, source_path, output_dir, split_markdown(source_text), request_translation=request
        ).execute()
        self.assertEqual(Path(output).read_text(encoding="utf-8"), "## A\n译文A\n## B\n译文B")

    async def test_failed_block_raises_and_does_not_claim_success(self):
        async def request(text, glossary, block_index):
            raise RuntimeError("provider failed")
        with self.assertRaises(RuntimeError):
            await MarkdownTranslatorAgent(
                config, source_path, output_dir, split_markdown(source_text), request_translation=request
            ).execute()
```

- [x] **Step 5: Run translator tests and verify failure.**

Run: `conda run -n latextrans python -m unittest tests.test_markdown_translator_agent`

Expected: FAIL because the translator agent does not exist.

- [x] **Step 6: Implement asynchronous block translation.**

Load `project_terms.csv` with the existing terminology loader. Protect each block before calling the LLM, include the glossary in the system prompt when nonempty, and restore protected tokens after the response. Use an `asyncio.Semaphore` from lite configuration or a default of 10. Gather all block tasks with their original indices, sort by index, and write `translated.md` atomically only after every block succeeds. Keep the pre-heading block translatable unless it consists only of protected/non-text content. Do not retry at the workflow level; the request helper may use the existing bounded provider retry behavior, but final failure must raise.

- [x] **Step 7: Run both focused agent test modules and verify success.**

Run: `conda run -n latextrans python -m unittest tests.test_markdown_terminology_agent tests.test_markdown_translator_agent`

Expected: PASS.

- [x] **Step 8: Commit the Markdown agents.**

Implementation note: Added Markdown terminology generation and concurrent protected block translation with glossary and multilingual regression coverage.

```bash
git add src/agents/tool_agents/markdown_terminology_agent.py src/agents/tool_agents/markdown_translator_agent.py tests/test_markdown_terminology_agent.py tests/test_markdown_translator_agent.py
git commit -m "feat(lite): translate markdown with project terminology"
```

---

## Task 6: Implement Lite Engine Orchestration and Runtime Dispatch

**Files:**
- Create: `src/engines/lite.py`
- Create: `src/engines/heavy.py`
- Modify: `src/runtime.py`
- Modify: `src/agents/coordinator_agent.py` only if the heavy adapter needs a narrow existing-workflow wrapper.
- Test: `tests/test_lite_engine.py`
- Test: `tests/test_runtime_project_results.py`
- Test: `tests/test_tui_runner.py`

**Interfaces:**

- Produce `class LiteEngine` with `run(input_item: str, config: dict[str, Any], output_root: Path, log_callback: Callable[[dict[str, Any]], None] | None = None) -> dict[str, Any]`.
- Produce `class HeavyEngine` with the same result contract for one prepared heavy project.
- Produce `run_engine_task(engine: str, input_type: str, items: list[str], config: dict[str, Any], event_callback: ProjectEventCallback) -> dict[str, Any]` in `src/runtime.py`.
- Lite result fields: `ok`, `engine`, `project_name`, `project_dir`, `output_dir`, `source_markdown_path`, `translated_markdown_path`, `pdf_path`, `project_terms_path`, `project_terms_decisions_path`, `error`; no `errors_report_path` and no validation report.

- [x] **Step 1: Write failing end-to-end-lite tests with injected fakes.**

```python
class LiteEngineTests(unittest.TestCase):
    def test_run_creates_all_artifacts_in_one_project_directory(self):
        engine = LiteEngine(
            mineru=FakeMineru(),
            terminology=FakeTerminology(),
            translator=FakeTranslator(),
            pdf_generator=FakePdfGenerator(),
        )
        result = engine.run("paper.pdf", config, Path(self.tempdir))
        self.assertTrue(result["ok"])
        project_dir = Path(result["output_dir"])
        self.assertTrue((project_dir / "source.pdf").is_file())
        self.assertTrue((project_dir / "source.md").is_file())
        self.assertTrue((project_dir / "translated.md").is_file())
        self.assertTrue((project_dir / "translated.pdf").is_file())
        self.assertFalse((project_dir / "errors_report.json").exists())

    def test_markdown_or_pdf_failure_returns_failed_result(self):
        engine = LiteEngine(mineru=FakeMineru(), terminology=FakeTerminology(), translator=FailingTranslator(), pdf_generator=FakePdfGenerator())
        result = engine.run("paper.pdf", config, Path(self.tempdir))
        self.assertFalse(result["ok"])
        self.assertIn("error", result)
```

- [x] **Step 2: Run engine tests and verify failure.**

Run: `conda run -n latextrans python -m unittest tests.test_lite_engine`

Expected: FAIL because the engine classes and runtime dispatch do not exist.

- [x] **Step 3: Implement the workflow and preserve heavy behavior.**

`LiteEngine.run` must create or receive a prepared timestamped project directory, call the MinerU adapter, write `source.md`, invoke Markdown terminology generation without review pause, split and translate Markdown, and call Pandoc. Emit milestone logs for input preparation, MinerU, terminology, translation, and PDF generation through the existing project log callback. Catch each expected external/workflow exception, log it at error level, and return a failed result with paths to any artifacts already produced.

`HeavyEngine` must wrap the existing `CoordinatorAgent` calls without changing heavy validation/retry behavior. Runtime dispatch selects the engine from the effective config and passes a project-specific config generated by `engine_config`. Keep `run_projects` compatible for heavy callers and add an engine-aware path for TUI tasks. Emit `engine`, Markdown path fields, and lite output paths in `project_start`, `project_complete`, and `project_error` events. Do not emit a fake validation result for lite.

- [x] **Step 4: Run focused engine/runtime tests and verify success.**

Run: `conda run -n latextrans python -m unittest tests.test_lite_engine tests.test_runtime_project_results tests.test_tui_runner`

Expected: PASS, with existing heavy runtime tests remaining green.

- [x] **Step 5: Commit the engine dispatch.**

Implementation note: Added heavy/lite engine adapters, Lite PDF-to-Markdown workflow orchestration, engine-aware runtime events, and recoverable input-preparation failure paths.

```bash
git add src/engines/lite.py src/engines/heavy.py src/runtime.py src/agents/coordinator_agent.py tests/test_lite_engine.py tests/test_runtime_project_results.py tests/test_tui_runner.py
git commit -m "feat(runtime): dispatch heavy and lite translation engines"
```

---

## Task 7: Add Engine-Aware TUI Runner, Process State, and History

**Files:**
- Modify: `src/tui/runner.py`
- Modify: `src/tui/process_runner.py`
- Modify: `src/tui/state.py`
- Modify: `src/tui/history.py`
- Test: `tests/test_tui_state.py`
- Test: `tests/test_tui_history.py`
- Test: `tests/test_tui_process_runner.py`
- Test: `tests/test_tui_runner.py`

**Interfaces:**

- Extend `TaskViewState` with `engine: str` and preserve backward-compatible construction by defaulting to the effective heavy mode only at the caller boundary.
- Extend `ProjectViewState` with `engine`, `source_markdown_path`, and `translated_markdown_path`.
- Extend `run_tui_task(..., engine: str, ...)` and `_process_entry(..., engine: str, ...)` while preserving a compatibility default for existing test callers.
- Extend `load_output_history(output_root: Path, engine: str = "heavy") -> list[TaskViewState]`.
- Extend `write_project_metadata(..., engine: str = "heavy", source_markdown_path: str | None = None, translated_markdown_path: str | None = None)`.

- [x] **Step 1: Write failing state/history tests.**

```python
class TuiStateEngineTests(unittest.TestCase):
    def test_lite_event_copies_markdown_paths_and_engine(self):
        task = TaskViewState(input_type="pdf", inputs=["paper.pdf"], engine="lite")
        task.apply_event({
            "type": "project_complete", "engine": "lite", "project_name": "paper_1",
            "source_markdown_path": "/tmp/source.md", "translated_markdown_path": "/tmp/translated.md",
        })
        project = task.projects[0]
        self.assertEqual(project.engine, "lite")
        self.assertEqual(project.source_markdown_path, "/tmp/source.md")

class TuiHistoryEngineTests(unittest.TestCase):
    def test_history_reads_lite_artifacts_without_creating_error_state(self):
        write_lite_metadata_and_files(output_root)
        tasks = load_output_history(output_root, engine="lite")
        self.assertEqual(tasks[0].projects[0].engine, "lite")
        self.assertIsNone(tasks[0].projects[0].errors_report_path)
```

- [x] **Step 2: Run focused TUI state/history tests and verify failure.**

Run: `conda run -n latextrans python -m unittest tests.test_tui_state tests.test_tui_history tests.test_tui_process_runner tests.test_tui_runner`

Expected: FAIL because engine and Markdown fields are not propagated.

- [x] **Step 3: Implement state, metadata, history, and process propagation.**

Copy `engine`, `source_markdown_path`, and `translated_markdown_path` from events into project state. Persist `schema_version=2`, engine, input metadata, and Markdown paths. For legacy directories, infer heavy from the old artifact set; for lite, recognize `source.md`/`translated.md` and do not infer errors from the absence of `errors_report.json`. History scanning must use the caller-provided engine and its output root.

Pass engine from the task object through `run_tui_task`, spawned process arguments, and runtime overrides. A task created in one mode must continue using that mode even if the UI slider later changes. Keep process termination behavior unchanged.

- [x] **Step 4: Run focused tests and verify success.**

Run: `conda run -n latextrans python -m unittest tests.test_tui_state tests.test_tui_history tests.test_tui_process_runner tests.test_tui_runner`

Expected: PASS.

- [x] **Step 5: Commit state and runner integration.**

Implementation note: Added engine-specific TUI task state, process propagation, schema-v2 history metadata, engine filtering, and runtime error-event coverage.

```bash
git add src/tui/runner.py src/tui/process_runner.py src/tui/state.py src/tui/history.py tests/test_tui_state.py tests/test_tui_history.py tests/test_tui_process_runner.py tests/test_tui_runner.py
git commit -m "feat(tui): persist engine-specific task state"
```

---

## Task 8: Adapt the TUI Entry Page, Mode Switch, Settings, Filtering, and Detail Views

**Files:**
- Modify: `src/tui/app.py`
- Modify: `src/tui/input_parser.py`
- Test: `tests/test_tui_input_parser.py`
- Test: `tests/test_tui_app.py`

**Interfaces:**

- Change `run(argv: Sequence[str] | None = None) -> None` to parse `--engine/-e` and instantiate `LaTeXTransTuiApp(initial_engine=...)`.
- Add `LaTeXTransTuiApp.effective_engine: str` and `LaTeXTransTuiApp.set_engine(engine: str, persist: bool = False) -> None`.
- Add `validate_lite_input(value: str) -> list[str]` and keep existing heavy validation behavior unchanged.
- Add `config_fields_for_engine` usage to compose/populate/collect the settings form.

- [x] **Step 1: Write failing tests for entry parsing, startup precedence, and mode changes.**

```python
class LiteInputParserTests(unittest.TestCase):
    def test_lite_rejects_batch_text(self):
        self.assertTrue(validate_lite_input("a.pdf,b.pdf"))
        self.assertTrue(validate_lite_input("a.pdf\nb.pdf"))
        self.assertEqual(validate_lite_input("a.pdf"), [])

class TuiEngineModeTests(unittest.IsolatedAsyncioTestCase):
    async def test_lite_compose_hides_tex_and_errors_and_shows_markdown_tabs(self):
        app = LaTeXTransTuiApp(load_history_on_mount=False, initial_engine="lite")
        async with app.run_test() as pilot:
            self.assertFalse(app.query_one("#tex-tab").display)
            self.assertFalse(app.query_one("#errors-tab").display)
            self.assertTrue(app.query_one("#source-markdown-tab").display)
            self.assertTrue(app.query_one("#translated-markdown-tab").display)

    async def test_mode_switch_changes_title_palette_without_persisting_config(self):
        app = LaTeXTransTuiApp(load_history_on_mount=False, initial_engine="heavy")
        with patch("src.tui.app.save_ui_config") as save:
            async with app.run_test() as pilot:
                app.set_engine("lite")
                self.assertEqual(app.effective_engine, "lite")
                save.assert_not_called()
```

- [x] **Step 2: Run TUI tests and verify failure.**

Run: `conda run -n latextrans python -m unittest tests.test_tui_input_parser tests.test_tui_app`

Expected: FAIL because the TUI has no engine argument, mode switch, or dynamic detail layout.

- [x] **Step 3: Implement startup parsing and session engine state.**

Parse `--engine/-e` with `argparse`; if absent, load `ui.toml.engine`, otherwise default to heavy. Keep `ui.toml` unchanged for command-line overrides. Add a `Switch` below the entry action row and a label to its right. Use heavy as the switch-off state and lite as the switch-on state. Switch events call `set_engine` without persistence.

When switching engines, update the title palette from the existing white-blue colors to white-light-gray for lite, refresh the input controls, reload the current engine history root, filter task/project tables, clear an incompatible selected project, refresh settings fields, and update detail tabs. Do not cancel or alter task processes; each task retains its creation engine.

- [x] **Step 4: Implement dynamic input and settings forms.**

Heavy keeps the current three input types and batch input. Lite displays one unified input option and rejects newline/comma batch input before task creation. New lite tasks use `input_type="pdf"`, one input item, and the current engine.

Compose the settings form from `grouped_config_fields(self.effective_engine)`. Always show editable `engine`; show heavy-only `tex_sources_dir`, `paper_list`, `retranslate_with_terms`, and `heavy.validation.*` only in heavy mode; show only `lite.output_dir` for lite-specific fields. Saving form changes updates `ui.toml`, including engine, but does not call `set_engine` automatically.

- [x] **Step 5: Implement engine-specific detail views and project filtering.**

Add read-only scrollable `source-markdown-tab` and `translated-markdown-tab` using Rich `Syntax(..., "markdown", ...)`. Keep the existing TeX preview and errors table widgets in the DOM if needed for stable Textual composition, but set their tab/display state according to the current engine. Lite detail tabs are source Markdown, translated Markdown, terms, log, and Zotero; heavy detail tabs remain TeX, terms, errors, log, and Zotero.

Update project iteration, history root selection, selection clearing, retry input handling, and metadata writes to respect task engine. Lite project deletion removes only its own output directory. Lite retry starts a complete new PDF workflow with a fresh timestamped project directory.

- [x] **Step 6: Run TUI tests and verify success.**

Run: `conda run -n latextrans python -m unittest tests.test_tui_input_parser tests.test_tui_app`

Expected: PASS. Also run existing tests that exercise configuration widgets with mocked `save_ui_config` for the full `run_test()` lifecycle.

- [x] **Step 7: Commit the main TUI adaptation.**

Implementation note: Added session-only engine switching, startup precedence, engine-specific entry/forms/details, Markdown previews, engine filtering, and initialization-event persistence protection.

```bash
git add src/tui/app.py src/tui/input_parser.py tests/test_tui_input_parser.py tests/test_tui_app.py
git commit -m "feat(tui): add heavy and lite session modes"
```

---

## Task 9: Add Zotero Markdown Note Import

**Files:**
- Modify: `src/tui/zotero_adapter.py`
- Modify: `src/tui/app.py`
- Test: `tests/test_tui_zotero_adapter.py`
- Test: `tests/test_tui_app.py`

**Interfaces:**

- Produce `ZoteroAdapter.create_note(item_key: str, title: str, note: str, library_id: str, library_type: str) -> dict[str, Any]`.
- Add a lite-only app action `import_selected_project_markdown_to_zotero()`.
- Keep `attach_pdf` unchanged for heavy and lite PDF import.

- [x] **Step 1: Write failing adapter and UI tests.**

```python
class ZoteroNoteTests(unittest.TestCase):
    def test_create_note_posts_child_note_payload(self):
        adapter = ZoteroAdapter(api_key="key", session=fake_session)
        result = adapter.create_note("PARENT", "paper translated", "# 内容", "0", "user")
        request = fake_session.last_request
        self.assertEqual(result["item_key"], "NOTE1")
        self.assertEqual(request["json"][0]["itemType"], "note")
        self.assertEqual(request["json"][0]["parentItem"], "PARENT")
        self.assertEqual(request["json"][0]["note"], "# 内容")

class ZoteroModeTests(unittest.IsolatedAsyncioTestCase):
    async def test_lite_shows_two_import_buttons_and_heavy_shows_one(self):
        lite = LaTeXTransTuiApp(load_history_on_mount=False, initial_engine="lite")
        heavy = LaTeXTransTuiApp(load_history_on_mount=False, initial_engine="heavy")
        async with lite.run_test():
            self.assertTrue(lite.query_one("#import-zotero-markdown-button").display)
        async with heavy.run_test():
            self.assertFalse(heavy.query_one("#import-zotero-markdown-button").display)
```

- [x] **Step 2: Run Zotero tests and verify failure.**

Run: `conda run -n latextrans python -m unittest tests.test_tui_zotero_adapter tests.test_tui_app`

Expected: FAIL because note creation and the lite button do not exist.

- [x] **Step 3: Implement child-note creation and lite UI behavior.**

Create a Zotero child item with `itemType="note"`, `parentItem`, title/content fields in the format accepted by the existing Web API version, tags/relations defaults, and the same library prefix and authorization headers used by attachments. Return the created item key and surface API failures.

In lite mode show separate `导入 PDF` and `导入 Markdown` buttons. The Markdown action reads the selected project's `translated.md`, then creates one child note per selected Zotero item using the project/Markdown filename as title and the complete Markdown text as note content. Do not expose the Markdown button in heavy mode. Reuse existing selection, API-key, and status handling.

- [x] **Step 4: Run Zotero tests and verify success.**

Run: `conda run -n latextrans python -m unittest tests.test_tui_zotero_adapter tests.test_tui_app`

Expected: PASS. Verify tests mock configuration saving and do not modify `config/ui.toml`.

- [x] **Step 5: Commit Zotero note support.**

Implementation note: Added Zotero child-note creation and Lite Markdown import actions with per-item failure handling while preserving Heavy PDF attachment behavior.

```bash
git add src/tui/zotero_adapter.py src/tui/app.py tests/test_tui_zotero_adapter.py tests/test_tui_app.py
git commit -m "feat(zotero): import lite markdown as child notes"
```

---

## Task 10: Update Launchers, Documentation, and Full Regression Coverage

**Files:**
- Modify: `scripts/windows/latextrans-tui.cmd` only if argument forwarding needs adjustment.
- Modify: `scripts/linux/latextrans-tui` only if argument forwarding needs adjustment.
- Modify: `README.md`
- Modify: `README_ZH.md`
- Modify: `tests/test_launchers.py`
- Create or modify: `tests/test_lite_integration.py`

**Interfaces:**

- Document `latextrans-tui --engine heavy`, `latextrans-tui -e lite`, and the persisted `engine` setting.
- Document the lite input types, one-input-per-task restriction, output layout, MinerU SDK requirement, and Pandoc/XeLaTeX requirement.
- Do not document a lite `main.py` CLI mode or `--retranslate-with-terms` support.

- [x] **Step 1: Write failing launcher/integration assertions for the public workflow.**

```python
class LiteIntegrationTests(unittest.TestCase):
    def test_lite_event_contract_contains_markdown_paths_and_no_validation_report(self):
        events = run_fake_lite_task()
        complete = next(event for event in events if event["type"] == "project_complete")
        self.assertEqual(complete["engine"], "lite")
        self.assertIn("source_markdown_path", complete)
        self.assertIn("translated_markdown_path", complete)
        self.assertNotIn("errors_report_path", complete)
```

- [x] **Step 2: Run the focused integration tests and verify failure.**

Run: `conda run -n latextrans python -m unittest tests.test_lite_integration tests.test_launchers`

Expected: FAIL until the final event contract and documented launcher behavior are covered.

- [x] **Step 3: Update scripts and documentation.**

Keep the current Windows `%*` and Linux `"$@"` forwarding. Add explicit launcher tests that assert arguments are preserved. Update both READMEs with the new configuration sections and example commands, and describe that the entry-page switch is session-only while the settings-page engine value is persisted for the next startup.

- [x] **Step 4: Run the complete test suite in the required environment.**

Run: `conda run -n latextrans python -m unittest discover tests`

Expected: PASS. If an existing test fails because it assumes the legacy flat config, update that test to assert the documented migration behavior rather than restoring the legacy implementation.

- [x] **Step 5: Inspect the final diff and generated-file hygiene.**

Run:

```bash
git diff --check
git status --short
git diff --stat
```

Expected: only task-related source, tests, configuration, scripts, and documentation changes; no generated PDFs, downloaded archives, cache directories, API keys, or unrelated `config/ui.toml` mutation.

- [x] **Step 6: Commit final documentation and regression coverage.**

Implementation note: Documented Heavy/Lite TUI modes and event differences, verified launcher forwarding and Lite completion metadata, and completed the 494-test regression suite.

```bash
git add scripts README.md README_ZH.md tests/test_launchers.py tests/test_lite_integration.py
git commit -m "docs: document lite engine and tui modes"
```

---

## Verification Checklist

Before declaring implementation complete, verify all of the following with test evidence:

- `--engine/-e` accepts only heavy/lite and has the documented precedence.
- Startup overrides and the mode slider do not persist to `ui.toml`.
- The settings-page engine field persists as the next-startup default.
- Heavy and lite use separate output roots and history filters.
- Lite accepts arXiv ID/URL, PDF URL, and local PDF, one input per task.
- Lite output directories use stable names plus timestamp suffixes.
- MinerU is invoked through the Python SDK and saves Markdown plus resources.
- Markdown splits at non-fenced `##` headings and preserves block order.
- Protected Markdown structures survive translation.
- Terminology is generated from Markdown and applied to parallel block translation.
- Lite produces `source.md`, `translated.md`, `project_terms.csv`, decisions JSON, and `translated.pdf` in one directory.
- Lite failures emit logs and `project_error` without `errors_report.json` or validation retry.
- Heavy behavior and existing heavy tests remain intact.
- Lite TUI hides TeX/errors and shows source/translated Markdown previews.
- Heavy TUI hides lite-only fields and controls.
- Lite Zotero imports support both PDF attachment and Markdown child note.
- Full `unittest` discovery passes in the `latextrans` environment.
