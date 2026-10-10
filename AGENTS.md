# Repository Guidelines

## Project Structure & Module Organization

LaTeXTransPlus is a Python package that translates LaTeX paper sources and PDFs into translated PDF output. It is derived from the upstream LaTeXTrans project and ships two workflows: the source-based Heavy workflow orchestrated by `src/agents/`, and the PDF-to-Markdown Lite workflow in `src/engines/`. Heavy is available through the `latextrans` CLI and both workflows through the Textual terminal UI in `src/tui/`.

- `main.py` is the `latextrans` CLI entry point for Heavy; `latextrans-tui` resolves to `src/tui/app.py:run`.
- `src/agents/` holds Heavy agent orchestration (`coordinator_agent.py`, `tool_agents/`).
- `src/engines/` holds the engine interface (`base.py`, `EngineName`), `heavy.py`, and the Lite stages (`lite.py`, `lite_inputs.py`, `lite_mineru.py`, `lite_markdown.py`, `lite_math.py`, `lite_fonts.py`, `lite_pdf.py`).
- `src/tui/` holds the UI. `app.py` only coordinates project identity and task lifecycle; state, configuration page/schema, project detail, history, error reports, runner/process runner, widgets and Zotero helpers live in their own modules.
- `src/formats/latex/` holds LaTeX parsing, prompt, reconstruction and compilation helpers.
- Shared services live in `src/runtime.py` (workflow orchestration and runtime config loading), `src/config.py` (LLM profile and payload helpers), `src/project_sources.py` and `src/project_metadata.py` (input acquisition and titles), `src/terminology.py`, `src/validation_policy.py`, `src/events.py` (JSON Lines events) and `src/utils/progress.py`.
- `config/default.toml` is the working configuration and `config/template.toml` the tracked template next to it; `config/ui.toml` is created locally on first TUI run and git-ignored, and `config/provider/*.toml` holds LLM profiles (only `config/provider/default.toml` is tracked).
- `terms/` stores terminology CSVs and `examples/` sample inputs and PDFs/images.
- `scripts/windows`, `scripts/linux` and `scripts/macos` contain launcher wrappers that activate the `latextrans` conda environment.
- `docs/` holds usage and design documentation (`configuration-and-usage.md`, `superpowers/plans/`, `superpowers/specs/`), `evaluation/scripts/` holds evaluation scripts, and `tests/` holds the `unittest` suite.

## Build, Test, and Development Commands

- Activate and use the local `latextrans` conda environment for all project runs and tests; do not run this project from any other environment.
- `pip install -e .`: install the package in editable mode with the `latextrans` and `latextrans-tui` console scripts.
- `latextrans --arxiv 2508.18791`: run the Heavy workflow for an arXiv ID.
- `latextrans --project D:\path\to\paper_source.tar.gz`: process a local LaTeX project or archive.
- `latextrans-tui`, `latextrans-tui --engine heavy`, `latextrans-tui -e lite`: open the terminal UI and select a workflow. Add `scripts/windows`, `scripts/linux` or `scripts/macos` to `PATH` first; the wrappers activate the conda environment, and the Linux and macOS scripts need `chmod +x`.
- `python -m unittest discover tests`: run the current test suite.
- If a change is unrelated to TUI behavior, do not run TUI tests. For TUI-related changes, run only the newly added tests by default unless the user explicitly requests the full TUI test suite.

Install MiKTeX or TeXLive before testing PDF compilation paths. Lite additionally requires `pandoc`, XeLaTeX and a MinerU API token. Installation, configuration keys, language codes, model profiles and output layout are documented in `docs/configuration-and-usage.md`; keep that guide in sync with CLI and configuration changes.

## Coding Style & Naming Conventions

Use Python 3.10+ style with 4-space indentation, explicit imports, and `pathlib.Path` for filesystem paths where practical. Keep functions small and name helpers with clear snake_case verbs, such as `_safe_extract_tar` or `load_runtime_config`. Preserve existing public CLI option names and configuration keys. When editing configuration examples, keep TOML keys aligned with `config/default.toml`.

## Testing Guidelines

Tests currently use the standard `unittest` framework. Add tests under `tests/` with filenames like `test_runtime_config.py` and test classes ending in `Tests`. Prefer temporary directories and environment variable isolation for filesystem or configuration behavior. Run `python -m unittest discover tests` before submitting changes.

## Project Lessons

- This project has two configuration paths: runtime configuration (`config/default.toml` plus `config/provider/*.toml`, loaded through `src/runtime.py` and `src/config.py`) and TUI configuration (`config/ui.toml`, loaded through `src/tui/config.py`). Do not let `main.py` grow its own parsing; route changes through the shared runtime helpers, and keep the `src/tui/config_schema.py` form fields aligned with the TOML keys, otherwise the CLI, the runtime and the UI can easily drift into inconsistent behavior.
- When removing legacy compatibility, clean it up thoroughly. Do not only update configuration examples or entry-point parameters; also inspect and remove leftover compatibility logic in low-level helpers, alias mappings, fallback branches, and old tests to keep documentation and runtime behavior from drifting again.
- Future development should not assume English-to-Chinese translation by default. Any work involving translation direction, prompts, glossaries, language configuration, or tests should be reviewed for multilingual support. If the user mentions only one case, such as "English-to-Chinese", pause first to note that it may affect multilingual capability and confirm whether the change should target only that language pair.
- New tool agents should log their `execute()` flow through `BaseToolAgent.log`, including start, key processing milestones, failure branches, and successful output paths, so workflow logs remain consistent across agents.
- The remote download helper must not only clean up on network exceptions; `OSError` during file open or write phases must also clean up partial archives, preventing subsequent `--all-existing` or extraction flows from mishandling corrupted packages.
- The skip semantics for batch input need regression tests covering "partial failure while continuing to process remaining items," not just a single failure causing a full abort.
- When adding new explicit input parameters, the `--all-existing` priority description, help text, README and `docs/configuration-and-usage.md` must be updated in sync, so the documentation does not still reference only the old parameters.
- Textual `DataTable` columns with manually assigned fixed widths do not automatically redistribute when the terminal is resized. Any TUI table that computes fixed column widths from available space needs an explicit resize hook and a regression test that exercises terminal resizing.
- Never let tests mutate the real UI config. Any test that runs the TUI, Textual, the configuration page, settings controls, `save_ui_config(Path.cwd(), ...)`, or code that may trigger asynchronous configuration-widget `Changed` events must protect the real `config/ui.toml`. This is not cosmetic test pollution: repeated unexpected edits can overwrite the user's active paper list, target language, terminology settings, model settings, and other working preferences, creating serious disruption. Mock the configuration save function for the entire `run_test()` interaction lifecycle, including widget assignments, clicks, `pilot.pause()`, and queued Textual event draining, or run the test from a temporary cwd / project root. When verifying these tests, prefer comparing the real `config/ui.toml` hash or diff.
- Do not let a single module grow into a multi-purpose script. The TUI started as one large `src/tui/app.py` and had to be decomposed afterwards into focused components, so when a module starts mixing unrelated responsibilities, extract a new module next to it with one clear purpose instead of appending more code to the existing file.

## Commit & Pull Request Guidelines

Recent commits use short messages such as `chore: ignore generated files` and `Update README`. Prefer concise, imperative messages; use a scoped conventional prefix when helpful, for example `fix(config): resolve API key from env`. Pull requests should describe the workflow affected, list verification commands, and note configuration changes.

## Security & Configuration Tips

Do not commit API keys. Store secrets in environment variables. Treat `outputs/`, `output-lite/`, `tex source/`, downloaded archives, and compiled PDFs as generated artifacts unless a fixture is intentionally added for tests or documentation.
