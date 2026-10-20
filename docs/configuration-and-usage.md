# 配置与使用说明

本文集中记录 LaTeXTransPlus 的详细配置和常用用法。README 只保留快速开始信息。

## 1. 安装环境

建议使用仓库约定的 `latextrans` Conda 环境：

```bash
conda create -n latextrans python=3.10 -y
conda activate latextrans
pip install -e .
```

生成 PDF 需要安装 MiKTeX 或 TeX Live，并确保 `latexmk`、`pdflatex`、`xelatex` 或 `lualatex` 可用。Lite 还需要 `pandoc`、XeLaTeX 和 `mineru-open-sdk`。

仓库提供 Windows、Linux 和 macOS 包装脚本，位于 `scripts/<platform>/`。直接使用 `latextrans` 和 `latextrans-tui` 前，必须先将对应目录加入 `PATH`：

- Windows：`scripts/windows`
- Linux：`scripts/linux`
- macOS：`scripts/macos`

这些包装脚本会先激活 `latextrans` Conda 环境，再调用已安装的命令。Linux/macOS 使用前执行：

```bash
chmod +x scripts/linux/latextrans scripts/linux/latextrans-tui
```

Windows 可在 PowerShell 中临时加入当前会话的 PATH：

```powershell
$env:Path = "${pwd}\scripts\windows;$env:Path"
```

Linux/macOS 可在当前 shell 中临时加入 PATH：

```bash
export PATH="$PWD/scripts/linux:$PATH"  # macOS 请将 linux 改为 macos
```

## 2. 配置文件

默认配置为 `config/default.toml`。常用配置如下：

```toml
source_language = "en"
target_language = "ch"
mode = "plain"
engine = "heavy"
user_term = ""

[llm_config]
profile = "deepseek"
reasoning_effort = ""

[terminology]
enabled = true
review_before_translate = false
max_llm_candidates = 30

[heavy]
tex_sources_dir = "tex source"
output_dir = "outputs"
retranslate_with_terms = false

[lite]
output_dir = "output-lite"
mineru_api_key_env = "MINERU_TOKEN"
translate_appendix = true
protected_token_retry_attempts = 2
cjk_mainfont_candidates = "SimSun, Noto Serif SC, FandolSong, Microsoft YaHei"
mainfont = ""
geometry = ""
```

`source_language` 和 `target_language` 支持 `en`、`ch`/`zh`、`ja`/`jp`、`de`、`fr`、`es`、`ko`、`ru`、`pt`、`it`、`ar` 等语言代码。`mode` 可设为 `plain` 或 `terms`。

### 模型配置

`[llm_config].profile` 指向 `config/provider/` 下的 provider 文件，例如：

```toml
# config/provider/deepseek.toml
model = "deepseek-chat"
api_key_env = "DEEPSEEK_API_KEY"
base_url = "https://api.deepseek.com/chat/completions"
custom_json = '{"enable_thinking": true}'
```

也可以通过命令行临时覆盖：

```bash
latextrans --model deepseek-chat \
  --url https://api.deepseek.com/chat/completions \
  --key YOUR_API_KEY --arxiv 2508.18791
```

实际 API key 建议放入环境变量，不要写入配置文件或命令历史。`custom_json` 只能追加供应商字段，不能覆盖 `model`、`messages`、`temperature`、`max_tokens` 等请求字段。

TUI 设置页在“LLM 配置 profile”下方提供“思考强度”下拉框，支持 `low`、`medium`、`high`、`xhigh`、`max`、`ultra`，保存到 `[llm_config].reasoning_effort`。默认“未设置”（空字符串或省略该配置项），不额外添加请求参数；若 profile 的 `custom_json` 已设置 `reasoning_effort`，则保留其原值。选择具体强度后，该值优先于 profile 中的同名参数，并作为 OpenAI-compatible 请求体的顶层字段发送，对 Heavy、Lite 翻译及术语提取统一生效。不按模型过滤选项，服务端是否接受该值取决于供应商和模型；遇到不支持的参数错误时，可切回“未设置”并检查 profile 的 `custom_json`。

### 术语与校验

启用项目术语并在翻译前人工审核：

```toml
[terminology]
enabled = true
review_before_translate = true
```

首次运行后检查输出目录中的 `project_terms.csv`，确认后重新翻译：

```bash
latextrans --arxiv 2508.18791 --retranslate-with-terms
```

自定义术语 CSV 使用以下列名：

```csv
Source Term,Target Translation
```

Heavy 默认会检查命令、占位符和括号。重试策略可在 `[heavy.validation.retry]` 中调整：

```toml
[heavy.validation.retry]
max_attempts = 3
generate_pdf_on_error = true
fail_on_error = true
```

## 3. Heavy 工作流

翻译 arXiv ID、版本号或 URL：

```bash
latextrans --arxiv 2508.18791
latextrans --arxiv 2508.18791v2
latextrans --arxiv https://arxiv.org/abs/2508.18791
```

批量翻译：

```bash
latextrans --arxiv 2508.18791v2,2407.01648
latextrans --project D:\paper_a,D:\paper_b,D:\paper_c.zip
```

处理本地项目、源码压缩包或公开源码 URL：

```bash
latextrans --project D:\path\to\paper_project
latextrans --project D:\path\to\paper_source.tar.gz
latextrans --project-url https://example.org/paper_source.tar.gz
```

处理 `tex_sources_dir` 中已有的所有项目：

```bash
latextrans --all-existing
```

自定义配置、路径和语言：

```bash
latextrans --config config/default.toml \
  --source "tex source" --output outputs \
  --source_language en --target_language ja \
  --arxiv 2508.18791
```

### JSON Lines 事件

Heavy CLI 可输出稳定的项目级事件：

```bash
latextrans --arxiv 2508.18791 --json-events stdout
latextrans --arxiv 2508.18791 --json-events-file outputs/events.jsonl
```

事件类型包括 `run_start`、`project_start`、`project_complete`、`project_error` 和 `run_complete`。

## 4. Lite 工作流与 TUI

启动 TUI 并选择引擎：

```bash
latextrans-tui
latextrans-tui --engine heavy
latextrans-tui -e lite
```

Heavy 接受 arXiv、本地 LaTeX 项目、压缩包和公开源码 URL。Lite 每个任务只接受一个 arXiv ID、PDF URL 或本地 PDF 路径；批量任务请在同一 TUI 会话中分别创建。

项目管理中，PDF 已生成但仍有未解决校验错误的项目显示为 `completed(nerrors)`，其中 `n` 是最终校验报告中 error 级别的条目数（同一条目中的多个问题合并计数），warning 不计入。该状态计入已完成项目，并保留错误记录供检查；历史项目加载时也采用此规则。未生成 PDF 的失败项目仍显示为 `failed`。此状态用于 TUI 展示，CLI 的严格校验退出规则仍由 `validation.retry.fail_on_error` 控制。

在 TUI 设置页的 Zotero 区域可选择 PDF 导入 API。默认使用 Web API，需要设置 `web_api_key_env` 指定的环境变量；选择本地 API 时会先检查 Zotero 本地服务是否支持写入，检查失败会保留原选项。首次导入时 Zotero 会请求本地写入授权；选择“始终允许”后，授权会保存在系统凭据存储中，后续导入无需再次确认。选择“一次允许”则每次写入都可能需要重新授权。搜索条目始终使用本地 API，Markdown 笔记导入仍使用 Web API。

Lite 的 MinerU token 从 `[lite].mineru_api_key_env` 指定的环境变量读取：

```powershell
$env:MINERU_TOKEN = "your-token"
```

中文、日文和韩文 PDF 需要可用的 CJK 字体。`cjk_mainfont_candidates` 按顺序探测字体；`mainfont` 用于正文拉丁/希腊字符。字体名称必须与 `fc-list` 输出一致。

## 5. 输出目录

Heavy 默认输出到：

```text
outputs/<target_language>_<project_name>/
```

常见文件包括 `latextrans.log`、`project_terms.csv`、`errors_report.json`、翻译后的 LaTeX 项目目录和最终 PDF。

Lite 默认输出到：

```text
output-lite/<stable_name>_YYMMDD/
├── source.pdf
├── source.md
├── translated.md
├── translated.pdf
├── project_terms.csv
└── latextrans.log
```

PDF 编译失败时，已生成的 Markdown 和日志仍会保留；请优先查看 `latextrans.log` 以及 LaTeX/Pandoc 构建输出。
