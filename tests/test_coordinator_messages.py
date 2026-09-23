import os
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from src.agents import coordinator_agent
from src.agents.coordinator_agent import (
    INITIAL_ERRORS_REPORT_FILENAME,
    build_review_required_result,
    build_unsupported_source_result,
    build_workflow_result,
    CoordinatorAgent,
    filter_retryable_reports,
    format_translation_result_message,
    is_pdf_only_latex_source,
    merge_validation_reports,
    save_initial_validation_report,
    should_run_terminology_scan,
    should_generate_pdf_after_validation,
    summarize_validation_reports,
)


class CoordinatorMessageTests(unittest.TestCase):
    def test_coordinator_error_log_uses_project_log_callback(self):
        events = []
        agent = CoordinatorAgent(
            config={"_project_log_callback": events.append},
            project_dir=r"D:\tex source\paper",
            output_dir=r"D:\repo\outputs",
        )
        try:
            agent._log("Generation failed (ValueError): broken document", level="error")
        finally:
            agent.loop.close()

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["agent_name"], "CoordinatorAgent")
        self.assertEqual(events[0]["level"], "error")
        self.assertIn("ValueError", events[0]["line"])
        self.assertIn("broken document", events[0]["line"])

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

    def test_build_workflow_result_includes_validation_failure_details(self):
        report_path = r"outputs\ch_2510.14901\errors_report.json"
        result = build_workflow_result(
            project_name="2510.14901",
            pdf_path=None,
            errors_report_path=report_path,
            validation_summary={"warnings": 1, "errors": 2, "total": 3},
            validation_failed=True,
        )

        self.assertIn("remaining validation errors: 2", result["error"])
        self.assertIn(report_path, result["error"])

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

    def test_save_initial_validation_report_preserves_first_report_snapshot(self):
        initial_report = [{"part": "sec", "num_or_ph": "1", "severity": "error"}]

        with tempfile.TemporaryDirectory() as tmp_dir:
            output_dir = Path(tmp_dir)
            save_initial_validation_report(output_dir, initial_report)
            (output_dir / "errors_report.json").write_text("[]", encoding="utf-8")

            saved = json.loads(
                (output_dir / INITIAL_ERRORS_REPORT_FILENAME).read_text(encoding="utf-8")
            )

        self.assertEqual(saved, initial_report)

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

    def test_pdf_only_latex_source_is_detected(self):
        sections = [
            {
                "section": "-1+0",
                "content": (
                    "\\documentclass[a4paper]{article}\n"
                    "\\usepackage{pdfpages}\n"
                    "\\begin{document}\n"
                    "\\includepdf[pages=1-last]{paper.pdf}\n"
                    "\\end{document}"
                ),
                "trans_content": "",
            }
        ]

        self.assertTrue(is_pdf_only_latex_source(sections, captions=[], envs=[]))

    def test_latex_source_with_real_section_and_pdf_appendix_is_not_pdf_only(self):
        sections = [
            {"section": "-1", "content": "\\documentclass{article}", "trans_content": ""},
            {"section": "0", "content": "\\begin{document}", "trans_content": ""},
            {
                "section": "1",
                "content": "\\section{Intro} We propose a method. \\includepdf{appendix.pdf}",
                "trans_content": "",
            },
        ]

        self.assertFalse(is_pdf_only_latex_source(sections, captions=[], envs=[]))

    def test_build_unsupported_source_result_marks_workflow_not_ok(self):
        result = build_unsupported_source_result(
            project_name="1707.06347",
            errors_report_path=r"outputs\ch_1707.06347\errors_report.json",
            error="LaTeX source only embeds PDF pages.",
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "unsupported_source")
        self.assertIsNone(result["pdf_path"])
        self.assertIn("embeds PDF", result["error"])

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

    def test_workflow_stops_on_pdf_only_latex_source_before_translation(self):
        events = []

        class FakeParserAgent:
            def __init__(self, config, project_dir, output_dir):
                self.output_dir = Path(output_dir)

            def execute(self):
                events.append("parser")
                self.output_dir.mkdir(parents=True, exist_ok=True)
                (self.output_dir / "sections_map.json").write_text(
                    json.dumps([
                        {
                            "section": "-1+0",
                            "content": (
                                "\\documentclass{article}\n"
                                "\\usepackage{pdfpages}\n"
                                "\\begin{document}\n"
                                "\\includepdf[pages=1-last]{paper.pdf}\n"
                                "\\end{document}"
                            ),
                            "trans_content": "",
                        }
                    ], ensure_ascii=False),
                    encoding="utf-8",
                )
                for filename in (
                    "captions_map.json",
                    "envs_map.json",
                    "inputs_map.json",
                    "newcommands_map.json",
                ):
                    (self.output_dir / filename).write_text("[]", encoding="utf-8")

        translator = Mock()
        translator.execute = AsyncMock(side_effect=lambda *args, **kwargs: events.append("translator"))

        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = os.path.join(tmpdir, "1707.06347")
            output_dir = os.path.join(tmpdir, "outputs")
            config = {
                "source_language": "en",
                "target_language": "ch",
                "llm_config": {},
                "terminology": {"enabled": False},
            }
            agent = CoordinatorAgent(config=config, project_dir=project_dir, output_dir=output_dir)
            try:
                with patch.object(coordinator_agent, "ParserAgent", FakeParserAgent), \
                        patch.object(coordinator_agent, "TranslatorAgent", return_value=translator), \
                        patch.object(coordinator_agent, "GeneratorAgent") as generator_cls, \
                        patch("builtins.print"):
                    result = agent.workflow_latextrans()
            finally:
                if not agent.loop.is_closed():
                    agent.loop.close()

        self.assertEqual(events, ["parser"])
        self.assertEqual(result["status"], "unsupported_source")
        self.assertFalse(result["ok"])
        translator.execute.assert_not_called()
        generator_cls.assert_not_called()

    def test_retranslation_workflow_reuses_existing_terms_without_parsing(self):
        events = []

        class FakeTranslatorAgent:
            def __init__(self, config, project_dir, output_dir, trans_mode):
                self.output_dir = Path(output_dir)

            def read_file(self, file_path, file_format):
                with open(file_path, "r", encoding="utf-8") as file:
                    return json.load(file)

            def save_file(self, file_path, file_format, data):
                with open(file_path, "w", encoding="utf-8") as file:
                    json.dump(data, file, ensure_ascii=False)

            async def execute(self, *args, **kwargs):
                events.append(("translator", args, kwargs))

            def enable_retranslation(self):
                events.append(("enable_retranslation", (), {}))

        class FakeValidatorAgent:
            def __init__(self, config, project_dir, output_dir):
                pass

            def execute(self, *args):
                events.append(("validator", args, {}))
                return []

            def save_file(self, file_path, file_format, data):
                with open(file_path, "w", encoding="utf-8") as file:
                    json.dump(data, file, ensure_ascii=False)

        class FakeGeneratorAgent:
            def __init__(self, config, project_dir, output_dir):
                self.output_dir = Path(output_dir)

            def execute(self):
                events.append(("generator", (), {}))
                pdf_path = self.output_dir / "build.pdf"
                pdf_path.write_bytes(b"%PDF")
                return str(pdf_path)

        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = os.path.join(tmpdir, "paper")
            output_dir = os.path.join(tmpdir, "output")
            transed_dir = Path(output_dir) / "ch_paper"
            transed_dir.mkdir(parents=True)

            (transed_dir / "sections_map.json").write_text(
                json.dumps([
                    {"section": "-1", "content": "preamble", "trans_content": "preamble"},
                    {"section": "0", "content": "front", "trans_content": "front"},
                    {"section": "1", "content": "body", "trans_content": "旧译文"},
                ], ensure_ascii=False),
                encoding="utf-8",
            )
            (transed_dir / "captions_map.json").write_text(
                json.dumps([{"content": "caption", "trans_content": "旧图题"}], ensure_ascii=False),
                encoding="utf-8",
            )
            (transed_dir / "envs_map.json").write_text(
                json.dumps([
                    {"content": "math", "trans_content": "", "need_trans": False},
                    {"content": "env", "trans_content": "旧环境", "need_trans": True},
                ], ensure_ascii=False),
                encoding="utf-8",
            )
            (transed_dir / "inputs_map.json").write_text(
                json.dumps([], ensure_ascii=False),
                encoding="utf-8",
            )
            (transed_dir / "newcommands_map.json").write_text(
                json.dumps([], ensure_ascii=False),
                encoding="utf-8",
            )
            (transed_dir / "project_terms.csv").write_text(
                "Source Term,Target Translation\nGraph,图\n",
                encoding="utf-8",
            )

            agent = CoordinatorAgent(
                config={"target_language": "ch"},
                project_dir=project_dir,
                output_dir=output_dir,
            )
            try:
                with patch.object(coordinator_agent, "ParserAgent") as parser_cls, \
                        patch.object(coordinator_agent, "TerminologyAgent") as terminology_cls, \
                        patch.object(coordinator_agent, "TranslatorAgent", FakeTranslatorAgent), \
                        patch.object(coordinator_agent, "ValidatorAgent", FakeValidatorAgent), \
                        patch.object(coordinator_agent, "GeneratorAgent", FakeGeneratorAgent), \
                        patch("builtins.print"):
                    result = agent.workflow_latextrans_with_existing_terms()
            finally:
                if not agent.loop.is_closed():
                    agent.loop.close()

            parser_cls.assert_not_called()
            terminology_cls.assert_not_called()
            self.assertEqual([event[0] for event in events], ["translator", "validator", "generator"])
            self.assertEqual(result["pdf_path"], str(transed_dir / "ch_paper.pdf"))

            with open(transed_dir / "sections_map.json", "r", encoding="utf-8") as file:
                sections = json.load(file)
            with open(transed_dir / "captions_map.json", "r", encoding="utf-8") as file:
                captions = json.load(file)
            with open(transed_dir / "envs_map.json", "r", encoding="utf-8") as file:
                envs = json.load(file)

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

    def test_workflow_result_keeps_generated_terms_paths_after_translation(self):
        """术语扫描后继续翻译时，最终结果应保留生成的术语表路径。"""
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
                    "review_before_translate": False,
                },
            }
            agent = CoordinatorAgent(config=config, project_dir=project_dir, output_dir=output_dir)
            try:
                with patch.object(coordinator_agent, "ParserAgent", return_value=parser), \
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

        self.assertEqual(events, ["parser", "terminology", "translator"])
        self.assertEqual(result["project_terms_path"], r"outputs\ch_paper\project_terms.csv")
        self.assertEqual(
            result["project_terms_decisions_path"],
            r"outputs\ch_paper\project_terms_decisions.json",
        )

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
