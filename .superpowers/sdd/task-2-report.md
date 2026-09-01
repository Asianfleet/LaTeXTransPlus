# 历史报告：UI 配置初始化与保存

此前任务的报告内容保留如下，避免覆盖已有记录：

- 新增 `src/tui/config.py`，提供 TUI 专用配置管理接口。
- 定义 `UI_CONFIG_PATH = Path("config") / "ui.toml"`。
- 实现配置文件初始化、加载和保存，并覆盖默认配置复制、模板回退和 round trip 测试。
- TDD 聚焦测试 `tests.test_tui_config` 已通过。

# Task 2 实现报告

## 实现

- 新增 `src/tui/process_runner.py`，定义 `ProcessMessage`、`TuiTaskProcess` 及三个公开函数。
- 使用 `multiprocessing.get_context("spawn")` 启动独立翻译进程。
- 子进程入口将运行时事件封装为 `("event", payload)`，成功结果封装为 `("result", result)`，异常封装为 `("error", {"error": ...})`。
- 父进程通过 `drain_process_messages` 非阻塞读取队列。
- `terminate_tui_task_process` 先调用 `terminate()` 并等待，超时后调用可用的 `kill()`，最后关闭进程和队列句柄。
- 新增 `tests/test_tui_process_runner.py` 覆盖事件/结果、异常、队列 drain 及终止生命周期。

## 自测

命令：

```text
conda run -n latextrans python -m unittest tests.test_tui_process_runner -v
```

结果：4 项测试全部通过（OK）。

## 顾虑

- 事件和结果通过 `multiprocessing.Queue` 跨进程传递，因此 payload 必须保持可 pickle。
- `terminate()` 后的迟到队列消息由调用方决定是否丢弃；本封装只负责生命周期和消息读取。
- Windows `spawn` 要求后续调用方在可导入的模块上下文中启动进程，当前入口函数已保持模块级定义以满足该要求。
