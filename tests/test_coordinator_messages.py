import os
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock, patch

from src.agents import coordinator_agent
from src.agents.coordinator_agent import (
    build_review_required_result,
    build_workflow_result,
    CoordinatorAgent,
    filter_retryable_reports,
    format_translation_result_message,
    merge_validation_reports,
    should_run_terminology_scan,
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

    def test_should_run_terminology_scan_respects_config(self):
        self.assertTrue(should_run_terminology_scan({"terminology": {"enabled": True}}))
        self.assertTrue(should_run_terminology_scan({}))
        self.assertFalse(should_run_terminology_scan({"terminology": {"enabled": False}}))

    def test_build_review_required_result_marks_workflow_not_ok(self):
        result = build_review_required_result(
            project_name="paper",
            project_terms_path=r"outputs\ch_paper\project_terms.csv",
            project_terms_decisions_path=r"outputs\ch_paper\project_terms_decisions.json",
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "needs_term_review")
        self.assertIn("project_terms.csv", result["project_terms_path"])
        self.assertIn("project_terms_decisions.json", result["project_terms_decisions_path"])

    def test_clear_translated_content_preserves_nontranslated_sections(self):
        from src.agents.coordinator_agent import clear_translated_content

        sections = [
            {"section": "-1", "content": "preamble", "trans_content": "preamble"},
            {"section": "0", "content": "front", "trans_content": "front"},
            {"section": "1", "content": "body", "trans_content": "旧译文"},
        ]
        captions = [{"content": "caption", "trans_content": "旧图题"}]
        envs = [
            {"content": "math", "trans_content": "", "need_trans": False},
            {"content": "env", "trans_content": "旧环境", "need_trans": True},
        ]

        clear_translated_content(sections, captions, envs)

        self.assertEqual(sections[0]["trans_content"], "preamble")
        self.assertEqual(sections[1]["trans_content"], "front")
        self.assertEqual(sections[2]["trans_content"], "")
        self.assertEqual(captions[0]["trans_content"], "")
        self.assertEqual(envs[0]["trans_content"], "")
        self.assertEqual(envs[1]["trans_content"], "")

    def test_workflow_pauses_after_terminology_review_and_skips_translation(self):
        events = []

        parser = Mock()
        parser.execute.side_effect = lambda: events.append("parser")
        terminology = Mock()
        terminology.execute.side_effect = lambda: events.append("terminology") or {
            "project_terms_path": r"outputs\ch_paper\project_terms.csv",
            "project_terms_decisions_path": r"outputs\ch_paper\project_terms_decisions.json",
        }
        translator = Mock()
        translator.execute = AsyncMock(side_effect=lambda *args, **kwargs: events.append("translator"))

        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = os.path.join(tmpdir, "paper")
            output_dir = os.path.join(tmpdir, "outputs")
            config = {
                "target_language": "ch",
                "terminology": {
                    "enabled": True,
                    "review_before_translate": True,
                },
            }
            agent = CoordinatorAgent(config=config, project_dir=project_dir, output_dir=output_dir)
            try:
                with patch.object(coordinator_agent, "ParserAgent", return_value=parser), \
                        patch.object(coordinator_agent, "TerminologyAgent", return_value=terminology), \
                        patch.object(coordinator_agent, "TranslatorAgent", return_value=translator), \
                        patch("builtins.print"):
                    result = agent.workflow_latextrans()
            finally:
                if not agent.loop.is_closed():
                    agent.loop.close()

        self.assertEqual(events, ["parser", "terminology"])
        self.assertEqual(result["status"], "needs_term_review")
        translator.execute.assert_not_called()

    def test_workflow_skips_terminology_when_helper_disables_scan(self):
        events = []

        parser = Mock()
        parser.execute.side_effect = lambda: events.append("parser")
        terminology = Mock()
        terminology.execute.side_effect = lambda: events.append("terminology")
        translator = Mock()
        translator.execute = AsyncMock(side_effect=lambda *args, **kwargs: events.append("translator"))
        validator = Mock()
        validator.execute.return_value = []
        generator = Mock()
        generator.execute.return_value = r"build\paper.pdf"

        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = os.path.join(tmpdir, "paper")
            output_dir = os.path.join(tmpdir, "outputs")
            config = {
                "target_language": "ch",
                "terminology": {
                    "enabled": False,
                    "review_before_translate": True,
                },
            }
            agent = CoordinatorAgent(config=config, project_dir=project_dir, output_dir=output_dir)
            try:
                with patch.object(coordinator_agent, "ParserAgent", return_value=parser), \
                        patch.object(coordinator_agent, "TerminologyAgent", return_value=terminology), \
                        patch.object(coordinator_agent, "TranslatorAgent", return_value=translator), \
                        patch.object(coordinator_agent, "ValidatorAgent", return_value=validator), \
                        patch.object(coordinator_agent, "GeneratorAgent", return_value=generator), \
                        patch.object(coordinator_agent, "shutil") as shutil_mock, \
                        patch("builtins.print"):
                    result = agent.workflow_latextrans()
            finally:
                if not agent.loop.is_closed():
                    agent.loop.close()

        self.assertEqual(events, ["parser", "translator"])
        terminology.execute.assert_not_called()
        translator.execute.assert_awaited_once()
        shutil_mock.move.assert_called_once()
        self.assertTrue(result["ok"])

    def test_workflow_uses_should_run_terminology_scan_gate(self):
        events = []

        parser = Mock()
        parser.execute.side_effect = lambda: events.append("parser")
        terminology = Mock()
        terminology.execute.side_effect = lambda: events.append("terminology") or {
            "project_terms_path": r"outputs\ch_paper\project_terms.csv",
            "project_terms_decisions_path": r"outputs\ch_paper\project_terms_decisions.json",
        }
        translator = Mock()
        translator.execute = AsyncMock(side_effect=lambda *args, **kwargs: events.append("translator"))
        validator = Mock()
        validator.execute.return_value = []
        generator = Mock()
        generator.execute.return_value = r"build\paper.pdf"

        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = os.path.join(tmpdir, "paper")
            output_dir = os.path.join(tmpdir, "outputs")
            config = {
                "target_language": "ch",
                "terminology": {
                    "enabled": True,
                    "review_before_translate": True,
                },
            }
            agent = CoordinatorAgent(config=config, project_dir=project_dir, output_dir=output_dir)
            try:
                with patch.object(coordinator_agent, "should_run_terminology_scan", return_value=False), \
                        patch.object(coordinator_agent, "ParserAgent", return_value=parser), \
                        patch.object(coordinator_agent, "TerminologyAgent", return_value=terminology), \
                        patch.object(coordinator_agent, "TranslatorAgent", return_value=translator), \
                        patch.object(coordinator_agent, "ValidatorAgent", return_value=validator), \
                        patch.object(coordinator_agent, "GeneratorAgent", return_value=generator), \
                        patch.object(coordinator_agent, "shutil"), \
                        patch("builtins.print"):
                    result = agent.workflow_latextrans()
            finally:
                if not agent.loop.is_closed():
                    agent.loop.close()

        self.assertEqual(events, ["parser", "translator"])
        terminology.execute.assert_not_called()
        self.assertTrue(result["ok"])


if __name__ == "__main__":
    unittest.main()
