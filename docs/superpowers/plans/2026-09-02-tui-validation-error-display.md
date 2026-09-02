# TUI Validation Error Display Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 caption 枚举括号误报，并让验证失败原因进入项目日志和 TUI 通知。

**Architecture:** 在 `ValidatorAgent` 中以原文括号状态为基准过滤译文继承的孤立括号；在 `CoordinatorAgent` 统一生成验证失败摘要并作为 workflow result 错误；TUI 继续消费 `project_error`，无需新增事件类型。

**Tech Stack:** Python 3.10+, unittest, pathlib, Textual。

## Global Constraints

- 保持 `generate_pdf_on_error` 和 `fail_on_error` 配置语义不变。
- 使用现有 `unittest` 测试框架。
- 不读取或提交 API key 等秘密。

---

### Task 1: Validator Regression

**Files:**
- Modify: `tests/test_validator_agent.py`
- Modify: `src/agents/tool_agents/validator_agent.py`

**Interfaces:**
- `ValidatorAgent._validate_closed_brackets(part)` 保持现有返回类型。

- [ ] **Step 1: Write the failing tests**

添加测试：原文和译文均包含 `i)`/`ii)` 时不返回 `bracket_mismatch`；译文额外增加 `)` 时仍返回该错误。

- [ ] **Step 2: Run the focused tests**

运行 `python -m unittest tests.test_validator_agent -v`，确认新测试在现有实现下失败。

- [ ] **Step 3: Implement the minimal validator change**

调整括号扫描/比较逻辑，只忽略原文已经存在且译文未新增的孤立括号；保留译文新增括号和 LaTeX 大括号错配检测。

- [ ] **Step 4: Run the focused tests again**

运行同一命令，确认测试通过。

### Task 2: Validation Failure Propagation

**Files:**
- Modify: `src/agents/coordinator_agent.py`
- Modify: `tests/test_runtime_project_results.py`

**Interfaces:**
- `build_workflow_result(...)` 继续返回现有字段，并在验证失败时包含非空 `error`。

- [ ] **Step 1: Write the failing test**

扩展协调器结果测试，验证校验失败结果的 `error` 包含错误数和 `errors_report.json`，并验证项目日志回调收到最终失败摘要。

- [ ] **Step 2: Run the focused test**

运行对应 unittest，确认现有实现失败。

- [ ] **Step 3: Implement the minimal propagation change**

在重试循环后构造 validation failure message，通过 `_log(..., level="error")` 写入项目日志，并传给所有失败 workflow result。

- [ ] **Step 4: Run the focused test again**

确认协调器测试通过，且 `generate_pdf_on_error=false` 仍跳过生成。

### Task 3: TUI Notification Regression

**Files:**
- Modify: `src/tui/app.py`
- Modify: `tests/test_tui_app.py`

**Interfaces:**
- 继续使用 `handle_runtime_event` 和 `_notify_task_event`，不改变事件名称。

- [ ] **Step 1: Write the failing test**

扩展 `project_error` 事件测试，验证通知包含传入的 validation failure message，而不是“未知异常”。

- [ ] **Step 2: Run the focused test**

运行 `python -m unittest tests.test_tui_app -v` 中对应测试，确认现有实现失败或缺少覆盖。

- [ ] **Step 3: Implement the minimal TUI change**

让通知在 `error` 为空但存在 `validation_summary` 时构造剩余错误数提示；优先展示 workflow result 提供的明确 `error`。

- [ ] **Step 4: Run focused and full tests**

运行 `python -m unittest tests.test_tui_app -v` 和 `python -m unittest discover tests`。

### Task 4: Diff and Commit

**Files:**
- Verify only task-related files are changed.

- [ ] **Step 1: Inspect diff and status**

运行 `git diff --check` 与 `git status --short`。

- [ ] **Step 2: Commit implementation**

使用英文提交信息：`fix(tui): report validation failures clearly`。
