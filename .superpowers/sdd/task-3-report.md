# Task 3 报告：TUI 进程事件轮询

## 状态

已完成 Task 3。`LaTeXTransTuiApp` 现在通过 `process_runner` 启动独立翻译进程，在 Textual worker 中轮询消息队列，并将事件安全地转回 UI 线程。

## TDD 证据

先新增以下失败测试并运行确认失败：

- `test_process_task_events_update_state`
- `test_process_error_marks_running_project_failed_and_refreshes`
- `test_terminate_task_marks_cancelled_and_ignores_late_completion`

初次运行因 `src.tui.app` 尚无 `start_tui_task_process` 等接口而失败，符合预期。实现后运行：

```powershell
conda run -n latextrans python -m unittest tests.test_tui_app.TuiTaskEventTests.test_process_task_events_update_state tests.test_tui_app.TuiTaskEventTests.test_process_error_marks_running_project_failed_and_refreshes tests.test_tui_app.TuiTaskEventTests.test_terminate_task_marks_cancelled_and_ignores_late_completion tests.test_tui_app.TuiTaskEventTests.test_stale_worker_events_do_not_update_new_current_task tests.test_tui_app.TuiTaskEventTests.test_worker_exception_is_reported_in_current_task -v
```

结果：`Ran 5 tests ... OK`。

另外验证了两个 remote prepare 异常回归测试，结果 `Ran 2 tests ... OK`。

## 实现内容

- 初始化 `task_processes` 和 `cancelled_task_ids` 注册表。
- `run_current_task` 使用 `start_tui_task_process`、`drain_process_messages` 轮询事件，处理子进程错误和异常退出，并在完成后清理句柄。
- `handle_runtime_event` 接受任务历史中的任意任务；取消任务后忽略迟到的完成/失败事件。
- 新增 `terminate_task_process`，调用强制终止接口，将运行项目发送 `project_cancelled` 事件并刷新视图。
- `CANCELLED` 纳入停止态集合；取消事件可持久化项目元数据。
- 保留测试替换旧 `run_tui_task` 的兼容入口，不影响生产进程隔离路径。

## 顾虑

完整 `tests.test_tui_app` 在当前环境中运行超过一分钟无输出，已中止；聚焦测试均已通过。完整测试应由主代理在所有 TUI 管理界面改动合并后统一执行。
