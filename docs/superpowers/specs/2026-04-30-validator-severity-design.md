# Validator Severity 分级体系设计

## 背景

当前 `ValidatorAgent` 会把所有校验失败都放入同一个 `errors_report`，`CoordinatorAgent` 只要看到非空 report 就进入重译循环。这个行为导致两类问题混在一起：

- 真正可能破坏 LaTeX 结构或导致占位符丢失的问题，需要重译。
- 格式命令数量差异、等价样式命令差异等不一定阻断编译的问题，也会触发重译，造成无效 retry。

`docs/validator-retry-loop-2510.14901.md` 中记录的 `2510.14901` 问题已经证明：如果 validator 不区分严重级别，流程会把 warning 级别问题当成 error 重试，最终仍可能带着校验残留继续生成 PDF。

## 目标

实现一个结构化 severity 分级体系，让 validator 输出可被 coordinator 明确消费：

- `error`：需要进入重译循环的问题。
- `warning`：记录并最终提示，但默认不触发重译的问题。

同时保留现有 `errors_report.json` 的关键兼容字段，避免一次性破坏 translator retry prompt、用户查看报告和已有调试习惯。

## 非目标

本次不建立完整 LaTeX 编译诊断系统，不尝试准确预测所有命令缺失是否必然导致编译失败。编译阶段仍由 `GeneratorAgent` 和 LaTeX engine 负责。

本次不引入配置文件开关。默认规则先覆盖当前已知问题，后续如有更多案例再扩展。

## 数据结构

每个 part 的 report 保持字典结构，新增结构化字段：

```python
{
    "part": "sec",
    "num_or_ph": "5_3",
    "severity": "warning",
    "retryable": false,
    "issues": [
        {
            "type": "command_mismatch",
            "severity": "warning",
            "retryable": false,
            "message": "'\\textit' — expected 6, found 4"
        }
    ],
    "command_error": "LaTeX command translation error or is missing:\n'\\textit' — expected 6, found 4"
}
```

兼容字段继续保留：

- `part`
- `num_or_ph`
- `command_error`
- `ph_error`
- `bracket_error`

新增字段用于流程控制：

- `issues`：结构化 issue 列表。
- `severity`：该 part 的最高严重级别。
- `retryable`：该 part 是否应进入重译。

## 默认分级规则

默认规则采用保守策略：只有明确结构性问题进入重译。

| issue type | severity | retryable | 说明 |
| --- | --- | --- | --- |
| `placeholder_mismatch` | `error` | `true` | placeholder 缺失或多余会破坏重构语义。 |
| `bracket_mismatch` | `error` | `true` | 译文新增括号结构错误，可能破坏 LaTeX。 |
| `command_mismatch` | `warning` | `false` | 命令数量差异不一定阻断编译，先记录不重试。 |

已处理的等价样式命令，例如 `\bf` 与 `\textbf`，不产生 issue。

## Validator 行为

`ValidatorAgent._validate()` 继续返回 `None` 或 report 字典，但内部改为先收集 issue：

1. `_validate_command()` 返回 command mismatch issue 列表或空列表。
2. `_validate_placeholder()` 返回 placeholder issue 列表或空列表。
3. `_validate_closed_brackets()` 返回 bracket issue 列表或空列表。
4. `_validate()` 合并 issue，计算最高 severity 与 retryable。
5. 为兼容旧逻辑，同步生成原有字符串字段。

severity 计算规则：

- 只要有任一 issue 为 `error`，part severity 为 `error`。
- 否则只要有任一 issue 为 `warning`，part severity 为 `warning`。
- 没有 issue 时返回 `None`。

retryable 计算规则：

- 任一 issue `retryable=true` 时，part `retryable=true`。
- 否则为 `false`。

## Coordinator 行为

`CoordinatorAgent` 收到 `errors_report` 后不再对所有 report 重试，而是过滤：

```python
retryable_reports = [report for report in errors_report if report.get("retryable", True)]
```

兼容策略：如果旧 report 没有 `retryable` 字段，默认视为 `true`，保证旧数据仍能被重试。

重译循环只处理 `retryable_reports`。每轮 validator 仍会返回完整 report；coordinator 再次过滤 retryable report 决定是否继续。

最终消息按完整 report 汇总：

- 无 report：`Successfully translated`
- 只有 warning：`PDF generated with validation warnings`
- 存在 error：`PDF generated with validation errors`

最终消息应包含：

- remaining warning/error 数量。
- `errors_report.json` 路径。

## Translator 行为

`TranslatorAgent` retry prompt 只接收 coordinator 过滤后的 retryable report，因此 warning 默认不会消耗重译次数。

现有 `_build_retranslation_user_prompt()` 可以继续使用。未来如果某个 command mismatch 被升级为 retryable error，它仍能利用当前的具体命令上下文。

## 错误报告文件

`errors_report.json` 继续保存所有 issue，包括 warning 和 error。这样即使只有 warning，用户也能看到为什么最终消息提示 validation warnings。

如果某轮 validator 没有任何 issue，应清理或覆盖旧的 `errors_report.json`，避免上一次运行的陈旧报告误导用户。实现时优先采用覆盖为空列表或删除旧文件中的一种，并在测试中固定行为。

推荐采用覆盖为空列表：保留文件路径稳定，便于最终消息和外部工具引用。

## 测试计划

新增或调整 `unittest` 覆盖以下行为：

- command mismatch 产生 `warning`、`retryable=false`。
- placeholder 缺失产生 `error`、`retryable=true`。
- bracket mismatch 产生 `error`、`retryable=true`。
- `\bf` 与 `\textbf` 等价，不产生 command issue。
- `\item[...]` label 内的文本括号不产生 bracket issue。
- coordinator 只有 warning 时不进入重译，最终消息为 validation warnings。
- coordinator 有 error 时仍进入重译，最终消息在错误残留时为 validation errors。
- validator 无 issue 时覆盖 `errors_report.json` 为空列表，避免陈旧报告。

## 迁移与兼容

旧字段保留，因此 translator retry prompt 和人工查看报告不会失效。

旧 report 如果缺少 `retryable`，coordinator 默认按 `true` 处理，避免历史 report 被错误跳过。

已有测试应保持通过。新增测试只绑定公开行为和必要 helper，不依赖过多内部实现细节。
