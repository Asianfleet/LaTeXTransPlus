import unittest

from src.tui.config_schema import (
    CONFIG_FIELDS,
    grouped_config_fields,
    normalized_config_from_form,
)


class TuiConfigSchemaTests(unittest.TestCase):
    """测试 TUI 配置 schema 与新的 LLM profile 配置契约。"""

    def test_llm_section_contains_only_profile_field(self):
        llm_fields = [field for field in CONFIG_FIELDS if field.section == "LLM"]

        self.assertEqual([field.path for field in llm_fields], [("llm_config", "profile")])
        self.assertEqual(llm_fields[0].label, "LLM 配置 profile")
        self.assertEqual(llm_fields[0].kind, "input")

    def test_grouped_fields_preserve_llm_profile_section(self):
        sections = dict(grouped_config_fields())

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


if __name__ == "__main__":
    unittest.main()
