import tempfile
import unittest
from pathlib import Path

from src.agents.tool_agents.translator_agent import TranslatorAgent
import src.formats.latex.prompts as pm


class _FakeResponse:
    def raise_for_status(self):
        return None

    async def json(self):
        return {"choices": [{"message": {"content": "N/A"}}]}


class _SuccessfulPost:
    def __init__(self, response):
        self.response = response

    async def __aenter__(self):
        return self.response

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _SuccessfulSession:
    def __init__(self):
        self.payload = None

    def post(self, url, json, headers, timeout):
        self.payload = json
        return _SuccessfulPost(_FakeResponse())


class MultilingualPromptTests(unittest.TestCase):
    def test_language_codes_are_rendered_as_language_names(self):
        pm.init_prompts("de", "jp")

        self.assertIn("from German to Japanese", pm.section_system_prompt)

    def test_terminology_prompt_is_not_hardcoded_to_english_chinese(self):
        pm.init_prompts("de", "jp")

        self.assertIn("German source sentence", pm.extract_terminology_system_prompt)
        self.assertIn("Japanese translation", pm.extract_terminology_system_prompt)
        self.assertIn("Example 1 (English to Chinese)", pm.extract_terminology_system_prompt)
        self.assertIn("Example 2 (German to Japanese)", pm.extract_terminology_system_prompt)
        self.assertNotIn("en-zh", pm.extract_terminology_system_prompt)


class MultilingualTerminologyTests(unittest.TestCase):
    def test_default_english_chinese_terms_are_not_loaded_for_other_language_pairs(self):
        agent = TranslatorAgent(
            config={
                "source_language": "de",
                "target_language": "jp",
                "llm_config": {},
            },
            project_dir="paper",
        )

        agent.build_term_dict()

        self.assertEqual(agent.term_dict, {})

    def test_user_terms_are_loaded_as_source_target_pairs(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            term_path = Path(tmp_dir) / "terms.csv"
            term_path.write_text("Graph,グラフ\n", encoding="utf-8")
            agent = TranslatorAgent(
                config={
                    "source_language": "en",
                    "target_language": "jp",
                    "user_term": str(term_path),
                    "llm_config": {},
                },
                project_dir="paper",
            )

            agent.build_term_dict()

        self.assertEqual(agent.term_dict, {"Graph": "グラフ"})


class MultilingualTerminologyRequestTests(unittest.IsolatedAsyncioTestCase):
    async def test_terminology_request_uses_configured_language_labels(self):
        agent = TranslatorAgent(
            config={
                "source_language": "de",
                "target_language": "jp",
                "llm_config": {"api_key": "test-key", "base_url": "https://example.test"},
            },
            project_dir="paper",
        )
        session = _SuccessfulSession()

        await agent._request_llm_for_extract_terms(
            "Extract terms.",
            "Graphenmodell",
            "グラフモデル",
            session=session,
        )

        user_content = session.payload["messages"][1]["content"]
        self.assertIn("<German source>", user_content)
        self.assertIn("<Japanese translation>", user_content)
        self.assertNotIn("<en source>", user_content)
        self.assertNotIn("<zh translation>", user_content)


if __name__ == "__main__":
    unittest.main()
