import unittest

from src.agents.tool_agents.translator_agent import TranslatorAgent


class TranslatorRetryPromptTests(unittest.TestCase):
    def test_retranslation_prompt_includes_concrete_command_context(self):
        agent = TranslatorAgent(config={"llm_config": {}})
        part = {
            "content": r"Use \textit{confidence} and \textit{uncertainty}.",
            "trans_content": r"使用 \textit{置信度} 和不确定性。",
        }
        error_message = (
            "LaTeX command translation error or is missing:\n"
            r"'\textit' — expected 2, found 1"
        )

        prompt = agent._build_retranslation_user_prompt(part, error_message)

        self.assertIn("[Concrete Fix Checklist]", prompt)
        self.assertIn(r"Preserve command `\textit`: source count=2, translation count=1.", prompt)
        self.assertIn("Source occurrences:", prompt)


if __name__ == "__main__":
    unittest.main()
