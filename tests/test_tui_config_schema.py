import unittest

from src.engines.lite_fonts import DEFAULT_CJK_FONT_CANDIDATES
from src.tui.config_schema import (
    CONFIG_FIELDS,
    FONT_HINT_LANGUAGE_BY_KIND,
    config_fields_for_engine,
    form_text_for_field,
    grouped_config_fields,
    normalized_config_from_form,
    parse_font_family_value,
    parse_font_list_value,
    parse_textarea_value,
)


class TuiConfigSchemaTests(unittest.TestCase):
    """测试 TUI 配置 schema、引擎字段过滤与表单转换。"""

    def test_llm_section_contains_only_profile_field(self):
        llm_fields = [field for field in CONFIG_FIELDS if field.section == "LLM"]

        self.assertEqual([field.path for field in llm_fields], [("llm_config", "profile")])
        self.assertEqual(llm_fields[0].label, "LLM 配置 profile")
        self.assertEqual(llm_fields[0].kind, "input")

    def test_grouped_fields_preserve_llm_profile_section(self):
        sections = dict(grouped_config_fields("heavy"))

        self.assertEqual([field.path for field in sections["LLM"]], [("llm_config", "profile")])

    def test_normalized_form_removes_legacy_llm_fields(self):
        config = {
            "llm_config": {
                "profile": "deepseek",
                "model": "legacy-model",
                "api_key_env": "LEGACY_KEY",
                "base_url": "https://legacy.example",
                "custom_json": "",
            }
        }

        normalized = normalized_config_from_form(
            config,
            {
                **{field.path: field.default for field in CONFIG_FIELDS},
                ("llm_config", "profile"): "qwen",
            },
        )

        self.assertEqual(normalized["llm_config"], {"profile": "qwen"})

    def test_engine_field_is_shared_and_selectable(self):
        """Every settings form should expose the persisted engine selector."""
        fields = config_fields_for_engine("heavy")
        engine_field = next(field for field in fields if field.path == ("engine",))

        self.assertEqual(engine_field.kind, "select")
        self.assertEqual({value for _label, value in engine_field.options}, {"heavy", "lite"})

    def test_heavy_fields_include_runtime_and_validation_settings(self):
        """Heavy forms should include heavy paths and exclude lite paths."""
        paths = {field.path for field in config_fields_for_engine("heavy")}

        self.assertIn(("heavy", "tex_sources_dir"), paths)
        self.assertIn(("heavy", "output_dir"), paths)
        self.assertIn(("heavy", "paper_list"), paths)
        self.assertIn(("heavy", "retranslate_with_terms"), paths)
        self.assertIn(("heavy", "validation", "retry", "max_attempts"), paths)
        self.assertNotIn(("lite", "output_dir"), paths)

    def test_lite_fields_exclude_all_heavy_only_settings(self):
        """Lite forms should contain its output path but no heavy validation fields."""
        paths = {field.path for field in config_fields_for_engine("lite")}

        self.assertIn(("engine",), paths)
        self.assertIn(("source_language",), paths)
        self.assertIn(("lite", "output_dir"), paths)
        self.assertIn(("lite", "mineru_api_key_env"), paths)
        self.assertFalse(any(path[0] == "heavy" for path in paths))
        self.assertFalse(any("validation" in path for path in paths))

    def test_lite_mineru_api_key_env_field_defaults_to_mineru_token(self):
        """The lite MinerU token env field should default to ``MINERU_TOKEN``."""
        field = next(
            field
            for field in config_fields_for_engine("lite")
            if field.path == ("lite", "mineru_api_key_env")
        )

        self.assertEqual(field.kind, "input")
        self.assertEqual(field.default, "MINERU_TOKEN")

    def test_grouped_fields_filter_for_selected_engine(self):
        """Grouped fields should preserve sections after engine filtering."""
        sections = dict(grouped_config_fields("lite"))
        all_paths = {field.path for fields in sections.values() for field in fields}

        self.assertIn(("lite", "output_dir"), all_paths)
        self.assertNotIn("校验", sections)

    def test_normalized_form_preserves_unshown_engine_values(self):
        """Saving a lite form should not overwrite hidden heavy settings."""
        config = {
            "engine": "heavy",
            "heavy": {"output_dir": "keep-heavy", "validation": {"retry": {"max_attempts": 7}}},
            "lite": {"output_dir": "old-lite"},
            "llm_config": {"profile": "default", "model": "legacy"},
        }
        values = {
            field.path: ("new-lite" if field.path == ("lite", "output_dir") else field.default)
            for field in config_fields_for_engine("lite")
        }

        normalized = normalized_config_from_form(config, values)

        self.assertEqual(normalized["heavy"]["output_dir"], "keep-heavy")
        self.assertEqual(normalized["heavy"]["validation"]["retry"]["max_attempts"], 7)
        self.assertEqual(normalized["lite"]["output_dir"], "new-lite")

    def test_lite_pdf_fields_use_the_font_list_kind_and_a_pdf_section(self):
        """Font fields and geometry belong to lite's PDF settings group."""
        fields = {field.path: field for field in config_fields_for_engine("lite")}

        font_field = fields[("lite", "cjk_mainfont_candidates")]
        self.assertEqual(font_field.kind, "font_list")
        self.assertEqual(font_field.section, "PDF")
        self.assertEqual(font_field.default, DEFAULT_CJK_FONT_CANDIDATES)
        self.assertEqual(fields[("lite", "mainfont")].kind, "font_family")
        self.assertEqual(fields[("lite", "mainfont")].default, "")
        self.assertEqual(fields[("lite", "geometry")].kind, "input")
        self.assertEqual(fields[("lite", "geometry")].default, "")

        sections = dict(grouped_config_fields("lite"))
        self.assertEqual(
            [field.path for field in sections["PDF"]],
            [
                ("lite", "mainfont"),
                ("lite", "cjk_mainfont_candidates"),
                ("lite", "geometry"),
            ],
        )
        self.assertNotIn("PDF", dict(grouped_config_fields("heavy")))

    def test_font_fields_declare_which_families_their_hint_lists(self):
        """The CJK field lists CJK fonts while the body font lists every family."""
        self.assertEqual(FONT_HINT_LANGUAGE_BY_KIND["font_list"], "zh")
        self.assertIsNone(FONT_HINT_LANGUAGE_BY_KIND["font_family"])
        for field in config_fields_for_engine("lite"):
            self.assertEqual(
                field.kind in FONT_HINT_LANGUAGE_BY_KIND,
                field.path[-1] in {"mainfont", "cjk_mainfont_candidates"},
            )

    def test_font_list_values_are_normalized_into_a_comma_separated_string(self):
        """Saving a font list should dedupe and re-join the family names."""
        field = next(
            field
            for field in config_fields_for_engine("lite")
            if field.path == ("lite", "cjk_mainfont_candidates")
        )

        self.assertEqual(
            parse_font_list_value(field, " SimSun ,FandolSong, simsun "),
            "SimSun, FandolSong",
        )
        self.assertEqual(parse_font_list_value(field, "   "), "")
        with self.assertRaisesRegex(ValueError, "中文字体候选"):
            parse_font_list_value(field, " , ,")

    def test_font_family_values_collapse_whitespace_and_reject_lists(self):
        """A body font is a single name, not a comma-separated candidate list."""
        field = next(
            field
            for field in config_fields_for_engine("lite")
            if field.path == ("lite", "mainfont")
        )

        self.assertEqual(parse_font_family_value(field, "  Times   New Roman "), "Times New Roman")
        self.assertEqual(parse_font_family_value(field, "   "), "")
        with self.assertRaisesRegex(ValueError, "正文字体"):
            parse_font_family_value(field, "Times New Roman, DejaVu Serif")

    def test_paper_list_textarea_round_trips_an_empty_list(self):
        """Paper-list text should retain its JSON array type when empty."""
        field = next(
            field
            for field in config_fields_for_engine("heavy")
            if field.path == ("heavy", "paper_list")
        )

        text = form_text_for_field(field, {"heavy": {"paper_list": []}})

        self.assertEqual(text, "[]")
        self.assertEqual(parse_textarea_value(field, text), [])


if __name__ == "__main__":
    unittest.main()
