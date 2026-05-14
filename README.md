<div align="center">

English | [中文](README_ZH.md)

<img src="./logo.png" width="100%"></img>

  **LaTeXTransPlus**

  **Translate LaTeX paper sources into multilingual PDF outputs while preserving document structure.**

</div>

<div align="center">
<p dir="auto">

• [Introduction](#-introduction)
• [Features](#-features)
• [Installation](#-installation)
• [Configuration](#-configuration)
• [Usage](#-usage)
• [Outputs](#-outputs)
• [Translation Examples](#-translation-examples)
• [Acknowledgments](#-acknowledgments)

</p>
</div>

# 📖 Introduction

LaTeXTransPlus is a LaTeX paper translation tool developed based on the original LaTeXTrans project. It translates LaTeX source projects directly instead of translating rendered PDFs, then reconstructs and compiles the translated LaTeX project into a PDF.

The current implementation coordinates a parser, terminology generator, translator, validator, and PDF generator. It supports arXiv source downloads, local LaTeX projects, compressed source archives, project-level terminology extraction, configurable source and target languages, validation-driven retranslation, and per-project workflow logs.

# ✨ Features

- Preserves LaTeX structure, commands, placeholders, formulas, captions, environments, and cross references as much as possible during translation.
- Downloads and extracts arXiv TeX sources from arXiv IDs, including versioned IDs such as `2508.18791v2`.
- Processes local extracted projects and `.zip`, `.tar`, `.tar.gz`, or `.tgz` archives.
- Supports batch input from multiple arXiv IDs or multiple local projects.
- Uses project-level terminology files to improve term consistency.
- Can pause after terminology generation for manual review, then retranslate with the reviewed terms.
- Validates translated parts for LaTeX command mismatches, placeholder mismatches, and bracket mismatches.
- Retranslates retryable validation failures according to configurable retry policy.
- Adds language-aware LaTeX support for common CJK targets and chooses a suitable compilation engine order for the target language.
- Keeps mixed-script academic text more readable for Chinese, Japanese, Korean, and Arabic targets.
- Writes per-project logs and validation reports under `outputs/`.

# 🛠️ Installation

## 1. Clone Repository

```bash
git clone <this-repository-url>
cd LaTeXTrans
pip install -e .
```

The package currently installs the console command:

```bash
latextrans
```

## 2. Install a LaTeX Distribution

To generate PDF output, install [MiKTeX](https://miktex.org/download) or [TeX Live](https://www.tug.org/texlive/).

For MiKTeX, enable package installation on the fly. On Windows, Strawberry Perl may also be required by parts of the LaTeX toolchain.

LaTeXTransPlus compiles translated projects with `latexmk` and may use `pdflatex`, `xelatex`, or `lualatex` depending on the target language. Make sure the required engine and language packages are available in your TeX distribution. Chinese output uses `ctex` when needed, Japanese output uses `luatexja`, and Korean output uses `kotex`.

## Optional Conda Environment

```bash
conda create -n latextrans python=3.10 -y
conda activate latextrans
pip install -e .
```

# ⚙️ Configuration

The default configuration lives at:

```text
config/default.toml
```

Important top-level options:

```toml
sys_name = "LaTeXTrans"
version = "0.1.0"
source_language = "en"
target_language = "ch"
paper_list = []
tex_sources_dir = "tex source"
output_dir = "outputs"
update_term = "False"
mode = "plain"
user_term = ""
```

`source_language` and `target_language` accept short language codes used by the prompt layer, such as `en`, `ch`, `zh`, `ja`, `jp`, `de`, `fr`, `es`, `ko`, `ru`, `pt`, `it`, and `ar`. The default is English to Chinese.

For PDF generation, LaTeXTransPlus has built-in package and engine handling for Chinese (`ch`/`zh`/`cn`), Japanese (`ja`/`jp`), and Korean (`ko`) targets. Other target languages can still be translated, but successful PDF compilation depends on the original LaTeX project and the packages available in your TeX environment.

`mode` currently accepts:

- `plain`: translate with the available default, user, and project terms when applicable.
- `terms`: force glossary-oriented translation prompts.

## LLM Configuration

Configure the model endpoint under `[llm_config]`:

```toml
[llm_config]
model = "deepseek-v4-flash"
api_key_env = "DEEPSEEK_API_KEY"
base_url = "https://api.deepseek.com/chat/completions"
```

`api_key_env` names the environment variable that stores your API key. You can also override model settings from the CLI with `--model`, `--url`, and `--key`.

Example endpoints:

| Model | base_url |
|:-|:-|
| deepseek-chat / deepseek-v4-flash | `https://api.deepseek.com/chat/completions` |
| gpt-4o | `https://api.openai.com/v1/chat/completions` |
| gemini-2.5-pro | `https://generativelanguage.googleapis.com/v1beta/openai/chat/completions` |

## Terminology Configuration

```toml
[terminology]
enabled = true
review_before_translate = false
max_llm_candidates = 30
```

When enabled, LaTeXTransPlus scans parsed paper text, asks the LLM to select project terminology, and writes:

- `project_terms.csv`
- `project_terms_decisions.json`

If `review_before_translate = true`, the workflow stops after generating project terms. Review `project_terms.csv`, then rerun with `--retranslate-with-terms`.

You can also provide a custom CSV glossary with `user_term`. The expected CSV columns are:

```csv
Source Term,Target Translation
```

For English-to-Chinese translation, default terminology from `terms/` may also be merged.

## Validation Configuration

```toml
[validation.retry]
max_attempts = 3
generate_pdf_on_error = true
fail_on_error = true

[validation.issues.command_mismatch]
severity = "error"
retryable = true

[validation.issues.placeholder_mismatch]
severity = "error"
retryable = true

[validation.issues.bracket_mismatch]
severity = "error"
retryable = true
```

The validator checks command counts, placeholder preservation, and bracket balance. Retryable issues are sent back to the translator for targeted retranslation.

# 📚 Usage

## Translate by arXiv ID

```bash
latextrans --arxiv 2508.18791
```

Versioned arXiv IDs are supported:

```bash
latextrans --arxiv 2508.18791v2
```

You can also pass arXiv `abs`, `pdf`, or `e-print` URLs; LaTeXTransPlus extracts the ID automatically:

```bash
latextrans --arxiv https://arxiv.org/abs/2508.18791
```

## Batch Translate arXiv IDs

```bash
latextrans --arxiv 2508.18791v2,2407.01648
```

`--arxiv` also accepts space-separated shell arguments that contain comma-separated IDs.

## Translate a Local Project

Pass an extracted LaTeX project directory:

```bash
latextrans --project D:\path\to\paper_project_dir
```

Or pass a compressed source archive:

```bash
latextrans --project D:\path\to\paper_source.tar.gz
```

Supported archive formats are `.zip`, `.tar`, `.tar.gz`, and `.tgz`.

## Batch Translate Local Projects

```bash
latextrans --project D:\paper_a,D:\paper_b,D:\paper_c.zip
```

## Process Existing Sources

To process every project already under `tex_sources_dir`:

```bash
latextrans --all-existing
```

When `--arxiv` or `--project` is provided, LaTeXTransPlus processes only those explicit inputs and ignores other existing folders under `tex source`.

## Use a Custom Config or Override Paths

```bash
latextrans --config config/default.toml --source "tex source" --output outputs --arxiv 2508.18791
```

## Override Model Settings

```bash
latextrans --model deepseek-chat --url https://api.deepseek.com/chat/completions --key YOUR_API_KEY --arxiv 2508.18791
```

Prefer environment variables for real API keys instead of passing secrets directly on the command line.

## Review Terms Before Translation

Set this in your config:

```toml
[terminology]
enabled = true
review_before_translate = true
```

Run the workflow once:

```bash
latextrans --arxiv 2508.18791
```

Review the generated `project_terms.csv`, then run:

```bash
latextrans --arxiv 2508.18791 --retranslate-with-terms
```

# 📂 Outputs

Each project is written to:

```text
outputs/<target_language>_<project_name>/
```

Typical generated files include:

- `latextrans.log`: console log for the project.
- `sections_map.json`, `captions_map.json`, `envs_map.json`, `inputs_map.json`, `newcommands_map.json`: parsed and translated intermediate maps.
- `project_terms.csv`: generated or reviewed terminology.
- `project_terms_decisions.json`: terminology decision details.
- `initial_errors_report.json`: first validation result snapshot.
- `errors_report.json`: latest validation result after retries.
- `<project_name>/`: reconstructed translated LaTeX project.
- `<target_language>_<project_name>.pdf`: compiled translated PDF, when compilation succeeds.
- `build_pdflatex/`, `build_xelatex/`, or `build_lualatex/`: LaTeX build logs and intermediate compilation files.

If validation errors remain, PDF generation depends on `validation.retry.generate_pdf_on_error`. If `validation.retry.fail_on_error = true`, remaining validation errors cause the CLI to exit with failure status even if a PDF is generated.

If a compiler produces a PDF but its `.log` contains hard LaTeX errors, LaTeXTransPlus treats that compilation attempt as failed and tries the next configured engine when available. Check the build log directories for details when no final PDF is produced.

<!-- # 🖼️ Translation Examples

The following examples show original pages on the left and translated results on the right.

## Case 1: English to Chinese

<table>
  <tr>
    <td align="center"><b>Original</b></td>
    <td align="center"><b>Translation</b></td>
  </tr>
  <tr>
    <td><img src="examples/case1src.png" width="100%"></td>
    <td><img src="examples/case1ch.png" width="100%"></td>
  </tr>
</table>

## Case 2: English to Chinese

<table>
  <tr>
    <td align="center"><b>Original</b></td>
    <td align="center"><b>Translation</b></td>
  </tr>
  <tr>
    <td><img src="examples/case3src.png" width="100%"></td>
    <td><img src="examples/case3ch.png" width="100%"></td>
  </tr>
</table>

## Case 3: English to Japanese

<table>
  <tr>
    <td align="center"><b>Original</b></td>
    <td align="center"><b>Translation</b></td>
  </tr>
  <tr>
    <td><img src="examples/case-en.png" width="100%"></td>
    <td><img src="examples/case-jp.png" width="100%"></td>
  </tr>
</table>

## Case 4: English to Japanese

<table>
  <tr>
    <td align="center"><b>Original</b></td>
    <td align="center"><b>Translation</b></td>
  </tr>
  <tr>
    <td><img src="examples/case5a-1-en.png" width="100%"></td>
    <td><img src="examples/case5b-1-jp.png" width="100%"></td>
  </tr>
</table>

See [`examples/`](examples/) for more sample assets and translated PDFs. -->

# 🙏 Acknowledgments

LaTeXTransPlus is developed based on the [LaTeXTrans](https://github.com/NiuTrans/LaTeXTrans) project. We thank the [LaTeXTrans](https://github.com/NiuTrans/LaTeXTrans) project and its contributors for the original structured LaTeX translation workflow and implementation foundation.
