# Repository Guidelines

## Project Structure & Module Organization

LaTeXTrans is a Python package for translating LaTeX paper sources and generating translated PDFs. The CLI entry point lives in `main.py`, while reusable package code is under `src/`. Agent orchestration code is in `src/agents/`, LaTeX parsing/compilation helpers are in `src/formats/latex/`, and runtime/config helpers are in `src/runtime.py` and `src/config.py`. Default configuration lives in `config/default.toml`. Terminology CSVs are stored in `terms/`, examples and sample PDFs/images in `examples/`, evaluation scripts in `evaluation/scripts/`, and tests in `tests/`.

## Build, Test, and Development Commands

- Activate and use the local `latextrans` conda environment for all project runs and tests; do not run this project from any other environment.
- `pip install -e .`: install the package in editable mode with console scripts.
- `latextrans --arxiv 2508.18791`: run the translation workflow for an arXiv ID.
- `latextrans --project D:\path\to\paper_source.tar.gz`: process a local LaTeX project or archive.
- `python -m unittest discover tests`: run the current test suite.
- If a change is unrelated to TUI behavior, do not run TUI tests. For TUI-related changes, run only the newly added tests by default unless the user explicitly requests the full TUI test suite.

Install MiKTeX or TeXLive before testing PDF compilation paths.

## Coding Style & Naming Conventions

Use Python 3.10+ style with 4-space indentation, explicit imports, and `pathlib.Path` for filesystem paths where practical. Keep functions small and name helpers with clear snake_case verbs, such as `_safe_extract_tar` or `load_runtime_config`. Preserve existing public CLI option names and configuration keys. When editing configuration examples, keep TOML keys aligned with `config/default.toml`.

## Testing Guidelines

Tests currently use the standard `unittest` framework. Add tests under `tests/` with filenames like `test_runtime_config.py` and test classes ending in `Tests`. Prefer temporary directories and environment variable isolation for filesystem or configuration behavior. Run `python -m unittest discover tests` before submitting changes.

## Project Lessons

- This project has two configuration loading paths: both `main.py` and `src/runtime.py` load configuration. Changes to configuration semantics must extract shared helpers; otherwise, the CLI entry point and runtime helper can easily drift into inconsistent behavior.
- When removing legacy compatibility, clean it up thoroughly. Do not only update configuration examples or entry-point parameters; also inspect and remove leftover compatibility logic in low-level helpers, alias mappings, fallback branches, and old tests to keep documentation and runtime behavior from drifting again.
- Future development should not assume English-to-Chinese translation by default. Any work involving translation direction, prompts, glossaries, language configuration, or tests should be reviewed for multilingual support. If the user mentions only one case, such as "English-to-Chinese", pause first to note that it may affect multilingual capability and confirm whether the change should target only that language pair.
- New tool agents should log their `execute()` flow through `BaseToolAgent.log`, including start, key processing milestones, failure branches, and successful output paths, so workflow logs remain consistent across agents.
- The remote download helper must not only clean up on network exceptions; `OSError` during file open or write phases must also clean up partial archives, preventing subsequent `--all-existing` or extraction flows from mishandling corrupted packages.
- The skip semantics for batch input need regression tests covering "partial failure while continuing to process remaining items," not just a single failure causing a full abort.
- When adding new explicit input parameters, the `--all-existing` priority description, help text, and README must be updated in sync, so the documentation does not still reference only the old parameters.
- Textual `DataTable` columns with manually assigned fixed widths do not automatically redistribute when the terminal is resized. Any TUI table that computes fixed column widths from available space needs an explicit resize hook and a regression test that exercises terminal resizing.
- Never let tests mutate the real UI config. Any test that runs the TUI, Textual, the configuration page, settings controls, `save_ui_config(Path.cwd(), ...)`, or code that may trigger asynchronous configuration-widget `Changed` events must protect the real `config/ui.toml`. This is not cosmetic test pollution: repeated unexpected edits can overwrite the user's active paper list, target language, terminology settings, model settings, and other working preferences, creating serious disruption. Mock the configuration save function for the entire `run_test()` interaction lifecycle, including widget assignments, clicks, `pilot.pause()`, and queued Textual event draining, or run the test from a temporary cwd / project root. When verifying these tests, prefer comparing the real `config/ui.toml` hash or diff.

## Commit & Pull Request Guidelines

Recent commits use short messages such as `chore: ignore generated files` and `Update README`. Prefer concise, imperative messages; use a scoped conventional prefix when helpful, for example `fix(config): resolve API key from env`. Pull requests should describe the workflow affected, list verification commands, and note configuration changes.

## Security & Configuration Tips

Do not commit API keys. Store secrets in environment variables. Treat `outputs/`, `tex source/`, downloaded archives, and compiled PDFs as generated artifacts unless a fixture is intentionally added for tests or documentation.
