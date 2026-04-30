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
