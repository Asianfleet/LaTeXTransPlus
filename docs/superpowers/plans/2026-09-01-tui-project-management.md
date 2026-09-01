# TUI Project Management Enhancements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 Textual 项目管理页增加可持久选择、批量终止、删除和重新翻译，并通过独立子进程实现可立即强制终止翻译任务。

**Architecture:** TUI 主进程为每个翻译任务创建独立 `multiprocessing` 子进程。子进程只调用现有 `run_tui_task` 并通过可序列化队列消息发送 runtime 事件；主进程轮询队列、更新任意任务状态，并在终止时调用 `Process.terminate()` 后统一收尾。项目管理页使用自定义 `DataTable` 处理行点击，应用层维护 `(task_id, project_name)` 选中身份集合并集中计算按钮启用状态。

**Tech Stack:** Python 3.10+, Textual `DataTable`/`Button`/`@work`, `multiprocessing` spawn context, `pathlib`, `shutil`, `unittest`。

## Global Constraints

- 使用项目现有 `latextrans` conda 环境运行测试和 TUI。
- 保留现有 CLI 选项、配置键、任务状态事件和历史元数据格式兼容性。
- 新增类和函数必须有中文 docstring；文件写入显式使用 UTF-8。
- 删除只允许作用于已解析的项目 `output_dir`，不删除源项目目录。
- 不读取任何凭据或 API key。

## 文件与职责映射

- Create: `src/tui/process_runner.py`：封装子进程入口、队列消息格式、句柄启动/轮询/终止/回收。
- Modify: `src/tui/state.py`：增加 `cancelled` 状态及停止态计数兼容。
- Modify: `src/tui/history.py`：加载 `cancelled` 元数据状态。
- Modify: `src/tui/app.py`：项目管理表、按钮栏、选中集合、按钮规则、删除/重译操作、子进程生命周期和事件刷新。
- Create: `tests/test_tui_process_runner.py`：进程封装的消息、异常和终止测试。
- Modify: `tests/test_tui_state.py`：取消状态回归测试。
- Modify: `tests/test_tui_app.py`：项目管理交互、删除、重译和状态刷新测试。

### Task 1: 扩展取消状态和历史加载

**Files:**
- Modify: `src/tui/state.py:10-84`
- Modify: `src/tui/history.py:90-110`
- Test: `tests/test_tui_state.py`

**Interfaces:**
- Produces `ProjectStatus.CANCELLED` and keeps `_stopped_project_count` callers valid.

- [ ] **Step 1: 写失败测试**

```python
def test_cancelled_status_is_a_stopped_project_state(self):
    state = TaskViewState(input_type="arxiv", inputs=["paper"], total=1)
    state.apply_event({"type": "project_cancelled", "project_name": "paper"})
    self.assertEqual(state.projects[0].status, ProjectStatus.CANCELLED)
    self.assertEqual(state.completed, 0)
    self.assertEqual(state.failed, 0)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m unittest tests.test_tui_state.TuiStateTests.test_cancelled_status_is_a_stopped_project_state -v`

Expected: FAIL because `ProjectStatus.CANCELLED` and `project_cancelled` handling do not exist.

- [ ] **Step 3: 实现最小状态变更**

在 `ProjectStatus` 增加 `CANCELLED = "cancelled"`；让 `TaskViewState.apply_event` 将 `project_cancelled` 作为终止事件并保留路径/错误字段；在应用层停止态集合中加入该枚举。历史元数据解析继续复用 `ProjectStatus(status)`，因此对有效 `cancelled` 值自动兼容，并为 `infer_project_status` 的 metadata 分支补充显式回归覆盖。

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m unittest tests.test_tui_state -v`

Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add src/tui/state.py src/tui/history.py tests/test_tui_state.py
git commit -m "feat(tui): add cancelled project state"
```

### Task 2: 创建可硬终止的 TUI 子进程封装

**Files:**
- Create: `src/tui/process_runner.py`
- Test: `tests/test_tui_process_runner.py`

**Interfaces:**
- Produces:
  - `ProcessMessage = tuple[str, object]`
  - `TuiTaskProcess` dataclass with `process: multiprocessing.Process` and `queue: multiprocessing.queues.Queue`.
  - `start_tui_task_process(config_path, input_type, items, overrides) -> TuiTaskProcess`.
  - `drain_process_messages(handle) -> list[ProcessMessage]`.
  - `terminate_tui_task_process(handle) -> None`.

- [ ] **Step 1: 写失败测试**

测试顶层子进程入口而不触发真实翻译：patch `src.tui.process_runner.run_tui_task`，让 fake runner通过回调发送事件并返回结果；验证消息格式为 `("event", payload)` 和 `("result", result)`。另测 fake runner 抛异常时产生 `("error", {"error": ...})`，`terminate_tui_task_process` 调用 `terminate()`、`join()`、`close()`（若句柄支持）。

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m unittest tests.test_tui_process_runner -v`

Expected: FAIL because the module and public functions do not exist.

- [ ] **Step 3: 实现最小封装**

使用 `multiprocessing.get_context("spawn")` 创建队列和进程；定义模块级 `_process_entry`，调用 `run_tui_task(..., event_callback=lambda event: queue.put(("event", event)))`，正常结束发送 `result`，异常发送 `error`。父进程 `drain_process_messages` 使用 `get_nowait()` 循环并在 `queue.Empty` 时返回；终止函数先 `process.terminate()`（仅在 `is_alive()` 时），再 `join(timeout=5)`，超时调用 `kill()`（存在时），最后关闭队列。

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m unittest tests.test_tui_process_runner -v`

Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add src/tui/process_runner.py tests/test_tui_process_runner.py
git commit -m "feat(tui): isolate translation tasks in processes"
```

### Task 3: 将 App 任务执行改为进程事件轮询

**Files:**
- Modify: `src/tui/app.py:540-730, 880-1050, 1690-1740`
- Test: `tests/test_tui_app.py`

**Interfaces:**
- Consumes `start_tui_task_process`, `drain_process_messages`, `terminate_tui_task_process`。
- Produces `self.task_processes: dict[str, TuiTaskProcess]` and `self.cancelled_task_ids: set[str]`。

- [ ] **Step 1: 写失败测试**

增加三个异步测试：启动任务后保存返回的进程句柄并将队列事件送入 `handle_runtime_event`；子进程异常会把运行项目标记为失败并刷新表格；调用终止方法后句柄的 `terminate` 被调用，运行项目变为 `cancelled`，且迟到的 `project_complete` 不会覆盖取消状态。

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m unittest tests.test_tui_app.TuiAppTests.test_process_task_events_update_state -v`

Expected: FAIL because App still calls `run_tui_task` directly in a thread and has no process registry.

- [ ] **Step 3: 实现进程生命周期**

在 `__init__` 初始化进程注册表；`run_current_task` 调用 `start_tui_task_process`，循环 `drain_process_messages`，通过 `call_from_thread` 处理事件，检测 `process.is_alive()` 和消息终态后退出。`handle_runtime_event` 改为接受 `self.tasks` 中任意任务，不再只接受 `current_task`；对已取消 task id 忽略迟到的完成/失败事件。终止收尾为运行项目发送 `project_cancelled`，清理注册表，刷新列表、任务表和按钮状态。保留现有通知文案，并在子进程错误消息上调用现有任务级错误处理。

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m unittest tests.test_tui_app -v`

Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add src/tui/app.py tests/test_tui_app.py
git commit -m "feat(tui): control translation processes from app"
```

### Task 4: 增加项目管理表的多选列和按钮栏

**Files:**
- Modify: `src/tui/app.py:180-250, 570-625, 665-760`
- Test: `tests/test_tui_app.py`

**Interfaces:**
- Produces `ProjectManagementTable(DataTable)` with row click callback。
- Produces `self.selected_project_keys: set[tuple[str, str]]`。
- Produces `_refresh_project_action_buttons()`, `_toggle_project_selection(row_index)`, `_selected_project_states()`。

- [ ] **Step 1: 写失败测试**

覆盖以下行为：表格列顺序为 `选中/项目/状态/任务 id`；单击第一行后单元格变为 `[√]`，再次点击恢复 `[]`；选择一个运行项目时仅终止按钮启用，选择一个完成项目时删除和重译启用；同时选择运行与完成项目时三个按钮都禁用；刷新列表后仍保留存在项目的选中身份。

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m unittest tests.test_tui_app.TuiProjectManagerTests -v`

Expected: FAIL because the toolbar, selection column, and button state calculation do not exist.

- [ ] **Step 3: 实现表格和按钮规则**

在 `PAGE_TASKS` 顶部加入 `Horizontal(id="project-actions")` 和三个带稳定 id 的按钮。自定义表格在 `on_mouse_down`/行点击事件中把当前 cursor row 交给 App；App 用 `(task.task_id, project.project_name)` 映射行，并在刷新时重建行数据、写入 `[]`/`[√]`。按钮规则严格使用全选条件：空集合全部禁用，终止要求全部 `RUNNING`，删除和重译要求全部非 `RUNNING`。将 `CANCELLED` 纳入非运行判断。

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m unittest tests.test_tui_app.TuiProjectManagerTests -v`

Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add src/tui/app.py tests/test_tui_app.py
git commit -m "feat(tui): add project selection controls"
```

### Task 5: 实现删除和批量重新翻译

**Files:**
- Modify: `src/tui/app.py:665-760, 970-1070, 1690-1740`
- Modify: `src/tui/history.py:15-70`（仅在需要保留原始输入元数据时）
- Test: `tests/test_tui_app.py`

**Interfaces:**
- Produces `_delete_selected_projects() -> None` and `_retry_selected_projects() -> None`。
- Produces `_retry_input_for_project(task, project) -> tuple[str, str]`，返回可交给 `TaskViewState` 的 `(input_type, input_item)`。

- [ ] **Step 1: 写失败测试**

删除测试使用临时 `output_dir`，验证目录被删除、项目从 `tasks` 消失、源 `project_dir` 仍存在；patch `shutil.rmtree` 抛错时验证失败项目保留且其他项目继续删除。重译测试验证 arXiv 任务使用原始输入，local/history 项目回退到 `project_dir`，多个选中项目只创建一个新 `TaskViewState` 并调用一次进程启动。

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m unittest tests.test_tui_app.TuiProjectManagerTests.test_delete_selected_projects -v`

Expected: FAIL because operation handlers and retry input resolution do not exist.

- [ ] **Step 3: 实现删除**

遍历选中快照；对非运行项目调用 `shutil.rmtree(Path(project.output_dir))`（目录不存在视为已删除），成功后从所属 task 移除，空 task 从 `self.tasks` 移除；单项异常通过 `notify(..., severity="error")` 报告并继续。清理选中身份、详情选择和表格后统一刷新。

- [ ] **Step 4: 实现重译**

按项目解析输入：优先从 `task.inputs` 与 `task.input_type` 映射单项目；若历史输入类型为空或为 `history`，且 `project.project_dir` 存在，则返回 `("local", project.project_dir)`；否则使用项目名作为 arXiv/原始输入。将所有可重译项目的输入合并到一个新任务，追加到 `self.tasks`，调用 `start_current_task`，并清除旧选择。新任务产生的同一输出目录事件继续走 `_replace_history_project` 去重。

- [ ] **Step 5: 运行测试确认通过**

Run: `python -m unittest tests.test_tui_app.TuiProjectManagerTests -v`

Expected: PASS。

- [ ] **Step 6: 提交**

```bash
git add src/tui/app.py src/tui/history.py tests/test_tui_app.py
git commit -m "feat(tui): add delete and retry actions"
```

### Task 6: 完整验证与差异清理

**Files:**
- Modify: only task-related files if verification exposes regressions.

- [ ] **Step 1: 运行聚焦测试**

Run: `python -m unittest tests.test_tui_state tests.test_tui_process_runner tests.test_tui_app -v`

Expected: PASS。

- [ ] **Step 2: 运行完整测试套件**

Run: `python -m unittest discover tests`

Expected: all discovered tests pass; if TeX compiler dependencies are absent, record the exact skipped/failing dependency-bound tests instead of masking them.

- [ ] **Step 3: 检查差异卫生**

Run: `git diff --check; git status --short; git diff --stat HEAD~5..HEAD`

Expected: no whitespace errors, only task-related source/tests/docs changes, and no generated output or configuration changes.

- [ ] **Step 4: 提交必要的回归修复**

若验证发现本任务引入的回归，只修改相关文件，补充对应测试后提交：

```bash
git add src tests
git commit -m "fix(tui): address project management regressions"
```

