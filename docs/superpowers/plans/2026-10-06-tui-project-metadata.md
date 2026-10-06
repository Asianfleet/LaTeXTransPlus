# TUI 项目元数据与 profile 下拉列表实施计划

> 执行方式：使用 writing-plans 制定计划，executing-plans 在当前分支逐项实施。用户已授权省略 spec 文档，不创建 worktree，不自动提交。

**目标：** lite/heavy 设置页均支持 profile 下拉选择，项目列表显示可截断且可悬浮查看的原文标题，项目管理表显示标题及本次翻译模型。

**架构：** 两种引擎共享标题提取工具，通过 `project_metadata` 事件更新项目状态；任务运行时捕获实际翻译模型。现有 `.latextrans-tui.json` 扩展为 schema 3，支持历史恢复及旧标题回填。展示逻辑仍由共享 TUI 实现。

**技术栈：** Python、unittest、Textual、Rich、现有 LaTeX/Markdown 解析工具。

## 全局约束

- 在当前分支实施，文件明确使用 UTF-8；新函数和类包含用途 docstring。
- 仅使用 `latextrans` conda 环境运行项目及测试；默认仅执行本次新增 TUI 测试。
- 不读取真实凭据，不枚举凭据环境变量；profile 列表只枚举文件名。
- UI 测试在整个交互生命周期 mock 配置保存，并比较真实配置哈希。
- 元数据缺失或标题提取失败不影响翻译；旧模型不可从当前配置推断。
- 任务标识仍为任务 id + 项目名，标题不得参与选中和批量操作身份判断。

## 任务 1：共享标题提取、profile 枚举与状态/历史

文件：新增 `src/project_metadata.py`；修改 `src/tui/config.py`、`src/tui/config_schema.py`、`src/tui/state.py`、`src/tui/history.py`；新增 `tests/test_tui_project_metadata.py`。

接口：`title_from_latex_captions(captions) -> str`、`title_from_markdown(markdown) -> str`、`read_project_title(project_dir, engine, source_markdown_path=None) -> str`；`list_llm_profiles(config_path) -> list[tuple[str, str]]`。

- [x] 编写失败测试：嵌套 LaTeX 标题、Markdown 代码块排除、多语言标题、profile 目录枚举、事件不改变任务计数、schema 3 恢复和旧记录回填。
- [x] 执行 `conda run -n latextrans python -m unittest discover -s tests -p test_tui_project_metadata.py`，确认新增行为缺失导致失败。
- [x] 实现共享提取工具、动态 profile 类型及状态字段 `title`/`translation_model`。元数据事件不改变状态和完成计数，空字段不覆盖已知值。
- [x] 扩展历史读写：schema 3；相同任务的状态保存保留字段；新的任务不得继承旧模型；旧记录仅读原文产物回填标题，未知模型显示“unknown”。
- [x] 重跑上述命令，确认通过并填写实施说明。

## 任务 2：两种引擎事件接入

任务 1 实施说明：新增原文标题共享提取工具和 profile 文件名枚举；状态及 schema 3 历史保存标题/模型。旧历史恢复标题到内存，不推断旧模型。回归测试覆盖短标题选项包含花括号时的嵌套 LaTeX 参数，修复后 5 项通过。

文件：修改 `src/runtime.py`、`src/tui/runner.py`、`src/agents/coordinator_agent.py`、`src/engines/lite.py`；新增 `tests/test_project_metadata_events.py`。

接口：`project_metadata` 事件包含 `project_name`、`output_dir`、`title`，运行事件携带 `translation_model`。

- [x] 编写失败测试：Heavy 解析后即发标题事件、Lite 提取后即发标题事件、runner 使用有效配置的模型并固定快照、失败事件保留已知元数据。
- [x] 执行 `conda run -n latextrans python -m unittest discover -s tests -p test_project_metadata_events.py`，确认缺少元数据行为导致失败。
- [x] Heavy 在解析完成/已有映射重译时发标题事件；Lite 在原文 Markdown 可用时发标题事件；运行时携带模型，runner 固定本次有效配置模型，不传递凭据。
- [x] 重跑新增测试并运行相关非 TUI 引擎回归测试，确认通过并填写实施说明。

## 任务 3：共享界面展示

任务 2 实施说明：Heavy 在解析及重译映射读取后发标题事件，Lite 在原文 Markdown 可用后发事件。使用独立元数据回调，保持日志回调契约；runner 从有效配置冻结模型快照。新增 3 项事件测试、16 项 Lite 引擎测试和 32 项 runtime 项目结果测试通过。

文件：修改 `src/tui/app.py`；新增 `tests/test_tui_metadata_ui.py`。

- [x] 编写失败测试：两种模式 profile 控件为 Select、缺失 profile 保留、选中自动保存、新标题事件刷新并持久化、列表省略和悬浮完整标题、表格新列与缩放后宽度调整、选择状态保持。
- [x] 执行 `conda run -n latextrans python -m unittest discover -s tests -p test_tui_metadata_ui.py`，确认新行为缺失导致失败。
- [x] 设置页动态加载选项；缺失值加入带提示选项；空目录提示且不自动切换；刷新时抑制 Changed 保存。
- [x] 列表保持一行、按终端字符宽度省略，鼠标悬浮展示纯文本完整标题。项目表列顺序为选中/项目/标题/翻译模型/状态/任务 id，分配剩余空间给标题；窄屏允许横向滚动。
- [x] 持久化接收元数据事件，通过状态中的输出路径保存；resize 后重绘表格并保留选择和游标。
- [x] 重跑新增测试，检查真实 UI 配置哈希不变并填写实施说明。

## 任务 4：最终验证和审阅

任务 3 实施说明：共享设置页使用动态 Select 并保留失效 profile；列表单行省略并使用纯文本 tooltip 展示完整标题；项目表新增两列并在 resize 后重新分配标题宽度。新增 3 项交互测试涵盖两种模式、真实 tooltip 展示及选择保持，真实 UI 配置哈希保持一致。同步更新原有测试中的控件类型和列索引预期。

- [x] 合并运行三个新增测试模块；运行相关非 TUI 回归测试，跳过旧 TUI 测试。
- [x] 执行 `git diff --check` 与 `git diff --stat`，审阅所有变更，确认真实配置和生成产物没有无关变化。
- [x] 逐项核对四项用户要求和旧历史兼容；在本计划补充测试结果和实施说明。
- [x] 汇报文件变化、验证结果及未运行项目；给出英文 commit message，不自动提交。

任务 4 实施说明：最终在 `latextrans` 环境执行以下命令，合计 59 项测试通过：

```powershell
conda run --no-capture-output -n latextrans python -X utf8 -m unittest discover -s tests -p 'test_*metadata*.py'
conda run --no-capture-output -n latextrans python -X utf8 -m unittest discover -s tests -p test_lite_engine.py
conda run --no-capture-output -n latextrans python -X utf8 -m unittest discover -s tests -p test_runtime_project_results.py
git diff --check
```

新增模块共 11 项测试通过，相关 Lite/runtime 回归共 48 项通过；diff 检查通过。配置哈希校验通过，`config/ui.toml` 无 diff；没有生成产物或无关配置改动。按项目要求未执行旧 TUI 整套测试，已同步更新受影响的旧断言；未进行远程 LLM/MinerU/PDF 编译端到端翻译验证。当前分支保留未提交变更。
