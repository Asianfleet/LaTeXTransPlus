import unittest

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


if __name__ == "__main__":
    unittest.main()
