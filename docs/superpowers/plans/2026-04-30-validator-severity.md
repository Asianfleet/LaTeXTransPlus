# Validator Severity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 `ValidatorAgent` 增加结构化 severity / retryable 分级，让 `CoordinatorAgent` 只重试真正需要重译的 error，同时保留 warning 报告和兼容字段。

**Architecture:** 在 `ValidatorAgent` 内部把 command、placeholder、bracket 校验结果统一转换为 issue dict，再由 report 汇总最高 severity 与 retryable。`CoordinatorAgent` 通过小型 helper 过滤 retryable report，并根据完整 report 生成最终消息。

**Tech Stack:** Python 3.10+、标准库 `unittest`、现有 JSON report 格式、现有 `BaseToolAgent.save_file/read_file`。

---

## File Map

- Modify: `src/agents/tool_agents/validator_agent.py`
  - 负责生成结构化 `issues`、兼容旧字段、保存完整 report。
- Modify: `src/agents/coordinator_agent.py`
  - 负责过滤 retryable report、按 warning/error 汇总最终消息。
- Modify: `tests/test_validator_agent.py`
  - 覆盖 command warning、placeholder error、bracket error、空 report 覆盖。
- Modify: `tests/test_coordinator_messages.py`
  - 覆盖最终消息与 retryable 过滤 helper。
- Optional: `tests/test_translator_retry_prompt.py`
  - 保持现有测试通过；本计划不需要改 translator。

---

### Task 1: Validator Issue 字段测试

**Files:**
- Modify: `tests/test_validator_agent.py`
- Test: `tests/test_validator_agent.py`

- [ ] **Step 1: 添加 command mismatch warning 测试**

在 `ValidatorAgentTests` 中添加：

```python
    def test_validate_command_mismatch_is_warning_not_retryable(self):
        part = {
            "section": "5_3",
            "content": r"Use \textit{confidence} and \textit{uncertainty}.",
            "trans_content": r"使用 \textit{置信度} 和不确定性。",
        }

        report = self.validator._validate(part)

        self.assertEqual(report["severity"], "warning")
        self.assertFalse(report["retryable"])
        self.assertEqual(report["issues"][0]["type"], "command_mismatch")
        self.assertEqual(report["issues"][0]["severity"], "warning")
        self.assertFalse(report["issues"][0]["retryable"])
        self.assertIn("command_error", report)
```

- [ ] **Step 2: 添加 placeholder mismatch error 测试**

在同一个 test class 中添加：

```python
    def test_validate_placeholder_mismatch_is_error_retryable(self):
        part = {
            "section": "1_1",
            "content": r"See <PLACEHOLDER_ENV_1> for details.",
            "trans_content": "详见说明。",
        }

        report = self.validator._validate(part)

        self.assertEqual(report["severity"], "error")
        self.assertTrue(report["retryable"])
        self.assertEqual(report["issues"][0]["type"], "placeholder_mismatch")
        self.assertEqual(report["issues"][0]["severity"], "error")
        self.assertTrue(report["issues"][0]["retryable"])
        self.assertIn("ph_error", report)
```

- [ ] **Step 3: 添加 bracket mismatch error 测试**

在同一个 test class 中添加：

```python
    def test_validate_bracket_mismatch_is_error_retryable(self):
        part = {
            "section": "2_1",
            "content": "A balanced sentence.",
            "trans_content": "一个不平衡的句子）",
        }

        report = self.validator._validate(part)

        self.assertEqual(report["severity"], "error")
        self.assertTrue(report["retryable"])
        self.assertEqual(report["issues"][0]["type"], "bracket_mismatch")
        self.assertEqual(report["issues"][0]["severity"], "error")
        self.assertTrue(report["issues"][0]["retryable"])
        self.assertIn("bracket_error", report)
```

- [ ] **Step 4: 运行测试确认失败**

Run:

```powershell
python -m unittest discover tests -p "test_validator_agent.py"
```

Expected: 新增 3 个测试失败，原因是 report 还没有 `severity`、`retryable`、`issues` 字段。

---

### Task 2: Validator 结构化 Issue 实现

**Files:**
- Modify: `src/agents/tool_agents/validator_agent.py`
- Test: `tests/test_validator_agent.py`

- [ ] **Step 1: 增加 issue helper**

在 `ValidatorAgent` 类内、`_validate` 前添加：

```python
    def _make_issue(self, issue_type: str, message: str, severity: str, retryable: bool) -> Dict[str, Any]:
        return {
            "type": issue_type,
            "severity": severity,
            "retryable": retryable,
            "message": message,
        }

    def _highest_severity(self, issues: List[Dict[str, Any]]) -> str:
        if any(issue["severity"] == "error" for issue in issues):
            return "error"
        return "warning"

    def _is_retryable(self, issues: List[Dict[str, Any]]) -> bool:
        return any(issue.get("retryable", False) for issue in issues)

    def _messages_for_type(self, issues: List[Dict[str, Any]], issue_type: str) -> List[str]:
        return [issue["message"] for issue in issues if issue["type"] == issue_type]
```

- [ ] **Step 2: 改 `_validate_command` 返回 issue 列表**

把 `_validate_command` 的返回类型从字符串改为 list。保留命令计数逻辑，返回：

```python
        issues = []
        for elem, count in src_counter.items():
            aliases = self._equivalent_commands(elem)
            found = sum(trans_counter.get(alias, 0) for alias in aliases)
            if found < count:
                issues.append(
                    self._make_issue(
                        "command_mismatch",
                        f"'{elem}' — expected {count}, found {found}",
                        "warning",
                        False,
                    )
                )
        return issues
```

当 `src_counter == trans_counter` 时返回 `[]`。

- [ ] **Step 3: 改 `_validate_placeholder` 返回 issue 列表**

把原本拼字符串的逻辑改为：

```python
        issues = []
        if missing:
            issues.append(
                self._make_issue(
                    "placeholder_mismatch",
                    f"Missing placeholders: {', '.join(sorted(missing))} translation error or is missing!",
                    "error",
                    True,
                )
            )
        if extra:
            issues.append(
                self._make_issue(
                    "placeholder_mismatch",
                    f"Extra placeholders: {', '.join(sorted(extra))} translation error or is redundant",
                    "error",
                    True,
                )
            )
        return issues
```

- [ ] **Step 4: 改 `_validate_closed_brackets` 返回 issue 列表**

当有新增 bracket 错误时返回一个 issue：

```python
        if errors and not org_errors:
            return [
                self._make_issue(
                    "bracket_mismatch",
                    "\n".join(errors),
                    "error",
                    True,
                )
            ]
        return []
```

- [ ] **Step 5: 改 `_validate` 汇总 issue 并保留兼容字段**

将 `_validate` 的开头改为：

```python
        issues = []
        issues.extend(self._validate_command(part))
        issues.extend(self._validate_placeholder(part))
        issues.extend(self._validate_closed_brackets(part))

        if not issues:
            return None

        error_report = {
            "severity": self._highest_severity(issues),
            "retryable": self._is_retryable(issues),
            "issues": issues,
        }
```

保留现有 `part` / `num_or_ph` 填充逻辑。

在兼容字段部分使用：

```python
            command_messages = self._messages_for_type(issues, "command_mismatch")
            if command_messages:
                error_report["command_error"] = (
                    "LaTeX command translation error or is missing:\n"
                    + "\n".join(command_messages)
                )

            placeholder_messages = self._messages_for_type(issues, "placeholder_mismatch")
            if placeholder_messages:
                error_report["ph_error"] = "\n".join(placeholder_messages)

            bracket_messages = self._messages_for_type(issues, "bracket_mismatch")
            if bracket_messages:
                error_report["bracket_error"] = "Brackets error:\n" + "\n".join(bracket_messages)
```

- [ ] **Step 6: 运行 validator 测试确认通过**

Run:

```powershell
python -m unittest discover tests -p "test_validator_agent.py"
```

Expected: `OK`。

---

### Task 3: errors_report 清理/覆盖测试与实现

**Files:**
- Modify: `tests/test_validator_agent.py`
- Modify: `src/agents/tool_agents/validator_agent.py`
- Test: `tests/test_validator_agent.py`

- [ ] **Step 1: 添加 execute 无 issue 时覆盖空 report 的测试**

在 `tests/test_validator_agent.py` 顶部增加 imports：

```python
import json
import tempfile
from pathlib import Path
```

在 `ValidatorAgentTests` 中添加：

```python
    def test_execute_overwrites_stale_errors_report_when_clean(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_dir = Path(tmp_dir)
            (output_dir / "sections_map.json").write_text(
                json.dumps([
                    {
                        "section": "1_1",
                        "content": "A clean sentence.",
                        "trans_content": "一个干净的句子。",
                    }
                ], ensure_ascii=False),
                encoding="utf-8",
            )
            (output_dir / "captions_map.json").write_text("[]", encoding="utf-8")
            (output_dir / "envs_map.json").write_text("[]", encoding="utf-8")
            (output_dir / "errors_report.json").write_text(
                '[{"severity": "error"}]',
                encoding="utf-8",
            )

            validator = ValidatorAgent(config={}, project_dir="paper", output_dir=str(output_dir))
            result = validator.execute()

            self.assertEqual(result, [])
            saved = json.loads((output_dir / "errors_report.json").read_text(encoding="utf-8"))
            self.assertEqual(saved, [])
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```powershell
python -m unittest discover tests -p "test_validator_agent.py"
```

Expected: 新测试失败，因为当前没有 issue 时不会覆盖旧 `errors_report.json`。

- [ ] **Step 3: 修改 `ValidatorAgent.execute` 始终保存 report**

把：

```python
        if errors_report:
            self.save_file(Path(self.output_dir, "errors_report.json"), "json", errors_report)
```

改为：

```python
        self.save_file(Path(self.output_dir, "errors_report.json"), "json", errors_report)
```

- [ ] **Step 4: 运行 validator 测试确认通过**

Run:

```powershell
python -m unittest discover tests -p "test_validator_agent.py"
```

Expected: `OK`。

---

### Task 4: Coordinator Retry 过滤与消息测试

**Files:**
- Modify: `tests/test_coordinator_messages.py`
- Test: `tests/test_coordinator_messages.py`

- [ ] **Step 1: 添加 helper 导入**

把 import 改成：

```python
from src.agents.coordinator_agent import (
    filter_retryable_reports,
    format_translation_result_message,
    summarize_validation_reports,
)
```

- [ ] **Step 2: 添加 retryable 过滤测试**

添加：

```python
    def test_filter_retryable_reports_keeps_errors_and_legacy_reports(self):
        reports = [
            {"severity": "warning", "retryable": False, "num_or_ph": "warning-only"},
            {"severity": "error", "retryable": True, "num_or_ph": "error"},
            {"num_or_ph": "legacy"},
        ]

        filtered = filter_retryable_reports(reports)

        self.assertEqual([item["num_or_ph"] for item in filtered], ["error", "legacy"])
```

- [ ] **Step 3: 添加 summary 测试**

添加：

```python
    def test_summarize_validation_reports_counts_errors_and_warnings(self):
        summary = summarize_validation_reports([
            {"severity": "warning"},
            {"severity": "error"},
            {"severity": "warning"},
            {},
        ])

        self.assertEqual(summary["warnings"], 2)
        self.assertEqual(summary["errors"], 2)
        self.assertEqual(summary["total"], 4)
```

这里 `{}` 按 legacy error 处理。

- [ ] **Step 4: 更新现有 warning 消息测试**

把 `format_translation_result_message` 调用改为传入 summary：

```python
        message = format_translation_result_message(
            system_name="LaTeXTrans",
            base_name="2510.14901",
            pdf_path=r"outputs\ch_2510.14901\ch_2510.14901.pdf",
            validation_summary={"warnings": 2, "errors": 0, "total": 2},
        )
```

断言：

```python
        self.assertIn("generated with validation warnings", message)
        self.assertIn("remaining validation warnings: 2", message)
```

- [ ] **Step 5: 添加 error 消息测试**

添加：

```python
    def test_result_message_mentions_validation_errors(self):
        message = format_translation_result_message(
            system_name="LaTeXTrans",
            base_name="2510.14901",
            pdf_path=r"outputs\ch_2510.14901\ch_2510.14901.pdf",
            validation_summary={"warnings": 1, "errors": 2, "total": 3},
        )

        self.assertIn("generated with validation errors", message)
        self.assertIn("remaining validation errors: 2", message)
        self.assertIn("warnings: 1", message)
        self.assertIn(r"outputs\ch_2510.14901\errors_report.json", message)
```

- [ ] **Step 6: 运行测试确认失败**

Run:

```powershell
python -m unittest discover tests -p "test_coordinator_messages.py"
```

Expected: import/helper/signature 相关失败。

---

### Task 5: Coordinator Retry 过滤与消息实现

**Files:**
- Modify: `src/agents/coordinator_agent.py`
- Test: `tests/test_coordinator_messages.py`

- [ ] **Step 1: 添加过滤 helper**

在 `format_translation_result_message` 前添加：

```python
def filter_retryable_reports(reports: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [report for report in reports if report.get("retryable", True)]
```

- [ ] **Step 2: 添加 summary helper**

添加：

```python
def summarize_validation_reports(reports: List[Dict[str, Any]]) -> Dict[str, int]:
    summary = {"warnings": 0, "errors": 0, "total": len(reports)}
    for report in reports:
        severity = report.get("severity", "error")
        if severity == "warning":
            summary["warnings"] += 1
        else:
            summary["errors"] += 1
    return summary
```

- [ ] **Step 3: 修改 `format_translation_result_message` 签名与逻辑**

改为：

```python
def format_translation_result_message(
    system_name: str,
    base_name: str,
    pdf_path: str,
    validation_summary: Optional[Dict[str, int]] = None,
) -> str:
    validation_summary = validation_summary or {"warnings": 0, "errors": 0, "total": 0}
    errors_report_path = os.path.join(os.path.dirname(pdf_path), "errors_report.json")
    if validation_summary["errors"]:
        return (
            f"🤖⚠️ {system_name}: PDF generated with validation errors for {base_name}; "
            f"remaining validation errors: {validation_summary['errors']}, "
            f"warnings: {validation_summary['warnings']}. "
            f"PDF: {pdf_path}. Error report: {errors_report_path}."
        )
    if validation_summary["warnings"]:
        return (
            f"🤖⚠️ {system_name}: PDF generated with validation warnings for {base_name}; "
            f"remaining validation warnings: {validation_summary['warnings']}. "
            f"PDF: {pdf_path}. Error report: {errors_report_path}."
        )
    return f"🤖🎉 {system_name}: Successfully translated {base_name} to {pdf_path}."
```

- [ ] **Step 4: 运行 coordinator 测试确认通过**

Run:

```powershell
python -m unittest discover tests -p "test_coordinator_messages.py"
```

Expected: `OK`。

---

### Task 6: Coordinator Workflow 使用 Retryable Reports

**Files:**
- Modify: `src/agents/coordinator_agent.py`
- Test: `tests/test_coordinator_messages.py`
- Test: full suite

- [ ] **Step 1: 修改 workflow 重试变量**

在初次 validator 后添加：

```python
        retryable_reports = filter_retryable_reports(errors_report)
```

把：

```python
        if errors_report:
            translator_agent.trans_mode = 1

        while errors_report and retry_count < MAX_RETRIES:
            translator_agent.errors_report = errors_report
            await translator_agent.execute(error_retry_count=retry_count, Maxtry=MAX_RETRIES)
            errors_report = validator_agent.execute(errors_report)
            retry_count += 1
```

改为：

```python
        if retryable_reports:
            translator_agent.trans_mode = 1

        while retryable_reports and retry_count < MAX_RETRIES:
            translator_agent.errors_report = retryable_reports
            await translator_agent.execute(error_retry_count=retry_count, Maxtry=MAX_RETRIES)
            errors_report = validator_agent.execute(retryable_reports)
            retryable_reports = filter_retryable_reports(errors_report)
            retry_count += 1
```

- [ ] **Step 2: 修改最终 summary 传参**

把：

```python
        validation_error_count = len(errors_report) if errors_report else 0
```

改为：

```python
        validation_summary = summarize_validation_reports(errors_report)
```

把最终消息参数改为：

```python
                    validation_summary=validation_summary,
```

- [ ] **Step 3: 运行 coordinator 测试**

Run:

```powershell
python -m unittest discover tests -p "test_coordinator_messages.py"
```

Expected: `OK`。

- [ ] **Step 4: 运行完整测试**

Run:

```powershell
python -m unittest discover tests
```

Expected: 全部通过。

---

### Task 7: 对 2510.14901 样本做只读回归检查

**Files:**
- No source changes
- Uses: `outputs/ch_2510.14901`

- [ ] **Step 1: 运行当前输出样本 validator 检查**

Run:

```powershell
$env:PYTHONIOENCODING='utf-8'; @'
import json
from pathlib import Path
from src.agents.tool_agents.validator_agent import ValidatorAgent

base = Path('outputs/ch_2510.14901')
validator = ValidatorAgent(config={})
secs = json.loads((base / 'sections_map.json').read_text(encoding='utf-8'))
envs = json.loads((base / 'envs_map.json').read_text(encoding='utf-8'))

for sec in secs:
    if sec.get('section') == '5_3':
        print('5_3:', validator._validate(sec))
for env in envs:
    if env.get('placeholder') == '<PLACEHOLDER_ENV_3>':
        print('ENV_3:', validator._validate(env))
'@ | python -
```

Expected after the previous commit's fixes: both print `None`. If a warning appears for `5_3`, verify it has `severity='warning'` and `retryable=False`.

- [ ] **Step 2: 检查工作区 diff**

Run:

```powershell
git status --short
git diff --stat
```

Expected: only intended source/test files are modified.

---

### Task 8: Final Verification and Commit

**Files:**
- All modified implementation/test files

- [ ] **Step 1: Run full tests**

Run:

```powershell
python -m unittest discover tests
```

Expected: `OK`.

- [ ] **Step 2: Review staged diff**

Run:

```powershell
git diff --stat
git diff -- src\agents\tool_agents\validator_agent.py
git diff -- src\agents\coordinator_agent.py
git diff -- tests\test_validator_agent.py
git diff -- tests\test_coordinator_messages.py
```

Expected: diff matches this plan; no unrelated files.

- [ ] **Step 3: Commit implementation**

Run:

```powershell
git add src\agents\tool_agents\validator_agent.py src\agents\coordinator_agent.py tests\test_validator_agent.py tests\test_coordinator_messages.py
git commit -m "feat(validator): 增加校验严重级别"
```

- [ ] **Step 4: Confirm clean worktree**

Run:

```powershell
git status --short --branch
```

Expected: no unstaged or staged changes.

---

## Self-Review

- Spec coverage: 数据结构、默认规则、validator 行为、coordinator 行为、translator 行为、报告文件和测试计划均有对应任务。
- Placeholder scan: 本计划没有未完成占位步骤或模糊实现要求。
- Type consistency: 使用 `severity`、`retryable`、`issues`、`filter_retryable_reports`、`summarize_validation_reports`、`validation_summary`，命名在测试和实现任务中一致。
