# Lite 附录翻译开关设计

## 目标

为 Lite PDF-to-Markdown 翻译增加 `lite.translate_appendix` 布尔设置。默认值为 `true`，保持现有行为。当它为 `false` 时，Lite 检测到附录标题后，保留附录及其后续内容的原始 Markdown，不把这些内容发送给翻译或术语生成模型。生成的 `translated.md` 和 `translated.pdf` 仍包含原文附录。

本设计只影响 Lite 引擎，不改变 Heavy、`latextrans` CLI 的源码翻译流程或既有公共配置项。

## 配置与界面

在 `[lite]` 增加：

```toml
translate_appendix = true
```

`config/default.toml` 和 `config/template.toml` 都声明该默认值。`src/engines/base.py` 将它列为 Lite runtime field，因此 `engine_config(..., "lite")` 可以传给 Lite，同时 Heavy effective config 不会获得它。

TUI 在 Lite 的“翻译”分组增加“翻译附录”开关。缺少该键的旧 UI 配置在运行时和表单显示中均按 `true` 处理，不重写格式正确的现代 `ui.toml`；用户下一次保存设置时会写入该值。旧布局的迁移默认值同样是 `true`。

## 附录识别与块策略

附录仅由非代码围栏内的 ATX Markdown 标题触发，标题文本去除编号、尾随 `#` 和首尾空白后再匹配。普通段落、代码围栏、YAML front matter 中出现的相同字串绝不触发。

标题词表由 `source_language` 选择，覆盖当前 TUI 提供的源语言：英语 `Appendix`、`Appendices`，中文“附录”及繁体“附錄”，德语 `Anhang`，法语 `Annexe`，日语“付録”，韩语“부록”。各语言允许紧随的编号、字母或说明性副标题，例如 `Appendix A. Details`、`附录 A` 和 `Annexe : résultats`。不把“Supplementary Material”等语义相近但不等价的标题纳入本次范围。

`split_markdown` 保持现有按二级标题的普通切块规则，但在命中的附录标题处无条件创建额外边界，即使该标题为一级或三级标题。关闭翻译附录后，从首个命中标题到文末的所有块都设置为 `translatable=False`；附录标题本身亦保留原文。没有命中时块结构和翻译行为完全不变。

## 工作流与可观测性

`LiteEngine` 在 MinerU 抽取和数学规范化之后生成一次带附录策略的块列表，并将该列表交给翻译阶段。`MarkdownTranslatorAgent` 已有的不可翻译块分支原样返回文本，因此不会产生 LLM 请求。

术语阶段使用同一策略筛选的可翻译内容收集候选项，避免附录影响 `project_terms.csv`、术语决策或术语模型成本。文档级标题和摘要上下文沿用既有逻辑；它们位于附录之前时不受影响。

关闭开关且检测到附录时，Lite 日志记录匹配到的标题和跳过的块数。开关开启或未检测到附录时，不增加告警，不影响成功结果的结构。

## 回归测试

测试覆盖以下风险：

- Lite effective config 仅携带 `translate_appendix`，Heavy 不携带该字段；默认配置、模板、旧 UI 配置迁移与 TUI switch 正确处理默认 `true`。
- 每种支持源语言的常用附录标题和带编号变体均被识别；围栏代码、front matter 与正文中的伪标题不触发；三级附录标题能把先前正文与附录分开。
- 开关关闭时，翻译代理不请求附录块，重建的 Markdown 保留附录标题和内容原文；开启或未命中时所有既有可翻译块仍正常处理。
- Markdown 术语记录不包含被跳过的附录内容。
- Lite 端到端测试验证 `translated.md` 和 PDF 输入包含原样附录，并验证日志包含跳过信息。

README.md 与 README_ZH.md 的 Lite 配置示例和说明同步写明默认值、识别范围和关闭后的保留行为。
