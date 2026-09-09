# Lite 翻译引擎与 TUI 多引擎适配设计

## 1. 背景与目标

项目当前只有 heavy 翻译方式：直接处理 LaTeX 源码，生成翻译后的 LaTeX 项目并编译 PDF。本功能新增 lite 翻译引擎，用于处理 PDF 文档：先通过 MinerU Python SDK 将 PDF 解析为 Markdown，再生成项目术语表，按 Markdown 二级标题分块并行翻译，最后生成译后 Markdown 和 PDF。

TUI 需要同时支持 heavy 与 lite 两种引擎。TUI 启动时接受 `--engine`/`-e` 参数，参数只影响当前会话，不写回 `ui.toml`。入口页还提供当前会话内的模式滑块。两个引擎使用完全独立的输出目录，项目列表、配置表单、项目详情和 Zotero 操作根据当前引擎动态适配。

本次只让 TUI 使用 lite；不为 `main.py` 增加 lite CLI 参数，但后端引擎接口应保持可复用，方便未来接入独立 CLI。

## 2. 已确认的范围

### 2.1 lite 输入

lite 每个任务只接受一个输入，不支持批量指定；用户可以在同一个 TUI 会话中分次创建多个任务。输入形式包括：

- arXiv ID；
- arXiv URL，包括摘要页 URL 和 PDF URL；
- 普通 PDF 直链；
- 本地 PDF 文件路径。

入口页在 lite 模式下使用统一输入类型，不再显示 heavy 的三种输入类型。系统根据内容自动识别输入：arXiv ID 或 arXiv URL 转换为 arXiv PDF；其他 HTTP/HTTPS 地址作为 PDF 直链；非 URL 内容作为本地路径。多行、逗号分隔或多个输入项应在提交前直接拒绝。

### 2.2 lite 翻译规则

- MinerU 使用 Python SDK，不调用 MinerU CLI；
- Markdown 按二级标题 `##` 分块；
- 第一个 `##` 之前的内容作为前置块；
- `###` 及更深层标题属于所属的 `##` 块，不单独拆分；
- fenced code block 中的 `##` 不视为标题；
- 翻译结果按照原始块顺序重建；
- 图片路径和 URL 保留；图片 alt 文本可翻译；
- 代码块和内联代码完全保留；
- 数学公式保留；
- 表格结构和分隔符保留，表格文字可翻译；
- 链接 URL 保留，链接文本可翻译；
- 脚注正文可翻译，脚注引用和结构保留；
- front-matter 保留不动。

术语表自动生成后直接开始翻译，不执行 `review_before_translate` 暂停。lite 不支持 `--retranslate-with-terms`。

### 2.3 lite 失败语义

lite 不使用 `ValidatorAgent`，不生成 `errors_report.json`，不执行校验重试。以下情况均视为项目失败：输入获取失败、MinerU 解析失败、Markdown 无效或写入失败、术语生成失败、任一 Markdown 块翻译失败、译后 Markdown 写入失败、Pandoc/XeLaTeX 生成 PDF 失败或生成文件不存在。

项目失败时保留已经生成的中间产物，写入项目日志并发送 `project_error` 事件。术语候选为空不是失败，只要术语生成请求正常完成即可继续翻译。

## 3. 总体架构

新增引擎层，避免把 lite 逻辑继续堆入已经较大的 `runtime.py` 和 `src/tui/app.py`：

```text
src/engines/
├── base.py              # 引擎接口、统一结果和公共约定
├── heavy.py             # 现有 CoordinatorAgent 流程适配
├── lite.py              # PDF → Markdown → 翻译 → PDF
├── lite_inputs.py       # lite 输入识别、下载与项目命名
├── lite_markdown.py     # Markdown 分块、保护和重建
└── lite_pdf.py          # Pandoc + XeLaTeX PDF 生成
```

引擎接口至少需要覆盖：

- 输入准备；
- 单项目执行；
- 输出目录确定；
- 统一工作流结果；
- 项目日志和事件所需的字段。

heavy 引擎通过适配器调用现有 `CoordinatorAgent`，保持当前 heavy 行为。runtime 统一负责任务生命周期、项目事件、日志、完成/失败统计和 TUI 子进程终止；具体引擎负责文档格式相关处理。

## 4. Lite 工作流

### 4.1 输入准备

每个 lite 任务创建一个独立项目目录。稳定名称来源为：

- arXiv 输入：arXiv ID；
- PDF URL：URL 最后一个路径片段去掉 `.pdf`；
- 本地 PDF：文件名去掉 `.pdf`。

目录名使用稳定名称加时间戳后缀，避免同一稳定名称冲突，例如：

```text
output-lite/2508.18791_20260909T203000/
```

远程输入下载到该目录并保存为 `source.pdf`；本地 PDF 复制为 `source.pdf`，使任务产出目录自包含。非法路径、非 PDF 文件、下载失败或无法识别的输入立即产生项目失败事件。

### 4.2 MinerU 解析

通过独立的 MinerU SDK 适配器调用 Python SDK，把 `source.pdf` 解析为 Markdown，并保存 MinerU 产生的图片资源。SDK 的具体返回对象不应泄漏到其他模块，以便未来适配 SDK 版本变化。

产物至少包括：

```text
source.pdf
source.md
<图片资源目录或文件>
```

Markdown 中的图片引用必须与复制到项目目录中的资源保持可用的相对路径关系。

### 4.3 术语生成

复用现有术语生成的候选过滤、LLM 批处理、决策记录和 CSV 写入语义，但增加 Markdown 文本输入适配：从 `source.md` 收集普通文本和上下文，而不是读取 LaTeX map 文件。输出：

```text
project_terms.csv
project_terms_decisions.json
```

共享的源语言、目标语言、用户术语、LLM 配置和术语开关继续生效；lite 不执行术语审核暂停。

### 4.4 Markdown 分块与翻译

Markdown 分块器以状态机方式扫描全文，识别 fenced code block、front-matter 和普通文本状态。仅在非代码块状态中识别行首二级标题 `##`。每个块包含该二级标题以及直到下一个二级标题之前的内容；首个二级标题之前的内容作为前置块。

翻译器使用异步并发请求，按块并行调用 LLM，并用信号量限制并发数。所有块完成后按原始索引排序重建 `translated.md`，不因异步完成顺序改变文档结构。

翻译请求需要通过保护/恢复机制避免破坏 Markdown 结构。保护内容包括代码、公式、URL、表格分隔符、front-matter 和脚注结构；允许翻译标题、普通段落、链接文本、表格文字、图片 alt 和脚注正文。任一块请求最终失败，工作流立即失败并保留已产生的中间结果。

### 4.5 PDF 生成

使用已安装的 Pandoc，并通过 XeLaTeX 生成译后 PDF。输入为 `translated.md`，输出文件位于同一项目目录，例如：

```text
translated.md
translated.pdf
```

Pandoc 或 XeLaTeX 执行失败、输出文件缺失或为空时，项目标记为失败并记录日志。

### 4.6 Lite 产物

```text
output-lite/
└── <稳定名_时间戳>/
    ├── source.pdf
    ├── source.md
    ├── translated.md
    ├── translated.pdf
    ├── project_terms.csv
    ├── project_terms_decisions.json
    ├── latextrans.log
    ├── .latextrans-tui.json
    └── <MinerU 图片资源>
```

一个任务的全部产出均位于同一个项目目录内。

## 5. 配置模型

`ui.toml` 顶层保存当前默认引擎：

```toml
engine = "heavy"
```

共享配置保留在顶层或现有共享小节中：

```toml
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
```

heavy 专属配置放入 `[heavy]`，包括：

```toml
[heavy]
paper_list = []
tex_sources_dir = "tex source"
output_dir = "outputs"
retranslate_with_terms = false
```

heavy 的 `[validation]` 整段移动为 `[heavy.validation]`，因为 validation 是 heavy 专属。

lite 专属配置为：

```toml
[lite]
output_dir = "output-lite"
```

`config/default.toml`、`config/template.toml` 和示例配置需要同步更新。`load_ui_config()` 需要兼容旧版扁平配置：首次加载旧结构时，将旧的 `tex_sources_dir`、`output_dir`、`paper_list`、`retranslate_with_terms` 和 `[validation]` 迁移到 `[heavy]`，保留用户已有路径值，并补齐 `engine = "heavy"` 和 `[lite].output_dir = "output-lite"`。

配置页始终显示可编辑的 `engine` 下拉框。修改后保存为下次启动的默认值，但不强制切换当前会话；当前会话由启动参数和模式滑块控制。

## 6. TUI 设计

### 6.1 引擎选择优先级

有效引擎的优先级为：

```text
--engine/-e > ui.toml.engine > heavy
```

合法值只有 `heavy` 和 `lite`。启动参数不写回 `ui.toml`。`run()` 和启动脚本链路需要支持参数传递；Windows 与 Linux 脚本继续把参数转发给 TUI。

任务创建时记录当前会话引擎。切换模式不会取消已经运行的任务；运行中的任务继续按创建时的引擎完成。任务状态和历史可在内存中共存，但界面只显示当前引擎项目。

### 6.2 入口页

heavy 模式保留当前输入类型和批量能力：

- arXiv ID / URL；
- 本地项目/压缩包；
- 远程压缩包 URL。

lite 模式将输入类型显示为统一选项：

```text
PDF / arXiv ID / URL / 本地路径
```

输入框只接受一个条目，多行、逗号或批量内容在提交时提示错误。

输入框操作行的下一行增加一个左对齐模式滑块，右侧显示当前模式，例如 `当前模式：Heavy` 或 `当前模式：Lite`。滑块只影响当前会话，不保存到配置。

heavy 标题继续使用白到蓝渐变；lite 标题使用白到浅灰渐变。响应式艺术字和窄屏回退逻辑保持不变，只按当前引擎选择颜色样式。

### 6.3 项目列表与历史

heavy 扫描 `[heavy].output_dir`，默认 `outputs`；lite 扫描 `[lite].output_dir`，默认 `output-lite`。两个目录同层级、互不共享。

项目元数据增加引擎和 Markdown 路径字段，例如：

```json
{
  "schema_version": 2,
  "engine": "lite",
  "task_id": "20260909T203000.123",
  "input_type": "pdf",
  "input_item": "2508.18791",
  "project_name": "2508.18791_20260909T203000",
  "status": "completed",
  "source_markdown_path": ".../source.md",
  "translated_markdown_path": ".../translated.md",
  "updated_at": "2026-09-09T20:30:00"
}
```

旧版 heavy 元数据默认按 heavy 处理。加载历史时按当前引擎扫描对应根目录，并优先检查元数据中的 `engine` 字段。当前模式的左侧项目列表和项目管理表只显示当前引擎项目。

heavy 和 lite 均保留终止、删除和重新翻译操作。lite 重新翻译是完整重跑流程，并使用新的时间戳目录，不支持 `--retranslate-with-terms`。

### 6.4 详情页

heavy 详情页保持：

```text
TeX | 术语表 | 错误记录 | 日志 | Zotero
```

heavy 不显示 lite 相关 tab。

lite 详情页为：

```text
源 Markdown | 译后 Markdown | 术语表 | 日志 | Zotero
```

lite 不显示 TeX 和错误记录。两个 Markdown tab 使用与当前 TeX 预览类似的只读可滚动区域和 Rich `Syntax` Markdown 高亮，分别读取 `source.md` 和 `translated.md`。文件尚未生成或读取失败时显示清晰提示。

术语表和日志展示逻辑在两个引擎间复用。

### 6.5 Zotero

heavy 只显示现有的「导入 PDF」按钮，并将译文 PDF 作为选中 Zotero 条目的子附件。

lite 显示两个按钮：

- 导入 PDF：将 `translated.pdf` 作为选中条目的子附件；
- 导入 Markdown：为每个选中条目创建一个子笔记，标题使用项目名或译后 Markdown 文件名，正文写入完整 `translated.md` 内容，不上传 Markdown 文件附件。

Zotero adapter 增加独立的创建子笔记方法，与 PDF 上传逻辑分离。未选择项目、未选择条目、文件不存在、API key 缺失或 API 请求失败时显示操作状态。

## 7. 事件与状态模型

heavy 与 lite 使用统一事件协议：

```text
project_start
project_log
task_log
project_complete
project_error
project_cancelled
```

lite 项目事件增加：

```text
engine = "lite"
source_markdown_path
translated_markdown_path
pdf_path
project_terms_path
project_terms_decisions_path
```

lite 不产生 `errors_report_path`，`validation_summary` 为 `None` 或不提供。`ProjectViewState`、`TaskViewState` 增加 `engine`、源 Markdown 路径和译后 Markdown 路径字段。统一 runtime 仍负责事件转发、日志落盘、状态统计和 TUI 元数据写入。

## 8. 测试计划

### 配置与引擎

- `--engine/-e` 合法值和非法值；
- 命令行参数优先于 `ui.toml.engine`；
- 无参数、无配置时默认为 heavy；
- 启动参数不写回配置；
- 设置页修改 engine 会写回配置；
- 设置页修改默认 engine 不改变当前会话；
- 旧版扁平配置迁移；
- heavy/lite 字段分组和过滤；
- 两个引擎输出目录独立扫描。

### Lite 输入与目录

- arXiv ID、摘要页 URL、PDF URL；
- 普通 PDF 直链；
- 本地 PDF；
- 非 PDF 文件、缺失路径、下载失败；
- 多行和逗号批量输入被拒绝；
- 稳定项目名和时间戳后缀；
- 远程和本地 PDF 均生成项目内 `source.pdf`。

### Markdown 工作流

- 按 `##` 分块；
- 前置内容形成前置块；
- `###` 不拆分；
- fenced code block 中的 `##` 不误识别；
- 并发完成后仍按原始顺序重建；
- 代码、公式、URL、表格结构、front-matter 和脚注结构保持；
- 标题、段落、链接文本、表格文字、图片 alt 和脚注正文可翻译；
- 单块翻译失败导致项目失败；
- MinerU 无效结果、Markdown 写入失败和 Pandoc 失败均导致项目失败。

### 外部依赖

MinerU SDK、网络下载和 Pandoc/XeLaTeX 均使用 mock 或临时测试替身，不依赖真实网络和真实外部服务。测试验证 SDK 参数、图片资源保存、Markdown 路径、Pandoc 参数、输出文件检查和失败语义。

### TUI

- 启动参数初始化滑块；
- 滑块切换不写回配置；
- heavy/lite 标题颜色变化；
- lite 输入校验与 heavy 输入校验不同；
- 项目列表和管理表按当前引擎过滤；
- 模式切换不取消另一引擎运行中的任务；
- heavy 详情显示 TeX/错误并隐藏 Markdown；
- lite 详情显示两个 Markdown tab 并隐藏 TeX/错误；
- heavy 设置页隐藏 lite 字段，lite 设置页隐藏 TeX 源目录和 heavy validation；
- 测试期间 mock 配置保存，避免修改真实 `config/ui.toml`。

### Zotero

- heavy 仅显示 PDF 导入；
- lite 显示 PDF 和 Markdown 导入；
- Markdown 导入创建子笔记而不是附件；
- 每个选中条目都创建笔记；
- 笔记标题和完整正文正确；
- 缺少项目、选中条目、API key 或 API 请求失败时均有清晰状态。

## 9. 预计修改范围

```text
src/engines/base.py
src/engines/heavy.py
src/engines/lite.py
src/engines/lite_inputs.py
src/engines/lite_markdown.py
src/engines/lite_pdf.py
src/agents/coordinator_agent.py
src/agents/tool_agents/terminology_agent.py
src/agents/tool_agents/translator_agent.py
src/runtime.py
src/tui/app.py
src/tui/config.py
src/tui/config_schema.py
src/tui/history.py
src/tui/input_parser.py
src/tui/runner.py
src/tui/state.py
src/tui/zotero_adapter.py
src/tui/process_runner.py
config/default.toml
config/template.toml
requirements.txt
tests/
scripts/windows/latextrans-tui.cmd
scripts/linux/latextrans-tui
```

`main.py` 本次不增加 lite CLI 参数。Windows 和 Linux TUI 启动脚本继续转发参数即可，必要时只调整入口函数的参数解析。

## 10. 设计自检结论

- 没有未决的 `TBD`、`TODO` 或占位设计；
- engine 的优先级、配置持久化语义和运行时滑块语义一致；
- heavy 与 lite 的输出根目录、历史扫描和详情内容明确隔离；
- lite 的无校验、无错误报告、失败即项目失败语义明确；
- MinerU 使用 SDK、Markdown 使用二级标题分块、Pandoc 使用 XeLaTeX 均已固定；
- 本设计聚焦于新增 lite 引擎及其 TUI 适配，未扩展独立 CLI；
- 各模块职责边界明确，MinerU SDK 与 Pandoc 均通过适配层隔离。
