# Repository Guidelines

## Project Structure & Module Organization

LaTeXTrans is a Python package for translating LaTeX paper sources and generating translated PDFs. The CLI entry point lives in `main.py`, while reusable package code is under `src/`. Agent orchestration code is in `src/agents/`, LaTeX parsing/compilation helpers are in `src/formats/latex/`, and runtime/config helpers are in `src/runtime.py` and `src/config.py`. Default configuration lives in `config/default.toml`. Terminology CSVs are stored in `terms/`, examples and sample PDFs/images in `examples/`, evaluation scripts in `evaluation/scripts/`, and tests in `tests/`.

## Build, Test, and Development Commands

- `pip install -e .`: install the package in editable mode with console scripts.
- `latextrans --arxiv 2508.18791`: run the translation workflow for an arXiv ID.
- `latextrans --project D:\path\to\paper_source.tar.gz`: process a local LaTeX project or archive.
- `python -m unittest discover tests`: run the current test suite.

Install MiKTeX or TeXLive before testing PDF compilation paths.

## Coding Style & Naming Conventions

Use Python 3.10+ style with 4-space indentation, explicit imports, and `pathlib.Path` for filesystem paths where practical. Keep functions small and name helpers with clear snake_case verbs, such as `_safe_extract_tar` or `load_runtime_config`. Preserve existing public CLI option names and configuration keys. When editing configuration examples, keep TOML keys aligned with `config/default.toml`.

## Testing Guidelines

Tests currently use the standard `unittest` framework. Add tests under `tests/` with filenames like `test_runtime_config.py` and test classes ending in `Tests`. Prefer temporary directories and environment variable isolation for filesystem or configuration behavior. Run `python -m unittest discover tests` before submitting changes.

## Project Lessons

- 这个项目有两条配置加载路径，`main.py` 和 `src/runtime.py` 都会加载配置；类似配置语义变更必须抽出公共 helper，否则 CLI 入口和 runtime helper 很容易行为不一致。
- 去除旧版兼容时要彻底清理，不仅要改配置示例或入口参数，还要检查并删除底层 helper、别名映射、回退分支和旧测试中的残留兼容逻辑，避免文档与真实运行时语义再次漂移。
- 后续开发不要再默认局限于英译中；涉及翻译方向、prompt、术语表、语言配置或测试时，都要按多语言支持审视。若用户只提到一种情况（例如只说“英译中”），先停下来提醒用户这可能影响多语言能力，并确认是否要只针对该语言对处理。

## Commit & Pull Request Guidelines

Recent commits use short messages such as `chore: 忽略生成文件` and `Update README`. Prefer concise, imperative messages; use a scoped conventional prefix when helpful, for example `fix(config): resolve API key from env`. Pull requests should describe the workflow affected, list verification commands, and note configuration changes.

## Security & Configuration Tips

Do not commit API keys. Store secrets in environment variables. Treat `outputs/`, `tex source/`, downloaded archives, and compiled PDFs as generated artifacts unless a fixture is intentionally added for tests or documentation.
