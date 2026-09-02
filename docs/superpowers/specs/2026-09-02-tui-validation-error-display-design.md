# TUI Validation Error Display Design

## Goal

避免验证器把论文枚举中的 `i)`、`ii)` 误报为 LaTeX 括号错误，并让校验失败在项目日志和 TUI 通知中显示可执行的原因。

## Design

验证器继续严格检查译文新增的括号结构，但先以原文为基准识别原文已有的孤立闭括号。译文与原文共享的孤立括号不产生错误；译文新增的孤立括号或真正的嵌套错配仍产生 `bracket_mismatch`。LaTeX 命令参数的大括号仍参与校验。

协调器在重试耗尽后生成稳定的 validation failure message，将剩余错误数和报告路径写入项目日志，并放入 workflow result 的 `error` 字段。TUI 沿用现有 `project_error` 事件和通知通道，直接展示该 message；没有 message 时仍保留现有兜底文本。

## Acceptance Criteria

- 包含原文枚举 `i)`/`ii)` 的 caption 在翻译内容保留这些枚举时不再产生括号误报。
- 译文新增不匹配的括号仍被报告。
- 校验失败结果的 `error` 不为空，并包含剩余错误数和错误报告路径。
- 项目日志包含最终校验失败摘要；TUI 通知不再显示“未知异常”。
- `generate_pdf_on_error=false` 的既有行为保持不变。

## Testing

新增验证器回归测试，并扩展协调器/TUI 事件测试；运行针对性测试和完整 `python -m unittest discover tests`。
