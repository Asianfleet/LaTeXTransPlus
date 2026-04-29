# 2510.14901 翻译校验重试循环记录

## 背景

运行 `python main.py --arxiv 2510.14901` 时，翻译与生成流程最终成功产出 PDF：

```text
LaTeXTrans: Successfully translated 2510.14901 to outputs\ch_2510.14901\ch_2510.14901.pdf.
```

但日志中多次出现：

```text
[ValidatorAgent] [INFO] ✅ Verification Complete for 2510.14901, remaining Errors: 2.
```

## 现象

这条日志会在以下阶段反复出现：

1. 首轮翻译完成后执行一次 `ValidatorAgent.execute()`。
2. validator 发现 2 个残留错误。
3. `CoordinatorAgent` 进入最多 3 次重译循环。
4. 每轮重译错误片段后再次执行 validator。
5. 因为同样的 2 个错误没有消失，所以每轮都继续打印 `remaining Errors: 2`。

相关流程位于：

- `src/agents/coordinator_agent.py`
  - 初次校验：`validator_agent.execute()`
  - 重试循环：`while errors_report and retry_count < MAX_RETRIES`
- `src/agents/tool_agents/validator_agent.py`
  - 日志打印：`Verification Complete ..., remaining Errors: ...`

## 具体残留错误

残留错误记录在：

```text
outputs\ch_2510.14901\errors_report.json
```

本次有两个条目：

1. `section = 5_3`
   - 原文中 `\textit` 出现 6 次。
   - 译文中 `\textit` 只剩 4 次。
   - 这是格式命令保留不完整，属于真实校验问题，但不一定会导致 LaTeX 编译失败。

2. `placeholder = <PLACEHOLDER_ENV_3>`
   - 原文使用 `\item[{\bf i)}]`、`\item[{\bf ii)}]`、`\item[{\bf iii)}]`。
   - 译文改成了 `\item[\textbf{i})]` 等形式。
   - validator 按命令计数，认为 `\bf` expected 3, found 0。
   - bracket validator 又把可选参数里的 `i)` 里的 `)` 当成结构括号，产生 `[` 与 `)` 不匹配的误报。

## 编译结果说明

`pdflatex` 失败不是最终失败。

本次 `pdflatex` 在 `lstlisting` 的中文注释处失败，例如：

```tex
# 基本情况
# 初始化前四个元素
# 迭代计算序列的其余部分
```

随后流程 fallback 到 `xelatex`，并成功生成 PDF。`build_xelatex/main.log` 中可见输出记录：

```text
Output written on build_xelatex/main.xdv (22 pages, ...)
```

因此这次问题的核心不是 PDF 生成失败，而是 validator 残留错误没有清零。

## 根因判断

这次反复日志由流程设计和校验规则共同导致：

- `CoordinatorAgent` 在 validator 有错误时会重试重译，最多 3 次。
- `TranslatorAgent` 重译后仍未修复这两个片段。
- `ValidatorAgent` 的命令计数规则要求源文和译文 LaTeX 命令完全一致，因此 `\bf` 改成 `\textbf` 会被判为缺失。
- `ValidatorAgent` 的括号检查没有跳过 LaTeX 命令参数内部的文本括号，因此 `\item[\textbf{i})]` 这类合法/近似合法 LaTeX 写法会触发误报。
- 重试耗尽后，流程仍继续执行 `GeneratorAgent`，所以最终仍会宣告 PDF 生成成功。

## 后续改进方向

可考虑分开处理两类问题：

1. 翻译输出约束
   - 对重译 prompt 增加更强约束：源文中的格式命令尽量原样保留。
   - 尤其避免把 `{\bf ...}` 自动改写成 `\textbf{...}`，除非 validator 能识别等价写法。

2. validator 规则改进
   - 对 `\bf` 与 `\textbf` 建立等价规则，避免纯样式命令改写造成误报。
   - bracket validator 应跳过 LaTeX 命令参数、数学环境或至少跳过 `\item[...]` 的 label 参数。
   - 对不会阻断编译的格式差异和会阻断编译的 LaTeX 结构错误区分严重级别。

3. 流程状态改进
   - 如果 `errors_report` 重试后仍非空，最终日志不要只打印 “Successfully translated”。
   - 可以改为 “PDF generated with validation warnings”，并输出 `errors_report.json` 路径。
