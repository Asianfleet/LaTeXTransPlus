# Validation Retry Policy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 validation issue 分级、重译轮数、错误后 PDF 生成和 CLI 失败状态改为配置驱动。

**Architecture:** 新增轻量 `ValidationPolicy` 作为配置解析边界，`ValidatorAgent` 用它生成 issue severity/retryable，`CoordinatorAgent` 用它控制重译循环与 workflow 结果，`main.py` 和 `src/runtime.py` 汇总项目结果决定最终状态。保持 parser/translator/generator 主体结构不变。

**Tech Stack:** Python 3.10+、TOML config、standard `unittest`、现有 agent 架构。

---

## 文件结构

- Create: `src/validation_policy.py`  
  负责解析 `config["validation"]`，提供 issue policy、retry policy 和失败判断。

- Create: `tests/test_validation_policy.py`  
  覆盖默认严格策略、配置覆盖、非法配置、失败判断。

- Modify: `config/default.toml`  
  增加 `[validation.retry]` 和 `[validation.issues.*]` 默认严格配置。

- Modify: `src/agents/tool_agents/validator_agent.py`  
  使用 `ValidationPolicy` 生成 issue severity/retryable。

- Modify: `tests/test_validator_agent.py`  
  更新 command mismatch 默认行为，并新增旧策略配置覆盖测试。

- Modify: `src/agents/coordinator_agent.py`  
  使用 `ValidationPolicy.max_attempts()`、生成结构化 workflow result、按 policy 决定是否跳过 generator 和是否标失败。

- Modify: `tests/test_coordinator_messages.py`  
  覆盖新的最终消息与结果判断 helper。

- Modify: `main.py`  
  汇总每个 project 的 workflow result，处理完所有项目后按失败状态 `sys.exit(1)`。

- Modify: `src/runtime.py`  
  在 `run_projects()` 中同步 project result 语义，失败项目进入 `failed_projects`，但不提前中断。

- Create: `tests/test_runtime_project_results.py`  
  轻量测试多项目汇总和失败不提前中断的 helper 行为。

---

### Task 1: ValidationPolicy 与默认配置

**Files:**
- Create: `src/validation_policy.py`
- Create: `tests/test_validation_policy.py`
- Modify: `config/default.toml`

- [ ] **Step 1: 写 failing tests**

Create `tests/test_validation_policy.py`:

```python
import unittest

from src.validation_policy import ValidationPolicy


class ValidationPolicyTests(unittest.TestCase):
    def test_default_policy_is_strict(self):
        policy = ValidationPolicy.from_config({})

        self.assertEqual(policy.issue_severity("command_mismatch"), "error")
        self.assertTrue(policy.issue_retryable("command_mismatch"))
        self.assertEqual(policy.issue_severity("placeholder_mismatch"), "error")
        self.assertTrue(policy.issue_retryable("placeholder_mismatch"))
        self.assertEqual(policy.issue_severity("bracket_mismatch"), "error")
        self.assertTrue(policy.issue_retryable("bracket_mismatch"))
        self.assertEqual(policy.max_attempts(), 3)
        self.assertTrue(policy.generate_pdf_on_error())
        self.assertTrue(policy.fail_on_error())

    def test_issue_policy_can_be_overridden(self):
        policy = ValidationPolicy.from_config({
            "validation": {
                "issues": {
                    "command_mismatch": {
                        "severity": "warning",
                        "retryable": False,
                    }
                }
            }
        })

        self.assertEqual(policy.issue_severity("command_mismatch"), "warning")
        self.assertFalse(policy.issue_retryable("command_mismatch"))
        self.assertEqual(policy.issue_severity("placeholder_mismatch"), "error")
        self.assertTrue(policy.issue_retryable("placeholder_mismatch"))

    def test_retry_policy_can_be_overridden(self):
        policy = ValidationPolicy.from_config({
            "validation": {
                "retry": {
                    "max_attempts": 1,
                    "generate_pdf_on_error": False,
                    "fail_on_error": False,
                }
            }
        })

        self.assertEqual(policy.max_attempts(), 1)
        self.assertFalse(policy.generate_pdf_on_error())
        self.assertFalse(policy.fail_on_error())

    def test_unknown_issue_type_defaults_to_strict(self):
        policy = ValidationPolicy.from_config({})

        self.assertEqual(policy.issue_severity("new_issue"), "error")
        self.assertTrue(policy.issue_retryable("new_issue"))

    def test_invalid_severity_raises_value_error(self):
        with self.assertRaisesRegex(ValueError, "Invalid validation severity"):
            ValidationPolicy.from_config({
                "validation": {
                    "issues": {
                        "command_mismatch": {
                            "severity": "fatal",
                            "retryable": True,
                        }
                    }
                }
            })

    def test_negative_max_attempts_raises_value_error(self):
        with self.assertRaisesRegex(ValueError, "max_attempts"):
            ValidationPolicy.from_config({
                "validation": {
                    "retry": {
                        "max_attempts": -1,
                    }
                }
            })

    def test_should_fail_requires_error_and_fail_on_error(self):
        strict_policy = ValidationPolicy.from_config({})
        lenient_policy = ValidationPolicy.from_config({
            "validation": {
                "retry": {
                    "fail_on_error": False,
                }
            }
        })

        self.assertTrue(strict_policy.should_fail({"errors": 1, "warnings": 0, "total": 1}))
        self.assertFalse(strict_policy.should_fail({"errors": 0, "warnings": 1, "total": 1}))
        self.assertFalse(lenient_policy.should_fail({"errors": 1, "warnings": 0, "total": 1}))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```powershell
python -m unittest tests.test_validation_policy
```

Expected: FAIL，错误包含 `ModuleNotFoundError: No module named 'src.validation_policy'`。

- [ ] **Step 3: 实现 ValidationPolicy**

Create `src/validation_policy.py`:

```python
from dataclasses import dataclass
from typing import Any, Dict


VALID_SEVERITIES = {"warning", "error"}


DEFAULT_RETRY_POLICY = {
    "max_attempts": 3,
    "generate_pdf_on_error": True,
    "fail_on_error": True,
}


DEFAULT_ISSUE_POLICIES = {
    "command_mismatch": {"severity": "error", "retryable": True},
    "placeholder_mismatch": {"severity": "error", "retryable": True},
    "bracket_mismatch": {"severity": "error", "retryable": True},
}


@dataclass(frozen=True)
class ValidationPolicy:
    retry_policy: Dict[str, Any]
    issue_policies: Dict[str, Dict[str, Any]]

    @classmethod
    def from_config(cls, config: Dict[str, Any]) -> "ValidationPolicy":
        validation_config = config.get("validation", {}) or {}
        retry_config = validation_config.get("retry", {}) or {}
        issues_config = validation_config.get("issues", {}) or {}

        retry_policy = DEFAULT_RETRY_POLICY.copy()
        retry_policy.update(retry_config)
        cls._validate_retry_policy(retry_policy)

        issue_policies = {
            issue_type: policy.copy()
            for issue_type, policy in DEFAULT_ISSUE_POLICIES.items()
        }
        for issue_type, issue_config in issues_config.items():
            merged = {"severity": "error", "retryable": True}
            merged.update(issue_policies.get(issue_type, {}))
            merged.update(issue_config or {})
            cls._validate_issue_policy(issue_type, merged)
            issue_policies[issue_type] = merged

        for issue_type, issue_policy in issue_policies.items():
            cls._validate_issue_policy(issue_type, issue_policy)

        return cls(retry_policy=retry_policy, issue_policies=issue_policies)

    @staticmethod
    def _validate_retry_policy(retry_policy: Dict[str, Any]) -> None:
        max_attempts = retry_policy.get("max_attempts", 3)
        if not isinstance(max_attempts, int) or max_attempts < 0:
            raise ValueError("validation.retry.max_attempts must be a non-negative integer")

    @staticmethod
    def _validate_issue_policy(issue_type: str, issue_policy: Dict[str, Any]) -> None:
        severity = issue_policy.get("severity")
        if severity not in VALID_SEVERITIES:
            raise ValueError(
                f"Invalid validation severity for {issue_type}: {severity!r}. "
                "Expected 'warning' or 'error'."
            )

    def issue_severity(self, issue_type: str) -> str:
        return self.issue_policies.get(issue_type, {"severity": "error"})["severity"]

    def issue_retryable(self, issue_type: str) -> bool:
        return bool(self.issue_policies.get(issue_type, {"retryable": True})["retryable"])

    def max_attempts(self) -> int:
        return int(self.retry_policy["max_attempts"])

    def generate_pdf_on_error(self) -> bool:
        return bool(self.retry_policy["generate_pdf_on_error"])

    def fail_on_error(self) -> bool:
        return bool(self.retry_policy["fail_on_error"])

    def should_fail(self, validation_summary: Dict[str, int]) -> bool:
        return self.fail_on_error() and validation_summary.get("errors", 0) > 0
```

- [ ] **Step 4: 增加默认 TOML 配置**

Modify `config/default.toml` after `user_term = ""`:

```toml
[validation.retry]
max_attempts = 3
generate_pdf_on_error = true
fail_on_error = true

[validation.issues.command_mismatch]
severity = "error"
retryable = true

[validation.issues.placeholder_mismatch]
severity = "error"
retryable = true

[validation.issues.bracket_mismatch]
severity = "error"
retryable = true
```

- [ ] **Step 5: 运行测试确认通过**

Run:

```powershell
python -m unittest tests.test_validation_policy
```

Expected: PASS。

- [ ] **Step 6: Commit**

Run:

```powershell
git add src/validation_policy.py tests/test_validation_policy.py config/default.toml
git commit -m "feat(validator): 增加 validation policy 配置"
```

---

### Task 2: ValidatorAgent 接入 ValidationPolicy

**Files:**
- Modify: `src/agents/tool_agents/validator_agent.py`
- Modify: `tests/test_validator_agent.py`

- [ ] **Step 1: 更新 failing tests**

Modify `tests/test_validator_agent.py`.

Change `test_validate_command_mismatch_is_warning_not_retryable` to:

```python
    def test_validate_command_mismatch_uses_strict_default_policy(self):
        part = {
            "section": "5_3",
            "content": r"Use \textit{confidence} and \textit{uncertainty}.",
            "trans_content": r"使用 \textit{置信度} 和不确定性。",
        }

        report = self.validator._validate(part)

        self.assertEqual(report["severity"], "error")
        self.assertTrue(report["retryable"])
        self.assertEqual(report["issues"][0]["type"], "command_mismatch")
        self.assertEqual(report["issues"][0]["severity"], "error")
        self.assertTrue(report["issues"][0]["retryable"])
        self.assertIn("command_error", report)
```

Add this test:

```python
    def test_validate_command_mismatch_can_be_configured_as_warning(self):
        validator = ValidatorAgent(config={
            "validation": {
                "issues": {
                    "command_mismatch": {
                        "severity": "warning",
                        "retryable": False,
                    }
                }
            }
        })
        part = {
            "section": "5_3",
            "content": r"Use \textit{confidence} and \textit{uncertainty}.",
            "trans_content": r"使用 \textit{置信度} 和不确定性。",
        }

        report = validator._validate(part)

        self.assertEqual(report["severity"], "warning")
        self.assertFalse(report["retryable"])
        self.assertEqual(report["issues"][0]["severity"], "warning")
        self.assertFalse(report["issues"][0]["retryable"])
```

- [ ] **Step 2: 运行 validator 测试确认失败**

Run:

```powershell
python -m unittest tests.test_validator_agent
```

Expected: FAIL，默认 command mismatch 仍是 warning/non-retryable。

- [ ] **Step 3: 接入 policy**

Modify imports in `src/agents/tool_agents/validator_agent.py`:

```python
from src.validation_policy import ValidationPolicy
```

Modify `__init__`:

```python
        self.policy = ValidationPolicy.from_config(config or {})
```

Add helper method inside `ValidatorAgent`:

```python
    def _make_policy_issue(self, issue_type: str, message: str) -> Dict[str, Any]:
        return self._make_issue(
            issue_type=issue_type,
            message=message,
            severity=self.policy.issue_severity(issue_type),
            retryable=self.policy.issue_retryable(issue_type),
        )
```

Replace command mismatch issue creation:

```python
                issues.append(self._make_policy_issue(
                    issue_type="command_mismatch",
                    message=f"'{elem}' — expected {count}, found {found}",
                ))
```

Replace missing placeholder issue creation:

```python
            issues.append(self._make_policy_issue(
                issue_type="placeholder_mismatch",
                message=f"Missing placeholders: {', '.join(sorted(missing))} translation error or is missing!",
            ))
```

Replace extra placeholder issue creation:

```python
            issues.append(self._make_policy_issue(
                issue_type="placeholder_mismatch",
                message=f"Extra placeholders: {', '.join(sorted(extra))} translation error or is redundant",
            ))
```

Replace bracket mismatch issue creation:

```python
            return [self._make_policy_issue(
                issue_type="bracket_mismatch",
                message="\n".join(errors),
            )]
```

- [ ] **Step 4: 运行 validator 测试确认通过**

Run:

```powershell
python -m unittest tests.test_validator_agent
```

Expected: PASS。

- [ ] **Step 5: Commit**

Run:

```powershell
git add src/agents/tool_agents/validator_agent.py tests/test_validator_agent.py
git commit -m "feat(validator): 按 policy 生成校验报告"
```

---

### Task 3: CoordinatorAgent 使用 policy 控制重译与结果

**Files:**
- Modify: `src/agents/coordinator_agent.py`
- Modify: `tests/test_coordinator_messages.py`

- [ ] **Step 1: 写 failing tests for message/result helpers**

Modify `tests/test_coordinator_messages.py`.

Add imports:

```python
    should_generate_pdf_after_validation,
    build_workflow_result,
```

Add tests:

```python
    def test_result_message_mentions_validation_failed_with_pdf(self):
        message = format_translation_result_message(
            system_name="LaTeXTrans",
            base_name="2510.14901",
            pdf_path=r"outputs\ch_2510.14901\ch_2510.14901.pdf",
            validation_summary={"warnings": 1, "errors": 2, "total": 3},
            validation_failed=True,
        )

        self.assertIn("PDF generated but validation failed", message)
        self.assertIn("remaining validation errors: 2", message)
        self.assertIn("warnings: 1", message)

    def test_should_generate_pdf_after_validation_respects_policy(self):
        self.assertTrue(should_generate_pdf_after_validation(
            validation_summary={"warnings": 0, "errors": 1, "total": 1},
            generate_pdf_on_error=True,
        ))
        self.assertFalse(should_generate_pdf_after_validation(
            validation_summary={"warnings": 0, "errors": 1, "total": 1},
            generate_pdf_on_error=False,
        ))
        self.assertTrue(should_generate_pdf_after_validation(
            validation_summary={"warnings": 2, "errors": 0, "total": 2},
            generate_pdf_on_error=False,
        ))

    def test_build_workflow_result_marks_validation_error_failed(self):
        result = build_workflow_result(
            project_name="2510.14901",
            pdf_path=r"outputs\ch_2510.14901\ch_2510.14901.pdf",
            errors_report_path=r"outputs\ch_2510.14901\errors_report.json",
            validation_summary={"warnings": 0, "errors": 1, "total": 1},
            validation_failed=True,
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["project_name"], "2510.14901")
        self.assertTrue(result["pdf_path"].endswith("ch_2510.14901.pdf"))
```

Update existing `test_result_message_mentions_validation_errors` to pass `validation_failed=False` if the function signature requires it. Keep assertions for legacy wording only if `validation_failed=False`.

- [ ] **Step 2: 运行 coordinator tests 确认失败**

Run:

```powershell
python -m unittest tests.test_coordinator_messages
```

Expected: FAIL，helper 不存在或 `format_translation_result_message()` 不支持 `validation_failed`。

- [ ] **Step 3: 实现 helper 与 message 扩展**

Modify imports in `src/agents/coordinator_agent.py`:

```python
from src.validation_policy import ValidationPolicy
```

Add helper functions near existing summary/message helpers:

```python
def should_generate_pdf_after_validation(
    validation_summary: Dict[str, int],
    generate_pdf_on_error: bool,
) -> bool:
    return validation_summary.get("errors", 0) == 0 or generate_pdf_on_error


def build_workflow_result(
    project_name: str,
    pdf_path: Optional[str],
    errors_report_path: str,
    validation_summary: Dict[str, int],
    validation_failed: bool,
    error: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "project_name": project_name,
        "ok": not validation_failed and error is None,
        "pdf_path": pdf_path,
        "errors_report_path": errors_report_path,
        "validation_summary": validation_summary,
        "error": error,
    }
```

Change `format_translation_result_message()` signature:

```python
def format_translation_result_message(
    system_name: str,
    base_name: str,
    pdf_path: str,
    validation_summary: Optional[Dict[str, int]] = None,
    validation_failed: bool = False,
) -> str:
```

Add this branch before the existing `if validation_summary["errors"]` branch:

```python
    if validation_failed and validation_summary["errors"]:
        return (
            f"🤖❌ {system_name}: PDF generated but validation failed for {base_name}; "
            f"remaining validation errors: {validation_summary['errors']}, "
            f"warnings: {validation_summary['warnings']}. "
            f"PDF: {pdf_path}. Error report: {errors_report_path}."
        )
```

- [ ] **Step 4: Wire policy into workflow**

In `CoordinatorAgent.__init__`, add:

```python
        self.validation_policy = ValidationPolicy.from_config(config)
```

In `workflow_latextrans_async()`, replace:

```python
        MAX_RETRIES = 3
```

with:

```python
        max_retries = self.validation_policy.max_attempts()
```

Replace loop condition and execute call:

```python
        while retryable_reports and retry_count < max_retries:
            translator_agent.errors_report = retryable_reports
            await translator_agent.execute(error_retry_count=retry_count, Maxtry=max_retries)
```

After `validation_summary`, add:

```python
        validation_failed = self.validation_policy.should_fail(validation_summary)
        errors_report_path = os.path.join(transed_project_dir, "errors_report.json")
        if not should_generate_pdf_after_validation(
            validation_summary=validation_summary,
            generate_pdf_on_error=self.validation_policy.generate_pdf_on_error(),
        ):
            print(
                f"🤖❌ {self.name}: Validation failed for {base_name}; "
                f"PDF generation skipped. Error report: {errors_report_path}."
            )
            return build_workflow_result(
                project_name=base_name,
                pdf_path=None,
                errors_report_path=errors_report_path,
                validation_summary=validation_summary,
                validation_failed=True,
            )
```

When generator raises, replace bare `return` with:

```python
            return build_workflow_result(
                project_name=base_name,
                pdf_path=None,
                errors_report_path=errors_report_path,
                validation_summary=validation_summary,
                validation_failed=True,
                error=str(e),
            )
```

When `PDF_file_path` succeeds and after moving PDF, change print call:

```python
            print(
                format_translation_result_message(
                    system_name=self.name,
                    base_name=os.path.basename(self.project_dir),
                    pdf_path=new_PDF_path,
                    validation_summary=validation_summary,
                    validation_failed=validation_failed,
                )
            )
            return build_workflow_result(
                project_name=base_name,
                pdf_path=new_PDF_path,
                errors_report_path=errors_report_path,
                validation_summary=validation_summary,
                validation_failed=validation_failed,
            )
```

When `PDF_file_path` is false, return failed result:

```python
        return build_workflow_result(
            project_name=base_name,
            pdf_path=None,
            errors_report_path=errors_report_path,
            validation_summary=validation_summary,
            validation_failed=True,
            error="PDF generation returned no output path",
        )
```

Modify `workflow_latextrans()` to return the async result:

```python
            return self.loop.run_until_complete(self.workflow_latextrans_async())
```

- [ ] **Step 5: 运行 coordinator tests**

Run:

```powershell
python -m unittest tests.test_coordinator_messages
```

Expected: PASS。

- [ ] **Step 6: Commit**

Run:

```powershell
git add src/agents/coordinator_agent.py tests/test_coordinator_messages.py
git commit -m "feat(coordinator): 返回 validation workflow 结果"
```

---

### Task 4: CLI 与 runtime 汇总失败状态

**Files:**
- Modify: `main.py`
- Modify: `src/runtime.py`
- Create: `tests/test_runtime_project_results.py`

- [ ] **Step 1: 写 failing tests for result classification**

Create `tests/test_runtime_project_results.py`:

```python
import unittest

from src.runtime import classify_project_result, should_exit_with_failure


class RuntimeProjectResultTests(unittest.TestCase):
    def test_classify_project_result_completed(self):
        result = classify_project_result(
            index=1,
            total=2,
            project_name="paper",
            project_dir=r"D:\paper",
            workflow_result={
                "ok": True,
                "pdf_path": r"outputs\ch_paper\ch_paper.pdf",
                "validation_summary": {"warnings": 0, "errors": 0, "total": 0},
            },
        )

        self.assertEqual(result["type"], "completed")
        self.assertTrue(result["ok"])

    def test_classify_project_result_failed(self):
        result = classify_project_result(
            index=1,
            total=2,
            project_name="paper",
            project_dir=r"D:\paper",
            workflow_result={
                "ok": False,
                "pdf_path": r"outputs\ch_paper\ch_paper.pdf",
                "validation_summary": {"warnings": 0, "errors": 1, "total": 1},
            },
        )

        self.assertEqual(result["type"], "failed")
        self.assertFalse(result["ok"])
        self.assertEqual(result["validation_summary"]["errors"], 1)

    def test_should_exit_with_failure_when_any_project_failed(self):
        self.assertTrue(should_exit_with_failure({
            "completed_projects": [{"project_name": "a"}],
            "failed_projects": [{"project_name": "b"}],
        }))
        self.assertFalse(should_exit_with_failure({
            "completed_projects": [{"project_name": "a"}],
            "failed_projects": [],
        }))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行 tests 确认失败**

Run:

```powershell
python -m unittest tests.test_runtime_project_results
```

Expected: FAIL，`classify_project_result` 和 `should_exit_with_failure` 不存在。

- [ ] **Step 3: 实现 runtime helpers**

Add to `src/runtime.py` before `run_projects()`:

```python
def classify_project_result(
    index: int,
    total: int,
    project_name: str,
    project_dir: str,
    workflow_result: Dict[str, Any],
) -> Dict[str, Any]:
    status_type = "completed" if workflow_result.get("ok", False) else "failed"
    return {
        "type": status_type,
        "ok": workflow_result.get("ok", False),
        "index": index,
        "total": total,
        "project_name": project_name,
        "project_dir": project_dir,
        "pdf_path": workflow_result.get("pdf_path"),
        "errors_report_path": workflow_result.get("errors_report_path"),
        "validation_summary": workflow_result.get(
            "validation_summary",
            {"warnings": 0, "errors": 0, "total": 0},
        ),
        "error": workflow_result.get("error"),
    }


def should_exit_with_failure(project_status: Dict[str, List[Dict[str, Any]]]) -> bool:
    return bool(project_status.get("failed_projects"))
```

- [ ] **Step 4: Wire runtime run_projects**

In `src/runtime.py`, replace:

```python
            latex_trans.workflow_latextrans()
```

with:

```python
            workflow_result = latex_trans.workflow_latextrans()
            project_result = classify_project_result(
                index=idx,
                total=total_projects,
                project_name=project_name,
                project_dir=project_dir,
                workflow_result=workflow_result,
            )
```

After try block, replace unconditional completed append with classification:

```python
        if project_result["ok"]:
            completed_projects.append(project_result)
            event_type = "project_complete"
        else:
            failed_projects.append(project_result)
            event_type = "project_error"

        if event_callback:
            event_callback(
                {
                    "type": event_type,
                    "index": idx,
                    "total": total_projects,
                    "project_name": project_name,
                    "project_dir": project_dir,
                    "pdf_path": project_result.get("pdf_path"),
                    "errors_report_path": project_result.get("errors_report_path"),
                    "validation_summary": project_result.get("validation_summary"),
                    "error": project_result.get("error"),
                }
            )
```

Keep the existing `except Exception as e` branch, but ensure it appends a dict with `"ok": False`.

- [ ] **Step 5: Wire main.py exit code**

In `main.py`, add import:

```python
from src.runtime import should_exit_with_failure
```

Before the project loop, add:

```python
    project_status = {
        "completed_projects": [],
        "failed_projects": [],
    }
```

Inside the loop, replace:

```python
                latex_trans.workflow_latextrans()
```

with:

```python
                workflow_result = latex_trans.workflow_latextrans()
                if workflow_result.get("ok", False):
                    project_status["completed_projects"].append(workflow_result)
                else:
                    project_status["failed_projects"].append(workflow_result)
```

In the `except Exception as e` branch, add:

```python
                project_status["failed_projects"].append({
                    "project_name": os.path.basename(project_dir),
                    "project_dir": project_dir,
                    "ok": False,
                    "error": str(e),
                })
```

After the loop, add:

```python
    if should_exit_with_failure(project_status):
        sys.exit(1)
```

- [ ] **Step 6: 运行 runtime tests**

Run:

```powershell
python -m unittest tests.test_runtime_project_results
```

Expected: PASS。

- [ ] **Step 7: Commit**

Run:

```powershell
git add main.py src/runtime.py tests/test_runtime_project_results.py
git commit -m "feat(cli): 汇总 validation 失败退出码"
```

---

### Task 5: Full Verification

**Files:**
- Verify all modified files

- [ ] **Step 1: 运行完整单测**

Run:

```powershell
python -m unittest discover tests
```

Expected: PASS。

- [ ] **Step 2: 检查默认配置解析**

Run:

```powershell
python -c "import toml; from src.validation_policy import ValidationPolicy; c=toml.load('config/default.toml'); p=ValidationPolicy.from_config(c); print(p.issue_severity('command_mismatch'), p.issue_retryable('command_mismatch'), p.max_attempts())"
```

Expected output:

```text
error True 3
```

- [ ] **Step 3: 检查 git diff**

Run:

```powershell
git status --short
git diff --stat
```

Expected: only task-related files are modified if not yet committed; after commits, working tree is clean.

- [ ] **Step 4: Final commit if verification changed files**

If verification caused no file changes, skip this step. If a formatting or test fix was needed, commit it:

```powershell
git add <changed task-related files>
git commit -m "test(validator): 验证可配置重译策略"
```
