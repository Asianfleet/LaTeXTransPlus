import asyncio
import json
import unittest
from unittest.mock import patch

import requests

from src.agents.tool_agents.parser_agent import ParserAgent
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
