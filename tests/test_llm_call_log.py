import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from src.llm_call_log import LlmCallLogger
from src.agents.tool_agents.translator_agent import TranslatorAgent


class _Response:
    async def json(self):
        return {"choices": [{"message": {"content": "译文"}}]}

    def raise_for_status(self):
        return None


class _Post:
    async def __aenter__(self):
        return _Response()

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _Session:
    def post(self, *args, **kwargs):
        return _Post()


class LlmCallLoggerTests(unittest.TestCase):
    def test_records_request_and_response_as_utf8_jsonl(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            logger = LlmCallLogger(Path(tmp_dir), agent_name="TranslatorAgent")
            logger.record(
                operation="translation",
                attempt=2,
                payload={"messages": [{"role": "user", "content": "你好"}]},
                response={"choices": [{"message": {"content": "Hello"}}]},
                status_code=200,
            )

            record = json.loads((Path(tmp_dir) / "llm_calls.jsonl").read_text(encoding="utf-8"))
            self.assertEqual(record["agent_name"], "TranslatorAgent")
            self.assertEqual(record["operation"], "translation")
            self.assertEqual(record["attempt"], 2)
            self.assertEqual(record["request"]["messages"][0]["content"], "你好")
            self.assertEqual(record["response"]["choices"][0]["message"]["content"], "Hello")
            self.assertEqual(record["status_code"], 200)
            self.assertNotIn("Authorization", record)

    def test_translator_request_is_written_to_task_output_dir(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            agent = TranslatorAgent(
                config={
                    "source_language": "en", "target_language": "ch",
                    "llm_config": {"api_key": "test-key", "base_url": "https://example.test"},
                },
                output_dir=tmp_dir,
            )
            asyncio.run(agent._request_llm_for_retrans_error_parts(
                "Translate only.",
                part={"content": "source", "trans_content": "旧译文"},
                error_message="validation error",
                fail_part="1", type="sec", session=_Session(),
            ))

            record = json.loads((Path(tmp_dir) / "llm_calls.jsonl").read_text(encoding="utf-8"))
            self.assertEqual(record["agent_name"], "TranslatorAgent")
            self.assertEqual(record["operation"], "retranslation")
            self.assertEqual(record["response"]["choices"][0]["message"]["content"], "译文")

    def test_records_transport_error_without_response(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            LlmCallLogger(Path(tmp_dir), agent_name="ParserAgent").record(
                operation="judge_environment",
                attempt=1,
                payload={"model": "test"},
                error="network down",
            )

            record = json.loads((Path(tmp_dir) / "llm_calls.jsonl").read_text(encoding="utf-8"))
            self.assertEqual(record["error"], "network down")
            self.assertNotIn("response", record)


if __name__ == "__main__":
    unittest.main()
