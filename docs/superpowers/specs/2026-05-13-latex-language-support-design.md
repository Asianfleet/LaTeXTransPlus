# LaTeX 目标语言宏包与编译引擎策略设计

## 背景

当前 LaTeX 重构阶段在 `LatexConstructor._revert_inputs()` 中无条件执行 `add_ctex_package(tex)`。这会导致翻译目标为日文、韩文、法文等语言时也插入 `\usepackage[UTF8]{ctex}`，污染原始模板，并可能引入不必要的编译失败。

同时，PDF 生成阶段的 `LaTexCompiler.compile()` 当前默认先尝试 `pdflatex`，再回退到 `xelatex`。这对中文、日文、韩文等 Unicode/CJK 目标语言不够合适，尤其日文 `luatexja` 通常应使用 `lualatex`。

## 范围

本次只覆盖以下目标语言代码：

- 中文：`ch`、`cn`、`zh`
- 日文：`ja`、`jp`
- 韩文：`ko`
- 法文：`fr`

阿文、俄文等其他语言暂不加入本次策略，避免把 RTL、字体选择、`babel`/`polyglossia` 等更复杂问题混入当前 bugfix。

## 目标

- 移除 `ctex` 的无条件注入。
- 根据 `target_language` 插入合适的 LaTeX 语言支持宏包。
- 根据 `target_language` 选择更合理的编译引擎顺序。
- 保持法文和未覆盖语言对原模板的侵入最小。
- 用单元测试锁定语言策略，避免后续多语言支持回退。

## 语言策略

新增一个集中策略函数，例如 `add_language_support_package(tex, target_language)`，由它负责根据目标语言决定是否插入宏包。

语言到宏包映射：

- 中文：插入 `\usepackage[UTF8]{ctex}`。
- 日文：插入 `\usepackage{luatexja}`。
- 韩文：插入 `\usepackage{kotex}`。
- 法文：不插入 CJK 或其他语言宏包。
- 其他语言：默认不插入额外语言宏包。

插入行为需要满足：

- 插入位置沿用现有行为，放在 `\documentclass` 后。
- 已存在目标宏包时不重复插入。
- 日文现有 `add_ja_package()` 中检查 `\usepackage{luatex-ja}` 但插入 `\usepackage{luatexja}` 的不一致需要修正。

## 编译策略

`LaTexCompiler` 接收可选 `target_language`。默认值保持为 `ch`，以兼容现有调用。

编译顺序：

- 中文：`xelatex -> pdflatex`
- 日文：`lualatex -> xelatex`
- 韩文：`xelatex -> pdflatex`
- 法文：`pdflatex -> xelatex`
- 其他语言：`pdflatex -> xelatex`

设计上保留 fallback，而不是只使用单一引擎。这样可以在目标环境缺少某个引擎、或原模板对某个引擎不兼容时，提高生成 PDF 的机会。

## 数据流

`GeneratorAgent` 已持有 `config`，其中包含 `target_language`。生成流程应改为：

1. 从 `self.config.get("target_language", "ch")` 读取目标语言。
2. 构造 `LatexConstructor(..., target_language=target_language)`。
3. `LatexConstructor.construct()` 在写回主 `.tex` 前调用语言宏包策略。
4. 构造 `LaTexCompiler(output_latex_dir=..., target_language=target_language)`。
5. `LaTexCompiler.compile()` 根据目标语言选择编译顺序。

## 错误处理

- 如果主 `.tex` 文件不存在，保持现有创建 `main.tex` 的行为。
- 如果某个编译引擎失败，继续尝试同语言策略中的下一个引擎。
- 如果所有引擎都失败，继续输出对应 build 目录中的 log 路径。
- 如果目标语言未被识别，不报错，按默认策略处理。

## 测试计划

新增或扩展单元测试覆盖：

- 中文目标语言会插入 `ctex`。
- 日文目标语言会插入 `luatexja`，不会插入 `ctex`。
- 韩文目标语言会插入 `kotex`，不会插入 `ctex`。
- 法文目标语言不会插入 `ctex`、`luatexja`、`kotex`。
- 已存在对应宏包时不会重复插入。
- `LaTexCompiler` 对中文、日文、韩文、法文选择预期编译顺序。
- `GeneratorAgent` 将 `target_language` 传给 `LatexConstructor` 和 `LaTexCompiler`。

最终验证命令：

```powershell
python -m unittest discover tests
```
