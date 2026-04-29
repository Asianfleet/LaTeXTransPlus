import unittest

from src.agents.coordinator_agent import format_translation_result_message


class CoordinatorMessageTests(unittest.TestCase):
    def test_success_message_mentions_validation_warnings(self):
        message = format_translation_result_message(
            system_name="LaTeXTrans",
            base_name="2510.14901",
            pdf_path=r"outputs\ch_2510.14901\ch_2510.14901.pdf",
            validation_error_count=2,
        )

        self.assertIn("generated with validation warnings", message)
        self.assertIn("remaining validation errors: 2", message)
        self.assertIn(r"outputs\ch_2510.14901\errors_report.json", message)


if __name__ == "__main__":
    unittest.main()
