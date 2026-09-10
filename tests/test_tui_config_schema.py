import unittest

from src.tui.config_schema import (
    CONFIG_FIELDS,
    config_fields_for_engine,
    form_text_for_field,
    grouped_config_fields,
    normalized_config_from_form,
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
        self.assertFalse(any(path[0] == "heavy" for path in paths))
        self.assertFalse(any("validation" in path for path in paths))

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
