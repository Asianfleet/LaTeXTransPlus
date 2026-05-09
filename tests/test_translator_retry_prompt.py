import asyncio
import unittest
from unittest.mock import AsyncMock, patch

import aiohttp

from src.agents.tool_agents.translator_agent import TranslatorAgent


class _FakeResponse:
    def raise_for_status(self):
        return None

    async def json(self):
        return {"choices": [{"message": {"content": "修正后的译文"}}]}


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


class _FailingPost:
    async def __aenter__(self):
        raise aiohttp.ClientError("network down")

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FailingSession:
    def __init__(self):
        self.calls = 0

    def post(self, url, json, headers, timeout):
        self.calls += 1
        return _FailingPost()


class TranslatorRetryPromptTests(unittest.TestCase):
    def test_translation_mode_defaults_to_plain_string(self):
        agent = TranslatorAgent(config={"llm_config": {}})

        self.assertEqual(agent.trans_mode, "plain")

    def test_translation_mode_accepts_terms_string(self):
        agent = TranslatorAgent(config={"llm_config": {}}, trans_mode="terms")

        self.assertEqual(agent.trans_mode, "terms")

    def test_translation_mode_rejects_legacy_number_values(self):
        for mode in (0, 1, 2, "0", "1", "2"):
            with self.subTest(mode=mode):
                with self.assertRaisesRegex(ValueError, "Invalid translation mode"):
                    TranslatorAgent(config={"llm_config": {}}, trans_mode=mode)

    def test_translation_mode_rejects_unknown_value(self):
        with self.assertRaisesRegex(ValueError, "Invalid translation mode"):
            TranslatorAgent(config={"llm_config": {}}, trans_mode="unknown")

    def test_translation_mode_rejects_retry_as_user_config(self):
        with self.assertRaisesRegex(ValueError, "Invalid translation mode"):
            TranslatorAgent(config={"llm_config": {}}, trans_mode="retry")

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

    def test_project_terms_enable_terms_prompt_for_plain_mode(self):
        agent = TranslatorAgent(config={"llm_config": {}}, trans_mode="plain")
        agent.term_dict = {"Graph": "图"}
        agent._project_terms_loaded = True

        self.assertTrue(agent._should_use_terms_prompt())

    def test_plain_project_terms_section_uses_terms_request(self):
        agent = TranslatorAgent(config={"llm_config": {}}, trans_mode="plain")
        agent.term_dict = {"Graph": "图"}
        agent._project_terms_loaded = True

        with (
            patch.object(agent, "_request_llm_for_trans", new_callable=AsyncMock) as plain_request,
            patch.object(
                agent,
                "_request_llm_for_trans_with_terms",
                new_callable=AsyncMock,
                return_value="图",
            ) as terms_request,
        ):
            result = asyncio.run(
                agent._translate_section(
                    {"section": "1", "content": "Graph"},
                    session=None,
                )
            )

        self.assertEqual(result["trans_content"], "图")
        plain_request.assert_not_awaited()
        terms_request.assert_awaited_once()


class TranslatorRetryRequestTests(unittest.IsolatedAsyncioTestCase):
    async def test_plain_retranslation_prompt_does_not_include_glossary(self):
        agent = TranslatorAgent(
            config={
                "source_language": "en",
                "target_language": "ch",
                "llm_config": {"api_key": "test-key", "base_url": "https://example.test"},
            },
            trans_mode="plain",
        )
        agent.term_dict = {"Graph": "图"}
        session = _SuccessfulSession()

        await agent._request_llm_for_retrans_error_parts(
            "Retry system prompt.",
            part={"content": "Graph", "trans_content": "图"},
            error_message="Brackets error",
            fail_part="1",
            type="sec",
            session=session,
        )

        system_content = session.payload["messages"][0]["content"]
        self.assertNotIn("<Glossary>", system_content)
        self.assertNotIn("When translating, you must strictly use", system_content)

    async def test_terms_retranslation_prompt_includes_glossary(self):
        agent = TranslatorAgent(
            config={
                "source_language": "en",
                "target_language": "ch",
                "llm_config": {"api_key": "test-key", "base_url": "https://example.test"},
            },
            trans_mode="terms",
        )
        agent.term_dict = {"Graph": "图"}
        session = _SuccessfulSession()

        await agent._request_llm_for_retrans_error_parts(
            "Retry system prompt.",
            part={"content": "Graph", "trans_content": "图"},
            error_message="Brackets error",
            fail_part="1",
            type="sec",
            session=session,
        )

        system_content = session.payload["messages"][0]["content"]
        self.assertIn("<Glossary>", system_content)
        self.assertIn("'Graph': '图'", system_content)

    async def test_plain_project_terms_retranslation_prompt_includes_glossary(self):
        agent = TranslatorAgent(
            config={
                "source_language": "en",
                "target_language": "ch",
                "llm_config": {"api_key": "test-key", "base_url": "https://example.test"},
            },
            trans_mode="plain",
        )
        agent.term_dict = {"Graph": "图"}
        agent._project_terms_loaded = True
        session = _SuccessfulSession()

        await agent._request_llm_for_retrans_error_parts(
            "Retry system prompt.",
            part={"content": "Graph", "trans_content": "图"},
            error_message="Brackets error",
            fail_part="1",
            type="sec",
            session=session,
        )

        system_content = session.payload["messages"][0]["content"]
        self.assertIn("<Glossary>", system_content)
        self.assertIn("'Graph': '图'", system_content)

    async def test_retranslation_request_catches_aiohttp_failures(self):
        agent = TranslatorAgent(
            config={
                "source_language": "en",
                "target_language": "ch",
                "llm_config": {"api_key": "test-key", "base_url": "https://example.test"},
            },
            trans_mode="plain",
        )
        session = _FailingSession()

        with (
            patch(
                "src.agents.tool_agents.translator_agent.asyncio.sleep",
                new_callable=AsyncMock,
            ),
            patch("builtins.print"),
        ):
            result = await agent._request_llm_for_retrans_error_parts(
                "Retry system prompt.",
                part={"content": "Graph", "trans_content": "图"},
                error_message="Brackets error",
                fail_part="1",
                type="sec",
                session=session,
            )

        self.assertEqual(result, "图")
        self.assertEqual(session.calls, 3)
        self.assertTrue(agent.have_fail_parts)
        self.assertEqual(agent.fail_section_nums, ["1"])


if __name__ == "__main__":
    unittest.main()
