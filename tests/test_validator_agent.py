import json
import tempfile
import unittest
from pathlib import Path

from src.agents.tool_agents.validator_agent import ValidatorAgent


class ValidatorAgentTests(unittest.TestCase):
    def setUp(self):
        self.validator = ValidatorAgent(config={})

    def test_validate_command_accepts_textbf_for_legacy_bf(self):
        part = {
            "content": r"\begin{itemize}\item[{\bf i)}] Source text.\end{itemize}",
            "trans_content": r"\begin{itemize}\item[\textbf{i})] 译文。\end{itemize}",
        }

        self.assertIsNone(self.validator._validate_command(part))

    def test_validate_brackets_ignores_item_optional_label_parentheses(self):
        part = {
            "content": r"\begin{itemize}\item[{\bf i)}] Source text.\end{itemize}",
            "trans_content": r"\begin{itemize}\item[\textbf{i})] 译文。\end{itemize}",
        }

        self.assertIsNone(self.validator._validate_closed_brackets(part))

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
            validator.log = lambda message: None
            result = validator.execute()

            self.assertEqual(result, [])
            saved = json.loads((output_dir / "errors_report.json").read_text(encoding="utf-8"))
            self.assertEqual(saved, [])


if __name__ == "__main__":
    unittest.main()
