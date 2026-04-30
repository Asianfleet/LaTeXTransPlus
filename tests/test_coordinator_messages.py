import unittest

from src.agents.coordinator_agent import (
    build_workflow_result,
    filter_retryable_reports,
    format_translation_result_message,
    merge_validation_reports,
    should_generate_pdf_after_validation,
    summarize_validation_reports,
)


class CoordinatorMessageTests(unittest.TestCase):
    def test_filter_retryable_reports_keeps_errors_and_legacy_reports(self):
        reports = [
            {"severity": "warning", "retryable": False, "num_or_ph": "warning-only"},
            {"severity": "error", "retryable": True, "num_or_ph": "error"},
            {"num_or_ph": "legacy"},
        ]

        filtered = filter_retryable_reports(reports)

        self.assertEqual([item["num_or_ph"] for item in filtered], ["error", "legacy"])

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

    def test_merge_validation_reports_keeps_non_retryable_warnings_after_retry(self):
        warning = {
            "part": "sec",
            "num_or_ph": "5_3",
            "severity": "warning",
            "retryable": False,
        }
        retryable_error = {
            "part": "sec",
            "num_or_ph": "1_1",
            "severity": "error",
            "retryable": True,
        }

        merged = merge_validation_reports(
            previous_reports=[warning, retryable_error],
            retryable_reports=[retryable_error],
            retry_results=[],
        )

        self.assertEqual(merged, [warning])

    def test_success_message_mentions_validation_warnings(self):
        message = format_translation_result_message(
            system_name="LaTeXTrans",
            base_name="2510.14901",
            pdf_path=r"outputs\ch_2510.14901\ch_2510.14901.pdf",
            validation_summary={"warnings": 2, "errors": 0, "total": 2},
        )

        self.assertIn("generated with validation warnings", message)
        self.assertIn("remaining validation warnings: 2", message)
        self.assertIn(r"outputs\ch_2510.14901\errors_report.json", message)

    def test_result_message_mentions_validation_errors(self):
        message = format_translation_result_message(
            system_name="LaTeXTrans",
            base_name="2510.14901",
            pdf_path=r"outputs\ch_2510.14901\ch_2510.14901.pdf",
            validation_summary={"warnings": 1, "errors": 2, "total": 3},
            validation_failed=False,
        )

        self.assertIn("generated with validation errors", message)
        self.assertIn("remaining validation errors: 2", message)
        self.assertIn("warnings: 1", message)
        self.assertIn(r"outputs\ch_2510.14901\errors_report.json", message)

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

    def test_build_workflow_result_respects_lenient_validation_policy(self):
        result = build_workflow_result(
            project_name="2510.14901",
            pdf_path=None,
            errors_report_path=r"outputs\ch_2510.14901\errors_report.json",
            validation_summary={"warnings": 0, "errors": 1, "total": 1},
            validation_failed=False,
        )

        self.assertTrue(result["ok"])
        self.assertIsNone(result["pdf_path"])


if __name__ == "__main__":
    unittest.main()
