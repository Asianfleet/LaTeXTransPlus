# TUI 项目列表排序选择 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 在 TUI 左侧“项目管理”下增加排序方式选择，并让项目列表支持按首字符、标题或创建时间展示。

**Architecture:** 在 `src/tui/project_list.py` 集中定义排序模式和值，以及不修改原始状态的排序函数；`LaTeXTransTuiApp` 持有当前会话排序模式，在侧栏组合 `Select`，监听选择变化后刷新 `ListView`。创建时间优先使用任务 ID 中现有的时间戳，再尝试目录 birth time；只有 Windows 的旧 Python 环境回退到 st_ctime，其余不可用时保留稳定列表顺序，避免改变项目身份和任务数据。

**Tech Stack:** Python 3.10+, Textual `Select` / `Select.Changed`, `unittest`。

**Spec:** 用户请求（2026-10-25）：左侧栏项目管理下面增加一个 select，三种排序方式为按首字符、按标题、按创建时间。

## Global Constraints

- 默认语言、UI 文本和新增代码注释使用中文。
- 只修改与本功能直接相关的文件；不改变任务身份、项目选择和任务管理表顺序语义。
- 文本排序按稳定升序；创建时间按最新优先展示，优先解析任务 ID，再读取可靠的目录 birth time；只有 Windows 的旧 Python 环境回退到 st_ctime。
- 遵循现有 TUI 测试约束，不运行完整 TUI 测试套件之外的无关测试；测试不得修改真实 `config/ui.toml`。

## Review Focus

- 三个选项都能改变左侧列表顺序，且默认仍按首字符排序。
- 标题为空时按界面占位文本排序，不会因缺失标题抛异常。
- 相同排序键保持原始顺序，避免项目身份或重复项目被错误合并。
- 历史任务没有时间戳时仍能稳定展示。
- `Select` 变化只刷新列表，不触发任务提交、配置保存或项目选择丢失。

---

### Task 1: 排序策略与失败测试

**Files:**
- Modify: `src/tui/project_list.py`
- Test: `tests/test_tui_project_list.py`

**Interfaces:**
- Produces a public-in-module sort mode definition and a pure helper that accepts flattened `(TaskViewState, ProjectViewState)` rows plus the selected mode and returns a sorted list.

**Steps:**

- [x] 为三个排序模式、默认模式和排序结果写最小失败测试；覆盖首字符、标题、时间戳以及缺失标题/时间戳回退。
- [x] 运行定向测试，确认它因排序接口不存在或行为缺失而失败。
- [x] 在 `project_list.py` 实现带 docstring 的模式定义与稳定排序 helper，不改变原始列表。
- [x] 运行定向测试，确认排序策略通过。

### Task 2: 接入侧栏 Select 与列表刷新

**Files:**
- Modify: `src/tui/app.py`
- Modify: `src/tui/app.tcss`
- Test: `tests/test_tui_app.py`

**Interfaces:**
- Adds `#project-sort-select` under `#project-manager-button`.
- Adds `Select.Changed` handling that updates the session sort mode and calls `refresh_project_list()`.
- `refresh_project_list()` applies the pure sorter before creating `ProjectListItem` instances.

**Steps:**

- [x] 为侧栏控件存在、选项文本和值、默认值以及交互排序写失败测试。
- [x] 运行这些定向测试确认红灯。
- [x] 在 App 中接入控件、事件处理、会话状态和刷新排序；增加必要 CSS 宽度/间距。
- [x] 运行定向测试确认绿灯。

### Task 3: 回归验证与计划记录

**Files:**
- Modify: `docs/superpowers/plans/2026-10-25-tui-project-list-sorting.md`

**Steps:**

- [x] 运行排序相关测试和项目状态相关回归测试。
- [x] 检查 `git diff`，确认没有无关改动。
- [x] 在本计划中勾选完成步骤，并记录实现说明。
- [x] 如代码已修改，建议一个英文提交信息。

## Implementation Notes

- 排序模式和值集中在 `src/tui/project_list.py`，文本排序使用 NFKC 规范化和 casefold；缺失标题沿用界面占位文本。
- 创建时间优先从任务 ID 时间戳解析，历史任务再读取目录 birth time；仅 Windows 的旧 Python 环境回退到 st_ctime，POSIX 无 birth time 时按原顺序稳定展示。创建时间排序为最新优先；排序后点击侧栏条目直接使用条目保存的 `(task_id, project_name)`，避免排序索引与详情身份错位。
- 最终定向验证排序、侧栏选择和项目进度相关测试：11 项通过（8 项排序/交互测试、3 项侧栏进度回归）。
- 布局跟进：侧栏 Select 及其 SelectCurrent 均设置 16 列最小宽度和 100% 宽度，并将 SelectCurrent 边框改为与 flat Button 一致的 `block $surface`，避免可见边框造成左右缩进；新增 120 列终端宽度断言，比较 SelectCurrent 与项目管理按钮宽度。定向排序/布局测试通过。
