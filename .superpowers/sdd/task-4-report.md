# Task 4 报告：状态模型和事件归并

## 状态

已完成。

## TDD 证据

### RED

先创建 `tests/test_tui_state.py`，覆盖以下行为：

- `run_start` 设置 `TaskViewState.total`
- `project_start` 创建项目并标记为 `RUNNING`
- `project_complete` 更新项目路径、状态和完成/失败计数
- `project_error` 创建或更新项目并统计失败数

运行命令：

```powershell
conda run -n latextrans python -m unittest tests.test_tui_state
```

结果：失败，符合预期。

关键错误：

```text
ModuleNotFoundError: No module named 'src.tui.state'
FAILED (errors=1)
```

### GREEN

实现 `src/tui/state.py` 后再次运行：

```powershell
conda run -n latextrans python -m unittest tests.test_tui_state
```

结果：

```text
Ran 3 tests in 0.000s
OK
```

### 扩展验证

运行相关 TUI 测试集合：

```powershell
conda run -n latextrans python -m unittest tests.test_tui_state tests.test_tui_input_parser tests.test_tui_config tests.test_tui_app
```

结果：

```text
Ran 14 tests in 0.261s
OK
```

## 变更文件

- `src/tui/state.py`
- `tests/test_tui_state.py`
- `.superpowers/sdd/task-4-report.md`

## 实现说明

- 新增 `ProjectStatus` 枚举：`PENDING`、`RUNNING`、`COMPLETED`、`FAILED`。
- 新增 `ProjectViewState`，保存单个项目的展示状态、路径、验证摘要、错误信息和 Zotero 导入状态。
- 新增 `TaskViewState`，保存输入类型、输入列表、总数、完成数、失败数、当前运行项目、事件列表和项目列表。
- `TaskViewState.apply_event()` 会保留原始事件，并根据 `run_start`、`project_start`、`project_complete`、`project_error` 归并状态。
- `project_complete` 和 `project_error` 后会从项目列表重新统计 `completed` 与 `failed`，避免重复事件导致计数漂移。

## 自审

- 新增类、函数和测试方法均包含 docstring。
- 只实现状态模型，没有实现 runner 或 Textual UI。
- 字段名按 brief 使用。
- 未修改 `.superpowers/sdd/progress.md`。
- 未读取 secrets。

## 顾虑

- `running_project` 在项目完成或失败后当前仍保留最后启动的项目名；brief 未要求完成时清空，因此没有额外改变该语义。
- 未知事件目前只会记录到 `events`，不改变派生状态；这与当前状态模型的最小归并需求一致。

---

# Task 4 实现报告：项目管理选择控件

## 状态

已完成项目管理表多选列、顶部操作按钮和按钮状态规则。

## 实现

- 新增 `ProjectManagementTable`，单击行切换选中状态。
- App 使用 `(task_id, project_name)` 维护 `selected_project_keys`。
- 项目表列顺序调整为“选中 / 项目 / 状态 / 任务 id”。
- 刷新表格时保留仍存在项目的选择，清除失效身份。
- 终止、删除、重新翻译按钮按全选项目状态动态启用；空选择或混合运行状态时禁用。
- 按钮事件已预留给后续终止、删除和重译实现。

## 验证

`conda run -n latextrans python -m unittest tests.test_tui_app.TuiProjectManagerTests -v`

结果：3 个测试通过。

## 顾虑

按钮具体操作由 Task 5 接入；当前仅负责控件、选择身份和可用性计算。
