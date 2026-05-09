import json
import tempfile
import unittest
from pathlib import Path

from src.terminology import (
    PROJECT_TERMS_FILENAME,
    TerminologyConfig,
    casefold_language,
    load_term_csv,
    merge_term_pairs,
    project_terms_path,
    require_retranslation_inputs,
    write_project_terms_csv,
)


class TerminologyConfigTests(unittest.TestCase):
    def test_defaults_are_enabled_without_config(self):
        config = TerminologyConfig.from_config({})

        self.assertTrue(config.enabled)
        self.assertFalse(config.review_before_translate)
        self.assertEqual(config.max_llm_candidates, 30)

    def test_none_config_uses_defaults(self):
        config = TerminologyConfig.from_config(None)

        self.assertTrue(config.enabled)
        self.assertFalse(config.review_before_translate)
        self.assertEqual(config.max_llm_candidates, 30)

    def test_config_values_can_be_overridden(self):
        config = TerminologyConfig.from_config({
            "terminology": {
                "enabled": False,
                "review_before_translate": True,
                "max_llm_candidates": 5,
            }
        })

        self.assertFalse(config.enabled)
        self.assertTrue(config.review_before_translate)
        self.assertEqual(config.max_llm_candidates, 5)

    def test_invalid_max_llm_candidates_raises(self):
        with self.assertRaisesRegex(ValueError, "max_llm_candidates"):
            TerminologyConfig.from_config({
                "terminology": {"max_llm_candidates": -1}
            })

    def test_bool_max_llm_candidates_raises(self):
        with self.assertRaisesRegex(ValueError, "max_llm_candidates"):
            TerminologyConfig.from_config({
                "terminology": {"max_llm_candidates": True}
            })

    def test_non_bool_enabled_raises(self):
        with self.assertRaisesRegex(ValueError, "enabled"):
            TerminologyConfig.from_config({
                "terminology": {"enabled": "true"}
            })

    def test_non_bool_review_before_translate_raises(self):
        with self.assertRaisesRegex(ValueError, "review_before_translate"):
            TerminologyConfig.from_config({
                "terminology": {"review_before_translate": "false"}
            })


class TermCsvTests(unittest.TestCase):
    def test_load_term_csv_with_header_and_bad_rows(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            term_path = Path(tmp_dir) / PROJECT_TERMS_FILENAME
            term_path.write_text(
                "Source Term,Target Translation\n"
                "Graph,グラフ\n"
                "\n"
                "bad-only-one-column\n"
                "Model,モデル\n",
                encoding="utf-8",
            )

            result = load_term_csv(term_path, source_language="en")

        self.assertEqual(result.terms, {"Graph": "グラフ", "Model": "モデル"})
        self.assertEqual(len(result.warnings), 1)
        self.assertIn("bad-only-one-column", result.warnings[0])

    def test_load_term_csv_without_header(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            term_path = Path(tmp_dir) / PROJECT_TERMS_FILENAME
            term_path.write_text("Graph,グラフ\n", encoding="utf-8")

            result = load_term_csv(term_path, source_language="en")

        self.assertEqual(result.terms, {"Graph": "グラフ"})

    def test_load_term_csv_rejects_extra_columns(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            term_path = Path(tmp_dir) / PROJECT_TERMS_FILENAME
            term_path.write_text(
                "Source Term,Target Translation\n"
                "Graph,图,extra\n"
                "Model,模型\n",
                encoding="utf-8",
            )

            result = load_term_csv(term_path, source_language="en")

        self.assertEqual(result.terms, {"Model": "模型"})
        self.assertEqual(len(result.warnings), 1)
        self.assertIn("Graph,图,extra", result.warnings[0])

    def test_load_term_csv_header_allows_bom_and_spaces(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            term_path = Path(tmp_dir) / PROJECT_TERMS_FILENAME
            term_path.write_text(
                "\ufeff Source Term , Target Translation \n"
                "Graph,グラフ\n",
                encoding="utf-8",
            )

            result = load_term_csv(term_path, source_language="en")

        self.assertEqual(result.terms, {"Graph": "グラフ"})

    def test_load_term_csv_header_is_case_insensitive_with_bom_and_spaces(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            term_path = Path(tmp_dir) / PROJECT_TERMS_FILENAME
            term_path.write_text(
                "\ufeff source term , target translation \n"
                "Graph,グラフ\n",
                encoding="utf-8",
            )

            result = load_term_csv(term_path, source_language="en")

        self.assertEqual(result.terms, {"Graph": "グラフ"})
        self.assertEqual(result.warnings, [])

    def test_casefold_language_for_latin_but_not_cjk(self):
        self.assertEqual(casefold_language("Graph", "en"), "graph")
        self.assertEqual(casefold_language("Graph", "de"), "graph")
        self.assertEqual(casefold_language("グラフ", "jp"), "グラフ")
        self.assertEqual(casefold_language("图模型", "ch"), "图模型")

    def test_casefold_language_without_source_language_leaves_term_unchanged(self):
        self.assertEqual(casefold_language("Graph", None), "Graph")

    def test_merge_term_pairs_preserves_higher_priority(self):
        merged = merge_term_pairs(
            [("Graph", "用户图")],
            [("graph", "项目图")],
            [("Tree", "树")],
            source_language="en",
        )

        self.assertEqual(merged, {"Graph": "用户图", "Tree": "树"})

    def test_merge_term_pairs_skips_empty_source_or_target(self):
        merged = merge_term_pairs(
            [("", "空源"), ("Graph", ""), ("Model", "模型")],
            source_language="en",
        )

        self.assertEqual(merged, {"Model": "模型"})

    def test_write_project_terms_csv_uses_source_target_header(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            term_path = Path(tmp_dir) / PROJECT_TERMS_FILENAME
            write_project_terms_csv(term_path, {"Graph": "グラフ", "Model": "モデル"})

            content = term_path.read_text(encoding="utf-8")

        self.assertIn("Source Term,Target Translation", content)
        self.assertIn("Graph,グラフ", content)


class RetranslationInputTests(unittest.TestCase):
    def test_require_retranslation_inputs_returns_paths_when_present(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_dir = Path(tmp_dir)
            for name in [
                "sections_map.json",
                "captions_map.json",
                "envs_map.json",
                "inputs_map.json",
                "newcommands_map.json",
                PROJECT_TERMS_FILENAME,
            ]:
                (output_dir / name).write_text("[]" if name.endswith(".json") else "Graph,图\n", encoding="utf-8")

            result = require_retranslation_inputs(output_dir)

        self.assertEqual(result.project_terms_path.name, PROJECT_TERMS_FILENAME)
        self.assertTrue(result.sections_path.name.endswith("sections_map.json"))
        self.assertEqual(result.inputs_path.name, "inputs_map.json")
        self.assertEqual(result.newcommands_path.name, "newcommands_map.json")

    def test_require_retranslation_inputs_raises_for_missing_project_terms(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_dir = Path(tmp_dir)
            for name in [
                "sections_map.json",
                "captions_map.json",
                "envs_map.json",
                "inputs_map.json",
                "newcommands_map.json",
            ]:
                (output_dir / name).write_text("[]", encoding="utf-8")

            with self.assertRaisesRegex(FileNotFoundError, "project_terms.csv"):
                require_retranslation_inputs(output_dir)

    def test_require_retranslation_inputs_raises_for_missing_inputs_map_for_full_retranslation(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_dir = Path(tmp_dir)
            for name in [
                "sections_map.json",
                "captions_map.json",
                "envs_map.json",
                "newcommands_map.json",
                PROJECT_TERMS_FILENAME,
            ]:
                (output_dir / name).write_text("[]" if name.endswith(".json") else "Graph,图\n", encoding="utf-8")

            with self.assertRaisesRegex(FileNotFoundError, "inputs_map.json"):
                require_retranslation_inputs(output_dir)

    def test_require_retranslation_inputs_raises_for_missing_newcommands_map_for_full_retranslation(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_dir = Path(tmp_dir)
            for name in [
                "sections_map.json",
                "captions_map.json",
                "envs_map.json",
                "inputs_map.json",
                PROJECT_TERMS_FILENAME,
            ]:
                (output_dir / name).write_text("[]" if name.endswith(".json") else "Graph,图\n", encoding="utf-8")

            with self.assertRaisesRegex(FileNotFoundError, "newcommands_map.json"):
                require_retranslation_inputs(output_dir)

    def test_require_retranslation_inputs_raises_when_input_is_directory(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_dir = Path(tmp_dir)
            for name in [
                "sections_map.json",
                "captions_map.json",
                "envs_map.json",
                "inputs_map.json",
                "newcommands_map.json",
                PROJECT_TERMS_FILENAME,
            ]:
                (output_dir / name).mkdir()

            with self.assertRaises(FileNotFoundError):
                require_retranslation_inputs(output_dir)

    def test_require_retranslation_inputs_raises_when_output_dir_missing(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_dir = Path(tmp_dir) / "missing"

            with self.assertRaises(FileNotFoundError):
                require_retranslation_inputs(output_dir)

    def test_project_terms_path_uses_output_dir(self):
        self.assertEqual(
            project_terms_path(Path("outputs") / "ch_paper"),
            Path("outputs") / "ch_paper" / PROJECT_TERMS_FILENAME,
        )


if __name__ == "__main__":
    unittest.main()
