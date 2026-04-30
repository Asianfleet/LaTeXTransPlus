# Validation Retry Policy 可配置化设计

## 背景

当前翻译流程中，`ValidatorAgent` 负责生成 `errors_report.json`，`CoordinatorAgent` 根据 report 决定是否进入重译循环。现有行为已经支持 severity 与 retryable 字段，但策略是硬编码的：

- `command_mismatch` 固定为 `warning` 且 `retryable=false`。
- `placeholder_mismatch` 固定为 `error` 且 `retryable=true`。
- `bracket_mismatch` 固定为 `error` 且 `retryable=true`。
- coordinator 最多重试 3 轮，重试后仍有 validation report 也继续生成 PDF。

这解决了无效重译问题，但也让用户无法按任务需求切换严格程度。对于需要高保真保留 LaTeX 命令的翻译任务，`command_mismatch` 应该可以升级为可重试错误；对于批处理任务，重试耗尽后是否继续生成 PDF、CLI 是否返回非零退出码，也应该有清晰策略。

## 目标

引入轻量的 `ValidationPolicy`，让 validation 与重译行为由配置驱动：

- 每类 issue 可配置 `severity` 与 `retryable`。
- 最大校验重译轮数可配置。
- 重试耗尽后，是否仍生成 PDF 可配置。
- 重试耗尽后仍有 validation error 时，workflow 与 CLI 能返回失败状态。
- 批量处理时继续处理后续论文，最后只要任一项目失败，进程整体返回非零退出码。

## 非目标

本次不重写 translator 的重译 prompt，不改变 parser/generator 的主体职责。

本次不引入复杂策略语言。配置只支持按 issue type 的静态策略，以及少量 retry 行为开关。

本次不把 LaTeX 编译 warning 纳入 validation policy。编译阶段仍由 `GeneratorAgent` 和 LaTeX engine 负责。

## 配置结构

`config/default.toml` 增加严格默认配置：

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

字段含义：

- `max_attempts`：validation retry 循环的最大轮数。
- `generate_pdf_on_error`：重试耗尽后仍有 validation error 时，是否继续生成 PDF。
- `fail_on_error`：重试耗尽后仍有 validation error 时，workflow 是否标记失败。
- `severity`：issue 的严重级别，支持 `warning` 或 `error`。
- `retryable`：issue 是否进入定向重译。

严格默认意味着 `command_mismatch` 默认也会进入重译。用户若要恢复旧行为，可配置：

```toml
[validation.issues.command_mismatch]
severity = "warning"
retryable = false
```

## ValidationPolicy

新增轻量 helper，例如 `src/validation_policy.py`。它只负责解析与提供策略，不直接读写文件、不调用 agent。

建议接口：

```python
class ValidationPolicy:
    @classmethod
    def from_config(cls, config: dict) -> "ValidationPolicy": ...

    def issue_severity(self, issue_type: str) -> str: ...
    def issue_retryable(self, issue_type: str) -> bool: ...
    def max_attempts(self) -> int: ...
    def generate_pdf_on_error(self) -> bool: ...
    def fail_on_error(self) -> bool: ...
    def should_fail(self, validation_summary: dict) -> bool: ...
```

默认值内置在 helper 中，保证旧配置文件没有 `[validation]` 时也有明确行为。未知 issue type 默认按严格处理：`severity="error"`、`retryable=true`，避免新增 validator issue 被静默忽略。

配置校验保持简单：

- 非法 severity 回退到默认值或抛出清晰异常。推荐抛出 `ValueError`，避免用户以为配置生效。
- `max_attempts` 小于 0 时抛出 `ValueError`。
- 缺失字段使用默认值。

## Validator 行为

`ValidatorAgent` 初始化时创建 `ValidationPolicy`。

`_validate_command()`、`_validate_placeholder()`、`_validate_closed_brackets()` 不再硬编码 severity 与 retryable，而是按 issue type 从 policy 获取：

- `command_mismatch`
- `placeholder_mismatch`
- `bracket_mismatch`

`_validate()` 仍负责合并 issue，并计算 part 级别：

- 只要任一 issue 是 `error`，part severity 为 `error`。
- 否则为 `warning`。
- 只要任一 issue `retryable=true`，part retryable 为 `true`。

兼容字段继续保留：

- `part`
- `num_or_ph`
- `command_error`
- `ph_error`
- `bracket_error`

`errors_report.json` 继续保存所有 warning 和 error。无 issue 时覆盖为空列表，避免陈旧 report 留存。

## Coordinator 行为

`CoordinatorAgent` 初始化或 workflow 开始时创建同一个 `ValidationPolicy`。

重译循环：

1. 首轮翻译后执行全量 validation。
2. 使用 `filter_retryable_reports()` 过滤 `retryable=true` 的 report。
3. 最大循环轮数从 `policy.max_attempts()` 获取。
4. 每轮只重译 retryable part。
5. 每轮只重新验证本轮重译过的 part。
6. 用 `merge_validation_reports()` 保留未重试 report，并替换被重试 part 的最新 report。

重试耗尽后的生成行为：

- 如果仍有 validation error 且 `generate_pdf_on_error=false`，跳过 `GeneratorAgent`，workflow 返回失败。
- 如果仍有 validation error 且 `generate_pdf_on_error=true`，继续生成 PDF。
- 如果生成 PDF 成功但仍有 validation error 且 `fail_on_error=true`，workflow 返回失败状态，但保留 PDF 路径。

最终消息需要区分：

- 完全成功：`Successfully translated ...`
- 只有 warning：`PDF generated with validation warnings ...`
- 有 error 且 PDF 已生成：`PDF generated but validation failed ...`
- 有 error 且跳过 PDF：`Validation failed; PDF generation skipped ...`
- PDF 生成阶段失败：沿用现有 generator failure 语义，但 workflow 返回失败。

## CLI 与 Runtime 行为

`CoordinatorAgent.workflow_latextrans()` 不应只打印结果，应返回一个简单结果对象或布尔状态。推荐结果对象包含：

```python
{
    "project": "...",
    "ok": bool,
    "pdf_path": "... or None",
    "errors_report_path": "...",
    "validation_summary": {"warnings": int, "errors": int, "total": int},
}
```

`main.py` 批量处理时：

- 每个 project 独立运行。
- 单个 project validation failed 后继续处理后续 project。
- 记录是否出现任一失败。
- 所有 project 处理结束后，如果任一失败，执行 `sys.exit(1)`；否则正常退出。

`src/runtime.py` 中类似的项目处理入口需要同步该语义，避免 CLI 与 runtime helper 行为分叉。

## Translator 行为

`TranslatorAgent` 结构不需要大改。它已经支持：

- 通过 `errors_report` 定向重译 sec/env/cap。
- 在 retry prompt 中提供 `[Original]`、`[Translation]`、`[Error]` 和 `Concrete Fix Checklist`。
- 对 command mismatch 提供源文/译文命令上下文。

本设计只改变哪些 report 会传入 translator，以及最多传入几轮。

## 测试计划

新增或调整 `unittest`：

1. `ValidationPolicy` 单测
   - 默认严格策略。
   - TOML/config 覆盖 issue policy。
   - 未知 issue type 默认严格处理。
   - 非法 severity 与非法 `max_attempts` 抛出清晰异常。
   - `should_fail()` 在有 error 且 `fail_on_error=true` 时返回 true。

2. `ValidatorAgent` 单测
   - 默认 `command_mismatch` 为 `error` 且 `retryable=true`。
   - 配置后 `command_mismatch` 可恢复为 `warning` 且 `retryable=false`。
   - placeholder 与 bracket issue 继续是可重试 error。
   - `\bf` 与 `\textbf` 等价规则不回退。
   - `\item[...]` label 内括号忽略规则不回退。

3. `CoordinatorAgent` 单测
   - `max_attempts` 来自 policy。
   - 只有 warning 时不触发重译，最终状态成功但带 warning。
   - error 重试耗尽且 PDF 已生成时，返回 `ok=false`。
   - `generate_pdf_on_error=false` 时跳过 generator。
   - `merge_validation_reports()` 继续保留未重试 warning。

4. CLI/runtime 轻量测试
   - 抽出汇总 project 结果到 exit code 的 helper。
   - 多项目中一项失败时最终 exit code 为 1，但处理流程不提前停止。

## 兼容与迁移

默认行为有意变严格：`command_mismatch` 会从 warning/non-retryable 变为 error/retryable。这样高保真保留 LaTeX 命令成为默认目标。

需要旧行为的用户可以用配置恢复：

```toml
[validation.issues.command_mismatch]
severity = "warning"
retryable = false
```

旧 `errors_report.json` 字段继续保留，人工查看和 translator retry prompt 不会失效。

旧配置文件缺少 `[validation]` 时，使用内置严格默认值。

## 风险

严格默认会增加 LLM 请求次数，尤其是论文中存在大量样式命令差异时。`max_attempts` 和 issue policy 可用于控制成本。

LLM 可能多轮仍无法修复 command mismatch。此时默认仍生成 PDF，但 CLI 返回非零，用户能同时拿到产物和失败信号。

`CoordinatorAgent` 返回结果对象会触及 `main.py` 与 `src/runtime.py`。实现时需要避免改变现有下载、解压、日志 tee 等无关逻辑。
