<div align="center">

English | [中文](README_ZH.md)

<img src="./assets/logo.png" width="100%"></img>

**LaTeXTransPlus**

Translate LaTeX paper sources into multilingual PDF outputs while preserving document structure.

</div>

LaTeXTransPlus translates LaTeX source projects directly, then reconstructs and compiles the translated project. It provides a source-based Heavy workflow through `latextrans` and a Textual terminal UI with Heavy and PDF-to-Markdown Lite workflows through `latextrans-tui`.

## Install

Use Python 3.10 or newer. Install the package in the project environment:

```bash
pip install -e .
```

Install [MiKTeX](https://miktex.org/download) or [TeX Live](https://www.tug.org/texlive/) when PDF compilation is required. Lite additionally needs `pandoc`, XeLaTeX, and a MinerU API token.

## Quick Start

Translate an arXiv paper with the Heavy workflow:

```bash
latextrans --arxiv 2508.18791
```

Translate a local project or archive:

```bash
latextrans --project D:\path\to\paper_project
```

Open the terminal UI after the platform wrapper directory has been added to `PATH`:

```bash
latextrans-tui
```

### TUI Usage 

Before using the commands below, add the wrapper directory for your platform to `PATH`: `scripts/windows` on Windows, `scripts/linux` on Linux, or `scripts/macos` on macOS. The wrappers activate the `latextrans` Conda environment before launching the installed command. On Linux and macOS, make the scripts executable first with `chmod +x scripts/<platform>/latextrans scripts/<platform>/latextrans-tui`.

Choose the workflow when starting the UI:

```bash
latextrans-tui --engine heavy
latextrans-tui -e lite
```

Heavy accepts arXiv IDs or URLs, local LaTeX projects, source archives, and public source archive URLs. Lite accepts one arXiv ID, PDF URL, or local PDF path per task. Create separate tasks in the same TUI session for additional PDFs.

Results are written below `outputs/` for Heavy and `output-lite/` for Lite. The exact layout, configuration options, language codes, model setup, terminology review, validation, and more usage examples are documented in [Configuration and Usage](docs/configuration-and-usage.md).

## Highlights

- Preserves LaTeX commands, formulas, environments, captions, placeholders, and cross references where possible.
- Accepts arXiv IDs or URLs, local projects, archives, and public source archive URLs.
- Supports configurable source and target languages, project terminology, validation retries, and JSON Lines events.
- Provides separate Heavy and Lite workflows with per-project logs and generated artifacts.

## Acknowledgments

LaTeXTransPlus is based on the [LaTeXTrans](https://github.com/NiuTrans/LaTeXTrans) project.
