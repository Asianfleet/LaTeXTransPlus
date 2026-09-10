import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import requests

from src.agents.tool_agents.markdown_terminology_agent import (
    MarkdownTerminologyAgent,
)
from src.terminology import load_term_csv


class _FakeResponse:
    """Provide the requests response surface used by terminology generation."""

    def __init__(self, decisions: list[dict[str, object]]) -> None:
        """Store terminology decisions for a fake chat completion response."""
        self.headers = {"x-request-id": "markdown-terms-test"}
        self._decisions = decisions

    def raise_for_status(self) -> None:
        """Accept the fake response as successful."""

    def json(self) -> dict[str, object]:
        """Return a chat-completions-compatible JSON body."""
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {"decisions": self._decisions}, ensure_ascii=False
                        )
                    }
                }
            ]
        }


class MarkdownTerminologyTests(unittest.TestCase):
    """Verify terminology generation directly from Markdown documents."""

    def _config(self, **terminology: object) -> dict[str, object]:
        """Build a minimal multilingual terminology configuration for tests."""
        return {
            "source_language": "en",
            "target_language": "ch",
            "terminology": {"max_llm_candidates": 1, **terminology},
            "llm_config": {
                "api_key": "test-key",
                "base_url": "https://example.test/chat/completions",
                "model": "test-model",
            },
        }

    @patch("src.agents.tool_agents.markdown_terminology_agent.requests.post")
    def test_execute_generates_project_terms_with_document_context(self, post) -> None:
        """Generate CSV and decisions while sending Markdown title and abstract context."""
        post.return_value = _FakeResponse(
            [
                {
                    "source_term": "power sampling",
                    "accepted": True,
                    "candidate_translations": ["幂采样"],
                    "selected_translation": "幂采样",
                    "reason": "The paper uses this as a method name.",
                }
            ]
        )
        source = (
            "# Reasoning by Sampling\n\n"
            "## Abstract\n"
            "Power sampling improves reasoning with a target distribution.\n\n"
            "## Method\n"
            "Power sampling reweights a sampling distribution.\n"
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            output_dir = Path(tmp_dir)
            markdown_path = output_dir / "source.md"
            markdown_path.write_text(source, encoding="utf-8")

            result = MarkdownTerminologyAgent(
                self._config(), markdown_path, output_dir
            ).execute()

            terms_path = Path(result["project_terms_path"])
            decisions_path = Path(result["project_terms_decisions_path"])
            terms = load_term_csv(terms_path, source_language="en").terms
            decisions = json.loads(decisions_path.read_text(encoding="utf-8"))

        self.assertTrue(result["ok"])
        self.assertEqual(terms["power sampling"], "幂采样")
        self.assertEqual(decisions["paper_context"]["title"], "Reasoning by Sampling")
        self.assertIn("Power sampling improves", decisions["paper_context"]["abstract"])
        post.assert_called_once()
        request_body = json.loads(post.call_args.kwargs["json"]["messages"][1]["content"])
        self.assertEqual(request_body["paper_context"]["title"], "Reasoning by Sampling")
        self.assertTrue(request_body["term_contexts"]["power sampling"])

    @patch("src.agents.tool_agents.markdown_terminology_agent.requests.post")
    def test_plan_example_accepts_candidate_without_review_pause(self, post) -> None:
        """Ignore heavy-only review pauses while accepting the plan's noun phrase."""
        post.return_value = _FakeResponse(
            [
                {
                    "source_term": "neural representation",
                    "accepted": True,
                    "candidate_translations": ["神经表示"],
                    "selected_translation": "神经表示",
                    "reason": "It is a technical concept in the document.",
                }
            ]
        )
        source = (
            "# Representation Learning\n\n"
            "Neural representation supports inference. "
            "Neural representation supports compression.\n"
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            output_dir = Path(tmp_dir)
            markdown_path = output_dir / "source.md"
            markdown_path.write_text(source, encoding="utf-8")

            result = MarkdownTerminologyAgent(
            self._config(review_before_translate=True), markdown_path, output_dir
            ).execute()
            terms = load_term_csv(
                Path(result["project_terms_path"]), source_language="en"
            ).terms

        self.assertEqual(terms["neural representation"], "神经表示")

    @patch("src.agents.tool_agents.markdown_terminology_agent.requests.post")
    def test_empty_candidate_list_writes_valid_empty_artifacts(self, post) -> None:
        """Write valid empty outputs without requiring an LLM request."""
        config = self._config()
        config["source_language"] = "de"
        config["target_language"] = "jp"

        with tempfile.TemporaryDirectory() as tmp_dir:
            output_dir = Path(tmp_dir)
            markdown_path = output_dir / "source.md"
            markdown_path.write_text("# Titel\n\nEin kurzer deutscher Text.\n", encoding="utf-8")

            result = MarkdownTerminologyAgent(
                config, markdown_path, output_dir
            ).execute()

            terms_text = Path(result["project_terms_path"]).read_text(encoding="utf-8")
            decisions = json.loads(
                Path(result["project_terms_decisions_path"]).read_text(encoding="utf-8")
            )

        self.assertEqual(terms_text, "Source Term,Target Translation\n")
        self.assertEqual(decisions["decisions"], [])
        post.assert_not_called()

    @patch("src.agents.tool_agents.markdown_terminology_agent.requests.post")
    def test_disabled_terminology_writes_empty_artifacts_without_request(self, post) -> None:
        """Honor the shared terminology switch without incurring an LLM request."""
        config = self._config(enabled=False)

        with tempfile.TemporaryDirectory() as tmp_dir:
            output_dir = Path(tmp_dir)
            markdown_path = output_dir / "source.md"
            markdown_path.write_text(
                "# Paper\n\nPower sampling uses a sampling distribution.\n",
                encoding="utf-8",
            )

            result = MarkdownTerminologyAgent(
                config, markdown_path, output_dir
            ).execute()
            terms_text = Path(result["project_terms_path"]).read_text(encoding="utf-8")
            decisions = json.loads(
                Path(result["project_terms_decisions_path"]).read_text(encoding="utf-8")
            )

        post.assert_not_called()
        self.assertEqual(terms_text, "Source Term,Target Translation\n")
        self.assertEqual(decisions["decisions"], [])

    def test_extracts_abstract_context_for_configured_source_language(self) -> None:
        """Recognize a localized abstract heading without assuming English input."""
        for source_language in ("ch", "cn", "zh"):
            with self.subTest(source_language=source_language):
                config = self._config()
                config["source_language"] = source_language
                config["target_language"] = "en"

                with tempfile.TemporaryDirectory() as tmp_dir:
                    output_dir = Path(tmp_dir)
                    markdown_path = output_dir / "source.md"
                    markdown_path.write_text(
                        "# 采样推理\n\n## 摘要\n本文研究采样效率。\n\n## 方法\n方法正文。\n",
                        encoding="utf-8",
                    )

                    result = MarkdownTerminologyAgent(
                        config, markdown_path, output_dir
                    ).execute()
                    decisions = json.loads(
                        Path(result["project_terms_decisions_path"]).read_text(
                            encoding="utf-8"
                        )
                    )

                self.assertEqual(
                    decisions["paper_context"]["abstract"], "本文研究采样效率。"
                )

    @patch("src.agents.tool_agents.markdown_terminology_agent.requests.post")
    def test_german_candidates_reach_llm_with_configured_language_context(self, post) -> None:
        """Generate and persist a German term without applying English-only filtering."""
        post.return_value = _FakeResponse(
            [
                {
                    "source_term": "neuronale darstellung",
                    "accepted": True,
                    "candidate_translations": ["ニューラル表現"],
                    "selected_translation": "ニューラル表現",
                    "reason": "Repeated technical phrase.",
                }
            ]
        )
        config = self._config()
        config["source_language"] = "de"
        config["target_language"] = "ja"
        source = (
            "# Neuronale Darstellung\n\n"
            "Neuronale Darstellung ist wichtig. "
            "Neuronale Darstellung ist wichtig.\n"
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            output_dir = Path(tmp_dir)
            markdown_path = output_dir / "source.md"
            markdown_path.write_text(source, encoding="utf-8")

            result = MarkdownTerminologyAgent(config, markdown_path, output_dir).execute()
            terms = load_term_csv(
                Path(result["project_terms_path"]), source_language="de"
            ).terms
            decisions = json.loads(
                Path(result["project_terms_decisions_path"]).read_text(
                    encoding="utf-8"
                )
            )

        post.assert_called_once()
        request_body = json.loads(post.call_args.kwargs["json"]["messages"][1]["content"])
        system_prompt = post.call_args.kwargs["json"]["messages"][0]["content"]
        self.assertIn("German", system_prompt)
        self.assertIn("Japanese", system_prompt)
        self.assertEqual(request_body["source_language"], "de")
        self.assertEqual(request_body["target_language"], "ja")
        self.assertEqual(request_body["candidates"], ["neuronale darstellung"])
        self.assertEqual(terms["neuronale darstellung"], "ニューラル表現")
        self.assertEqual(decisions["source_language"], "de")
        self.assertEqual(decisions["target_language"], "ja")
        self.assertEqual(len(decisions["decisions"]), 1)
        self.assertEqual(
            decisions["decisions"][0]["source_term"], "neuronale darstellung"
        )
        self.assertEqual(
            decisions["decisions"][0]["candidate_translations"], ["ニューラル表現"]
        )
        self.assertEqual(
            decisions["decisions"][0]["selected_translation"], "ニューラル表現"
        )
        self.assertTrue(decisions["decisions"][0]["accepted"])

    @patch("src.agents.tool_agents.markdown_terminology_agent.time.sleep")
    @patch("src.agents.tool_agents.markdown_terminology_agent.requests.post")
    def test_llm_failure_is_logged_and_raised(self, post, _sleep) -> None:
        """Propagate final provider failures so the lite workflow can fail."""
        post.side_effect = requests.exceptions.ReadTimeout("provider unavailable")
        logs: list[tuple[str, str]] = []
        config = self._config()
        config["_project_log_callback"] = lambda event: logs.append(
            (event["level"], event["message"])
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            output_dir = Path(tmp_dir)
            markdown_path = output_dir / "source.md"
            markdown_path.write_text(
                "# Paper\n\nPower sampling uses a sampling distribution.\n",
                encoding="utf-8",
            )
            agent = MarkdownTerminologyAgent(config, markdown_path, output_dir)

            with self.assertRaisesRegex(requests.exceptions.ReadTimeout, "provider unavailable"):
                agent.execute()

        self.assertTrue(any(level == "error" and "failed" in message.lower() for level, message in logs))


if __name__ == "__main__":
    unittest.main()
