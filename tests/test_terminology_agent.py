import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.agents.tool_agents.terminology_agent import TerminologyAgent
from src.terminology import PROJECT_TERMS_DECISIONS_FILENAME, PROJECT_TERMS_FILENAME


class _FakeResponse:
    def __init__(self, content: str):
        self.content = content

    def raise_for_status(self):
        return None

    def json(self):
        return {"choices": [{"message": {"content": self.content}}]}


class TerminologyAgentContextTests(unittest.TestCase):
    def test_extracts_paper_context_from_captions_and_sections(self):
        agent = TerminologyAgent(
            config={
                "source_language": "en",
                "target_language": "ch",
                "category": {"paper": ["cs.AI"]},
                "llm_config": {},
            },
            project_dir="paper",
            output_dir="unused",
        )
        sections = [
            {
                "section": "0",
                "content": r"\begin{abstract}We propose power sampling for reasoning.\end{abstract}",
                "trans_content": "",
            },
            {
                "section": "1",
                "content": r"\section{Introduction} Power sampling improves diversity.",
                "trans_content": "",
            },
        ]
        captions = [
            {
                "placeholder": "<PLACEHOLDER_CAP_1>",
                "cap_type": "title",
                "content": r"\title{Reasoning by Sampling}",
                "trans_content": "",
            },
            {
                "placeholder": "<PLACEHOLDER_CAP_2>",
                "cap_type": "keywords",
                "content": r"\keywords{sampling, reasoning}",
                "trans_content": "",
            },
        ]

        context = agent._extract_paper_context(sections=sections, captions=captions)

        self.assertEqual(context["project_name"], "paper")
        self.assertIn("Reasoning by Sampling", context["title"])
        self.assertIn("power sampling", context["abstract"])
        self.assertEqual(context["keywords"], ["sampling", "reasoning"])
        self.assertEqual(context["category"], ["cs.AI"])

    def test_english_candidate_extraction_finds_multiword_terms(self):
        agent = TerminologyAgent(
            config={"source_language": "en", "target_language": "ch", "llm_config": {}},
            project_dir="paper",
            output_dir="unused",
        )
        records = [
            {
                "part": "sec",
                "id": "1",
                "text": "Power sampling uses a power distribution. Power sampling improves reasoning.",
            }
        ]

        candidates = agent._extract_rule_candidates(records)

        self.assertIn("power sampling", candidates)
        self.assertIn("power distribution", candidates)
        self.assertNotIn("this paper", candidates)

    def test_english_candidate_extraction_rejects_context_fragments(self):
        agent = TerminologyAgent(
            config={"source_language": "en", "target_language": "ch", "llm_config": {}},
            project_dir="paper",
            output_dir="unused",
        )
        records = [
            {
                "part": "sec",
                "id": "1",
                "text": (
                    "Our sampling algorithm uses power sampling. "
                    "Algorithm ref describes the method. "
                    "That power sampling works while low-temperature sampling does not. "
                    "The model we evaluate can sample from the target distribution. "
                    "Distribution p and distribution over tokens are notation fragments. "
                    "The base model Qwen Math 7B is a model name, not a glossary term. "
                    "Distribution cit is a citation artifact. "
                    "The algorithm achieves gains but high likelihood is not enough. "
                    "During sampling the model responds directly until it stops. "
                    "Low-temperature sampling upweights tokens."
                ),
            }
        ]

        candidates = agent._extract_rule_candidates(records)

        self.assertIn("power sampling", candidates)
        self.assertIn("sampling algorithm", candidates)
        self.assertIn("target distribution", candidates)
        self.assertNotIn("our sampling", candidates)
        self.assertNotIn("our sampling algorithm", candidates)
        self.assertNotIn("algorithm ref", candidates)
        self.assertNotIn("that power sampling", candidates)
        self.assertNotIn("while low-temperature sampling", candidates)
        self.assertNotIn("model we", candidates)
        self.assertNotIn("sampling does", candidates)
        self.assertNotIn("distribution p", candidates)
        self.assertNotIn("distribution over", candidates)
        self.assertNotIn("model qwen", candidates)
        self.assertNotIn("model name", candidates)
        self.assertNotIn("distribution cit", candidates)
        self.assertNotIn("algorithm achieves", candidates)
        self.assertNotIn("but high likelihood", candidates)
        self.assertNotIn("during sampling", candidates)
        self.assertNotIn("sampling directly", candidates)
        self.assertNotIn("model responds", candidates)
        self.assertNotIn("model until", candidates)
        self.assertNotIn("sampling upweights", candidates)
        self.assertNotIn("sampling upweights tokens", candidates)

    def test_non_english_candidate_extraction_does_not_use_english_rules(self):
        agent = TerminologyAgent(
            config={"source_language": "de", "target_language": "jp", "llm_config": {}},
            project_dir="paper",
            output_dir="unused",
        )

        candidates = agent._extract_rule_candidates([
            {"part": "sec", "id": "1", "text": "Power sampling appears in an English-looking sentence."}
        ])

        self.assertEqual(candidates, [])


class _FakeLlmTerminologyAgent(TerminologyAgent):
    def _request_llm_for_term_decisions(self, candidates, paper_context, term_contexts, known_terms):
        self.llm_request = {
            "candidates": candidates,
            "paper_context": paper_context,
            "term_contexts": term_contexts,
            "known_terms": known_terms,
        }
        return [
            {
                "source_term": "power sampling",
                "candidate_translations": ["幂采样", "功率采样"],
                "selected_translation": "幂采样",
                "reason": "Uses a power distribution in the paper context.",
            }
        ]


class TerminologyAgentExecuteTests(unittest.TestCase):
    def _write_maps(self, output_dir: Path) -> None:
        (output_dir / "sections_map.json").write_text(
            json.dumps([
                {
                    "section": "0",
                    "content": r"\begin{abstract}We propose power sampling for power distributions.\end{abstract}",
                    "trans_content": "",
                },
                {
                    "section": "1",
                    "content": r"\section{Method} Power sampling uses a power distribution. Power sampling works.",
                    "trans_content": "",
                },
            ]),
            encoding="utf-8",
        )
        (output_dir / "captions_map.json").write_text(
            json.dumps([
                {
                    "placeholder": "<PLACEHOLDER_CAP_1>",
                    "cap_type": "title",
                    "content": r"\title{Reasoning by Sampling}",
                    "trans_content": "",
                }
            ]),
            encoding="utf-8",
        )
        (output_dir / "envs_map.json").write_text("[]", encoding="utf-8")

    def test_execute_writes_project_terms_and_decision_log_with_context(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_dir = Path(tmp_dir)
            self._write_maps(output_dir)
            agent = _FakeLlmTerminologyAgent(
                config={
                    "source_language": "en",
                    "target_language": "ch",
                    "category": {"paper": ["cs.AI"]},
                    "llm_config": {},
                    "terminology": {"max_llm_candidates": 10},
                },
                project_dir="paper",
                output_dir=str(output_dir),
            )

            result = agent.execute()

            terms_content = (output_dir / PROJECT_TERMS_FILENAME).read_text(encoding="utf-8")
            decisions = json.loads((output_dir / PROJECT_TERMS_DECISIONS_FILENAME).read_text(encoding="utf-8"))

        self.assertTrue(result["ok"])
        self.assertIn("Source Term,Target Translation", terms_content)
        self.assertIn("power sampling,幂采样", terms_content)
        self.assertEqual(decisions["source_language"], "en")
        self.assertEqual(decisions["target_language"], "ch")
        self.assertIn("power sampling", agent.llm_request["term_contexts"])
        self.assertIn("abstract", agent.llm_request["paper_context"])
        self.assertEqual(decisions["decisions"][0]["candidate_translations"], ["幂采样", "功率采样"])
        self.assertEqual(decisions["decisions"][0]["selected_translation"], "幂采样")
        self.assertIn("power distribution", decisions["decisions"][0]["reason"])

    def test_execute_ignores_invalid_llm_confirmed_terms(self):
        class InvalidDecisionTerminologyAgent(TerminologyAgent):
            def _request_llm_for_term_decisions(self, candidates, paper_context, term_contexts, known_terms):
                return [
                    {
                        "source_term": "power sampling",
                        "candidate_translations": ["幂采样"],
                        "selected_translation": "幂采样",
                        "reason": "Valid domain term.",
                    },
                    {
                        "source_term": "our sampling",
                        "candidate_translations": ["本文采样"],
                        "selected_translation": "本文采样",
                        "reason": "Invalid context fragment.",
                    },
                ]

        with tempfile.TemporaryDirectory() as tmp_dir:
            output_dir = Path(tmp_dir)
            self._write_maps(output_dir)
            agent = InvalidDecisionTerminologyAgent(
                config={
                    "source_language": "en",
                    "target_language": "ch",
                    "llm_config": {},
                    "terminology": {"max_llm_candidates": 10},
                },
                project_dir="paper",
                output_dir=str(output_dir),
            )

            agent.execute()

            terms_content = (output_dir / PROJECT_TERMS_FILENAME).read_text(encoding="utf-8")

        self.assertIn("power sampling,幂采样", terms_content)
        self.assertNotIn("our sampling,本文采样", terms_content)

    def test_llm_failure_records_failure_and_does_not_write_unconfirmed_candidate(self):
        class FailingTerminologyAgent(TerminologyAgent):
            def _request_llm_for_term_decisions(self, candidates, paper_context, term_contexts, known_terms):
                raise RuntimeError("llm down")

        with tempfile.TemporaryDirectory() as tmp_dir:
            output_dir = Path(tmp_dir)
            self._write_maps(output_dir)
            agent = FailingTerminologyAgent(
                config={
                    "source_language": "en",
                    "target_language": "ch",
                    "llm_config": {},
                    "terminology": {"max_llm_candidates": 10},
                },
                project_dir="paper",
                output_dir=str(output_dir),
            )

            result = agent.execute()
            terms_content = (output_dir / PROJECT_TERMS_FILENAME).read_text(encoding="utf-8")
            decisions = json.loads((output_dir / PROJECT_TERMS_DECISIONS_FILENAME).read_text(encoding="utf-8"))

        self.assertTrue(result["ok"])
        self.assertNotIn("power sampling,", terms_content)
        self.assertEqual(decisions["decisions"][0]["decision_source"], "llm_failed")
        self.assertIn("llm down", decisions["decisions"][0]["reason"])

    def test_request_llm_uses_configured_full_chat_completions_endpoint(self):
        endpoint = "https://api.deepseek.com/chat/completions"
        agent = TerminologyAgent(
            config={
                "source_language": "en",
                "target_language": "ch",
                "llm_config": {
                    "api_key": "test-key",
                    "base_url": endpoint,
                    "model": "deepseek-chat",
                },
            },
            project_dir="paper",
            output_dir="unused",
        )
        captured = {}

        def fake_post(url, **kwargs):
            captured["url"] = url
            return _FakeResponse(json.dumps({
                "decisions": [
                    {
                        "source_term": "power sampling",
                        "candidate_translations": ["幂采样"],
                        "selected_translation": "幂采样",
                        "reason": "Confirmed by context.",
                    }
                ]
            }))

        with patch("src.agents.tool_agents.terminology_agent.requests.post", side_effect=fake_post):
            decisions = agent._request_llm_for_term_decisions(
                ["power sampling"],
                {"title": "Reasoning by Sampling"},
                {"power sampling": ["Power sampling works."]},
                {},
            )

        self.assertEqual(captured["url"], endpoint)
        self.assertEqual(decisions[0]["selected_translation"], "幂采样")

    def test_extract_json_payload_handles_preface_uppercase_fence_and_trailing_text(self):
        agent = TerminologyAgent(
            config={"source_language": "en", "target_language": "ch", "llm_config": {}},
            project_dir="paper",
            output_dir="unused",
        )
        content = (
            "Here is the terminology decision:\n"
            "```JSON\n"
            "{\"decisions\": [{\"source_term\": \"power sampling\", \"selected_translation\": \"幂采样\"}]}\n"
            "```\n"
            "Use these terms consistently."
        )

        payload = agent._extract_json_payload(content)

        self.assertEqual(
            json.loads(payload)["decisions"][0]["source_term"],
            "power sampling",
        )

    def test_invalid_llm_schema_records_failure_decisions(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_dir = Path(tmp_dir)
            self._write_maps(output_dir)
            agent = TerminologyAgent(
                config={
                    "source_language": "en",
                    "target_language": "ch",
                    "llm_config": {
                        "api_key": "test-key",
                        "base_url": "https://api.deepseek.com/chat/completions",
                    },
                    "terminology": {"max_llm_candidates": 10},
                },
                project_dir="paper",
                output_dir=str(output_dir),
            )

            with patch(
                "src.agents.tool_agents.terminology_agent.requests.post",
                return_value=_FakeResponse(json.dumps({"foo": []})),
            ):
                result = agent.execute()

            terms_content = (output_dir / PROJECT_TERMS_FILENAME).read_text(encoding="utf-8")
            decisions = json.loads((output_dir / PROJECT_TERMS_DECISIONS_FILENAME).read_text(encoding="utf-8"))

        self.assertTrue(result["ok"])
        self.assertIn("Source Term,Target Translation", terms_content)
        self.assertNotIn("power sampling,", terms_content)
        self.assertEqual(decisions["decisions"][0]["decision_source"], "llm_failed")
        self.assertIn("decisions", decisions["decisions"][0]["reason"])

    def test_top_level_list_llm_schema_records_failure_decisions(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_dir = Path(tmp_dir)
            self._write_maps(output_dir)
            agent = TerminologyAgent(
                config={
                    "source_language": "en",
                    "target_language": "ch",
                    "llm_config": {
                        "api_key": "test-key",
                        "base_url": "https://api.deepseek.com/chat/completions",
                    },
                    "terminology": {"max_llm_candidates": 10},
                },
                project_dir="paper",
                output_dir=str(output_dir),
            )

            with patch(
                "src.agents.tool_agents.terminology_agent.requests.post",
                return_value=_FakeResponse(json.dumps([{"source_term": "x"}])),
            ):
                result = agent.execute()

            terms_content = (output_dir / PROJECT_TERMS_FILENAME).read_text(encoding="utf-8")
            decisions = json.loads((output_dir / PROJECT_TERMS_DECISIONS_FILENAME).read_text(encoding="utf-8"))

        self.assertTrue(result["ok"])
        self.assertIn("Source Term,Target Translation", terms_content)
        self.assertNotIn("power sampling,", terms_content)
        self.assertEqual(decisions["decisions"][0]["decision_source"], "llm_failed")
        self.assertIn("decisions", decisions["decisions"][0]["reason"])


if __name__ == "__main__":
    unittest.main()
