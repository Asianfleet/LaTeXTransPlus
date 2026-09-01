# Task 1 Report: 依赖、入口和包结构

## 实现内容

- 查询 Textual 当前文档，确认官方库 ID 为 `/textualize/textual`，当前用法仍支持实例化 `App` 子类并调用 `app.run()`。
- 在 `requirements.txt` 增加 `textual>=0.86.0`。
- 在 `setup.py` 增加 `latextrans-tui=src.tui.app:run` console script。
- 将 `setup()` 调用移动到 `if __name__ == "__main__":` 下，避免测试导入 `load_requirements()` 时触发 setuptools 命令解析。
- 新增 `src.tui` 包：
  - `src/tui/__init__.py`
  - `src/tui/app.py`
- `src.tui.app` 提供：
  - `LaTeXTransTuiApp(App[None])`
  - `run() -> None`
- 新增 `tests/test_tui_app.py`，覆盖 Textual 依赖声明和 TUI run 入口可导入。
- 同步更新 `tests/test_cli_only_distribution.py` 的旧断言：继续验证 `latextrans=main:main` 存在，同时验证新增 `latextrans-tui=src.tui.app:run` 存在。

## TDD RED 证据

首次写入 `tests/test_tui_app.py` 后运行：

```powershell
conda run -n latextrans python -m unittest tests.test_tui_app.TuiPackagingTests
```

第一次运行先暴露 `setup.py` 顶层 `setup()` 导致导入测试失败：

```text
invalid command name 'tests.test_tui_app.TuiPackagingTests'
```

修复为入口保护后重新运行同一测试，得到预期 RED：

```text
FAILED (failures=1, errors=1)
ModuleNotFoundError: No module named 'src.tui'
AssertionError: False is not true
```

这确认测试能捕捉到 Textual 依赖未声明和 TUI 包入口不存在。

## GREEN 证据

实现依赖和最小入口后，因本地 `latextrans` conda 环境尚未安装新依赖，目标测试先失败于：

```text
ModuleNotFoundError: No module named 'textual'
```

随后在指定环境安装项目依赖：

```powershell
conda run -n latextrans python -m pip install -e .
```

pip 安装到 `textual-8.2.8`，满足 `textual>=0.86.0`。

目标测试通过：

```powershell
conda run -n latextrans python -m unittest tests.test_tui_app.TuiPackagingTests
```

```text
Ran 2 tests in 0.243s
OK
```

## 旧测试冲突与同步更新

全量测试首次失败于：

```text
FAIL: test_package_exposes_only_cli_entry_point (test_cli_only_distribution.CliOnlyDistributionTests)
AssertionError: Lists differ:
['latextrans=main:main', 'latextrans-tui=src.tui.app:run']
!= ['latextrans=main:main']
```

该旧测试断言 console scripts 只能有一个，与 Task 1 明确新增 `latextrans-tui=src.tui.app:run` 冲突。经用户授权后，最小更新为验证两个预期入口都存在，不扩大范围。

同步测试后运行：

```powershell
conda run -n latextrans python -m unittest tests.test_tui_app.TuiPackagingTests tests.test_cli_only_distribution
```

```text
Ran 5 tests in 0.231s
OK
```

## 全量验证

运行：

```powershell
conda run -n latextrans python -m unittest discover tests
```

结果：

```text
Ran 186 tests in 0.639s
OK
```

## 变更文件

- `requirements.txt`
- `setup.py`
- `src/tui/__init__.py`
- `src/tui/app.py`
- `tests/test_tui_app.py`
- `tests/test_cli_only_distribution.py`
- `.superpowers/sdd/task-1-report.md`

## 自审

- 文件范围符合 Task 1 和用户追加授权。
- 新增类与函数均包含 docstring。
- Textual API 使用前已查询 Context7 官方文档。
- 测试命令均使用项目 `latextrans` conda 环境。
- `pip install -e .` 产生的 `LaTeXTrans.egg-info/` 已清理，未纳入 diff。
- 最终 diff 仅包含任务相关变更。

## 顾虑

- 无阻塞顾虑。
- 注意：为使 `from setup import load_requirements` 的测试导入稳定，`setup.py` 的 `setup()` 调用被移动到 `if __name__ == "__main__":` 下。这是测试可导入 helper 的必要包装修正。

## 复审修复

Important 复审指出新增测试类和测试方法缺少 docstring，违反全局约束。已做最小修复：

- 为 `tests/test_tui_app.py` 中新增的 `TuiPackagingTests` 类补充 docstring。
- 为 `tests/test_tui_app.py` 中两个新增测试方法补充 docstring。
- 为 `tests/test_cli_only_distribution.py` 中本任务重命名并触及的 `test_package_exposes_expected_cli_entry_points` 方法补充 docstring。

复审修复后运行：

```powershell
conda run -n latextrans python -m unittest tests.test_tui_app.TuiPackagingTests tests.test_cli_only_distribution
```

结果：

```text
Ran 5 tests in 0.224s
OK
```


# Task 1（取消状态）报告

## 状态

DONE

## 实现

- `ProjectStatus` 新增 `CANCELLED = "cancelled"`。
- `TaskViewState.apply_event` 支持 `project_cancelled` 终止事件，复用既有字段复制逻辑，并保持成功/失败计数语义不变。
- `infer_project_status` 对历史元数据中的 `cancelled` 状态直接返回，避免被产物推断覆盖。
- 增加取消事件和历史元数据加载回归测试。

## Commit

`feat(tui): add cancelled project state`

## 测试

命令：

```text
conda run -n latextrans python -m unittest tests.test_tui_state -v
```

结果：8 tests，全部通过（OK）。

## 疑虑

无。应用层停止态集合已在后续 App 任务中加入 `ProjectStatus.CANCELLED`。
