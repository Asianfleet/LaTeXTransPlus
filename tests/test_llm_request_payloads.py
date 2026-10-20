import asyncio
import json
import unittest
from pathlib import Path
from unittest.mock import patch

import requests

from src.agents.tool_agents.parser_agent import ParserAgent
from src.agents.tool_agents.markdown_translator_agent import MarkdownTranslatorAgent
from src.agents.tool_agents.terminology_agent import TerminologyAgent
from src.agents.tool_agents.translator_agent import TranslatorAgent


CUSTOM_JSON = {"enable_thinking": True, "reasoning_effort": "high"}


class _ParserResponse:
    def raise_for_status(self):
        return None

    def json(self):
        return {"choices": [{"message": {"content": "true"}}]}


class _TranslatorResponse:
    def raise_for_status(self):
        return None

    async def json(self):
        return {"choices": [{"message": {"content": "译文"}}]}


class _AsyncPost:
    def __init__(self, response):
        self.response = response

    async def __aenter__(self):
        return self.response

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _CapturingAsyncSession:
    def __init__(self):
        self.payloads = []

    def post(self, _url, json, headers, timeout):
        self.payloads.append(json)
        return _AsyncPost(_TranslatorResponse())


class LlmRequestPayloadTests(unittest.TestCase):
    def test_explicit_reasoning_effort_reaches_all_agent_request_bodies(self):
        """各请求入口均使用显式强度覆盖 profile，而非仅在运行时展开生效。"""
        config = {
            "source_language": "en", "target_language": "ja",
            "llm_config": {
                "api_key": "test-key", "base_url": "https://example.test",
                "custom_json": CUSTOM_JSON, "reasoning_effort": "ultra",
            },
        }
        parser = ParserAgent(config=config)
        with patch(
            "src.agents.tool_agents.parser_agent.requests.post",
            return_value=_ParserResponse(),
        ) as post:
            parser._request_llm_for_judge("Judge this.", "text")
            self.assertEqual(post.call_args.kwargs["json"]["reasoning_effort"], "ultra")

        translator = TranslatorAgent(config=config)
        session = _CapturingAsyncSession()
        asyncio.run(translator._request_llm_for_retrans_error_parts(
            "Retry prompt.", part={"content": "source", "trans_content": "text"},
            error_message="validation error", fail_part="1", type="sec", session=session,
        ))
        self.assertEqual(session.payloads[0]["reasoning_effort"], "ultra")

        terminology = TerminologyAgent(config=config, project_dir="paper", output_dir="unused")
        with patch(
            "src.agents.tool_agents.terminology_agent.requests.post",
            return_value=_TerminologyResponse(),
        ) as post:
            terminology._request_llm_for_term_decisions(
                ["power sampling"], {"title": "Sampling"},
                {"power sampling": ["Power sampling works."]}, {},
            )
            self.assertEqual(post.call_args.kwargs["json"]["reasoning_effort"], "ultra")

        markdown = MarkdownTranslatorAgent(
            config=config, source_markdown=Path("source.md"), output_dir=Path("unused"),
            blocks=[],
        )
        markdown._session = session = _CapturingAsyncSession()
        asyncio.run(markdown._request_provider_translation("source", {}, 0))
        self.assertEqual(session.payloads[0]["reasoning_effort"], "ultra")

    def test_parser_request_includes_custom_json_at_top_level(self):
        agent = ParserAgent(
            config={
                "source_language": "en",
                "target_language": "ch",
                "llm_config": {
                    "api_key": "test-key",
                    "base_url": "https://example.test",
                    "custom_json": CUSTOM_JSON,
                },
            }
        )
        captured = {}

        def fake_post(_url, **kwargs):
            captured["payload"] = kwargs["json"]
            return _ParserResponse()

        with patch(
            "src.agents.tool_agents.parser_agent.requests.post",
            side_effect=fake_post,
        ):
            result = agent._request_llm_for_judge("Judge this.", "text")

        self.assertTrue(result)
        self.assertEqual(
            {key: captured["payload"][key] for key in CUSTOM_JSON},
            CUSTOM_JSON,
        )

    def test_translator_retry_request_includes_custom_json_at_top_level(self):
        agent = TranslatorAgent(
            config={
                "source_language": "en",
                "target_language": "ch",
                "llm_config": {
                    "api_key": "test-key",
                    "base_url": "https://example.test",
                    "custom_json": CUSTOM_JSON,
                },
            }
        )
        session = _CapturingAsyncSession()

        asyncio.run(
            agent._request_llm_for_retrans_error_parts(
                "Retry prompt.",
                part={"content": "source", "trans_content": "译文"},
                error_message="validation error",
                fail_part="1",
                type="sec",
                session=session,
            )
        )

        self.assertEqual(
            {key: session.payloads[0][key] for key in CUSTOM_JSON},
            CUSTOM_JSON,
        )

    def test_terminology_request_includes_custom_json_at_top_level(self):
        agent = TerminologyAgent(
            config={
                "source_language": "en",
                "target_language": "ch",
                "llm_config": {
                    "api_key": "test-key",
                    "base_url": "https://example.test",
                    "custom_json": CUSTOM_JSON,
                },
            },
            project_dir="paper",
            output_dir="unused",
        )
        captured = {}

        def fake_post(_url, **kwargs):
            captured["payload"] = kwargs["json"]
            return _TerminologyResponse()

        with patch(
            "src.agents.tool_agents.terminology_agent.requests.post",
            side_effect=fake_post,
        ):
            agent._request_llm_for_term_decisions(
                ["power sampling"],
                {"title": "Sampling"},
                {"power sampling": ["Power sampling works."]},
                {},
            )

        self.assertEqual(
            {key: captured["payload"][key] for key in CUSTOM_JSON},
            CUSTOM_JSON,
        )


class _TerminologyResponse:
    def __init__(self):
        self.headers = {}

    def raise_for_status(self):
        return None

    def json(self):
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "decisions": [
                                    {
                                        "source_term": "power sampling",
                                        "selected_translation": "幂采样",
                                    }
                                ]
                            }
                        )
                    }
                }
            ]
        }


if __name__ == "__main__":
    unittest.main()
