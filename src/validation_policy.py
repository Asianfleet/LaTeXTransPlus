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
