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

    def test_chinese_prompts_include_cjk_latin_spacing_rules(self):
        pm.init_prompts("en", "ch")

        prompt = pm.section_system_prompt

        self.assertIn("Chinese typography spacing", prompt)
        self.assertIn("Common Crawl 的 120B 数学相关 token", prompt)
        self.assertIn("RLVR 使 LLMs", prompt)
        self.assertIn(r"pass@\textit{k}（大 \textit{k} 值）", prompt)
        self.assertIn("Do not insert spaces inside LaTeX command names", prompt)

    def test_non_chinese_prompts_do_not_include_chinese_spacing_rules(self):
        pm.init_prompts("en", "ja")

        self.assertNotIn("Chinese typography spacing", pm.section_system_prompt)

    def test_japanese_prompts_include_japanese_latin_spacing_rules(self):
        pm.init_prompts("en", "ja")

        prompt = pm.section_system_prompt

        self.assertIn("Japanese typography spacing", prompt)
        self.assertIn("GPT-4 は", prompt)
        self.assertIn("LLM の性能", prompt)
        self.assertIn(r"\textit{k} の値", prompt)
        self.assertIn("Do not insert spaces inside LaTeX command names", prompt)

    def test_korean_prompts_include_korean_latin_spacing_rules(self):
        pm.init_prompts("en", "ko")

        prompt = pm.section_system_prompt

        self.assertIn("Korean typography spacing", prompt)
        self.assertIn("LLM 학습", prompt)
        self.assertIn("GPT-4를", prompt)
        self.assertIn("Do not split Korean postpositions attached to Latin terms", prompt)
        self.assertIn("Do not insert spaces inside LaTeX command names", prompt)

    def test_arabic_prompts_include_mixed_script_spacing_rules(self):
        pm.init_prompts("en", "ar")

        prompt = pm.section_system_prompt

        self.assertIn("Arabic mixed-script spacing", prompt)
        self.assertIn("RTL", prompt)
        self.assertIn("Do not reorder mixed Arabic/Latin text", prompt)
        self.assertIn("Do not insert spaces inside LaTeX command names", prompt)

    def test_latin_script_prompts_do_not_include_special_typography_rules(self):
        pm.init_prompts("en", "fr")

        prompt = pm.section_system_prompt

        self.assertNotIn("Chinese typography spacing", prompt)
        self.assertNotIn("Japanese typography spacing", prompt)
        self.assertNotIn("Korean typography spacing", prompt)
        self.assertNotIn("Arabic mixed-script spacing", prompt)

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

    def test_project_terms_are_loaded_for_non_english_chinese_pair(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_dir = Path(tmp_dir)
            (output_dir / "project_terms.csv").write_text(
                "Source Term,Target Translation\nGraphmodell,グラフモデル\n",
                encoding="utf-8",
            )
            agent = TranslatorAgent(
                config={
                    "source_language": "de",
                    "target_language": "jp",
                    "llm_config": {},
                },
                project_dir="paper",
                output_dir=str(output_dir),
            )

            agent.build_term_dict()

        self.assertEqual(agent.term_dict, {"Graphmodell": "グラフモデル"})

    def test_user_terms_override_project_terms(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_dir = Path(tmp_dir) / "output"
            output_dir.mkdir()
            user_terms = Path(tmp_dir) / "user_terms.csv"
            user_terms.write_text("Graph,用户图\n", encoding="utf-8")
            (output_dir / "project_terms.csv").write_text(
                "Source Term,Target Translation\nGraph,项目图\nTree,树\n",
                encoding="utf-8",
            )
            agent = TranslatorAgent(
                config={
                    "source_language": "en",
                    "target_language": "ch",
                    "user_term": str(user_terms),
                    "llm_config": {},
                },
                project_dir="paper",
                output_dir=str(output_dir),
            )

            agent.build_term_dict()

        self.assertEqual(agent.term_dict["Graph"], "用户图")
        self.assertEqual(agent.term_dict["Tree"], "树")

    def test_empty_project_terms_do_not_enable_plain_terms_prompt(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_dir = Path(tmp_dir)
            (output_dir / "project_terms.csv").write_text(
                "Source Term,Target Translation\n",
                encoding="utf-8",
            )
            agent = TranslatorAgent(
                config={
                    "source_language": "de",
                    "target_language": "jp",
                    "llm_config": {},
                },
                project_dir="paper",
                output_dir=str(output_dir),
            )

            agent.build_term_dict()

        self.assertEqual(agent.term_dict, {})
        self.assertFalse(agent._should_use_terms_prompt())

    def test_build_term_dict_does_not_keep_stale_project_terms(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_dir = Path(tmp_dir)
            terms_path = output_dir / "project_terms.csv"
            terms_path.write_text(
                "Source Term,Target Translation\nGraph,图\n",
                encoding="utf-8",
            )
            agent = TranslatorAgent(
                config={
                    "source_language": "en",
                    "target_language": "jp",
                    "llm_config": {},
                },
                project_dir="paper",
                output_dir=str(output_dir),
            )

            agent.build_term_dict()
            terms_path.write_text(
                "Source Term,Target Translation\n",
                encoding="utf-8",
            )
            agent.build_term_dict()

        self.assertNotIn("Graph", agent.term_dict)
        self.assertFalse(agent._project_terms_loaded)

    def test_build_term_dict_preserves_input_placeholder_terms(self):
        agent = TranslatorAgent(
            config={
                "source_language": "de",
                "target_language": "jp",
                "llm_config": {},
            },
            project_dir="paper",
        )
        agent.term_dict = {
            "<PLACEHOLDER_INPUT_begin>": "<PLACEHOLDER_INPUT_begin>",
            "Graph": "旧图",
        }

        agent.build_term_dict()

        self.assertEqual(
            agent.term_dict,
            {"<PLACEHOLDER_INPUT_begin>": "<PLACEHOLDER_INPUT_begin>"},
        )


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
