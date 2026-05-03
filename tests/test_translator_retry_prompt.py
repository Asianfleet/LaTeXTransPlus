import unittest

from src.agents.tool_agents.translator_agent import TranslatorAgent


class TranslatorRetryPromptTests(unittest.TestCase):
    def test_translation_mode_defaults_to_plain_string(self):
        agent = TranslatorAgent(config={"llm_config": {}})

        self.assertEqual(agent.trans_mode, "plain")

    def test_translation_mode_accepts_terms_string(self):
        agent = TranslatorAgent(config={"llm_config": {}}, trans_mode="terms")

        self.assertEqual(agent.trans_mode, "terms")

    def test_translation_mode_keeps_legacy_number_compatibility(self):
        self.assertEqual(
            TranslatorAgent(config={"llm_config": {}}, trans_mode=0).trans_mode,
            "plain",
        )
        self.assertEqual(
            TranslatorAgent(config={"llm_config": {}}, trans_mode=1).trans_mode,
            "retry",
        )
        self.assertEqual(
            TranslatorAgent(config={"llm_config": {}}, trans_mode=2).trans_mode,
            "terms",
        )

    def test_translation_mode_rejects_unknown_value(self):
        with self.assertRaisesRegex(ValueError, "Invalid translation mode"):
            TranslatorAgent(config={"llm_config": {}}, trans_mode="unknown")

    def test_update_term_string_true_enables_dynamic_terms(self):
        agent = TranslatorAgent(config={"llm_config": {}, "update_term": "True"})

        self.assertIs(agent.update_term, True)

    def test_update_term_defaults_to_false_when_missing(self):
        agent = TranslatorAgent(config={"llm_config": {}})

        self.assertIs(agent.update_term, False)

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
