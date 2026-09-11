import tempfile
import unittest
from pathlib import Path

import toml

from src.tui.config import ensure_ui_config, load_ui_config, migrate_ui_config, save_ui_config


class TuiConfigTests(unittest.TestCase):
    """测试 TUI 专用配置文件的初始化、加载和保存行为。"""

    def test_ensure_ui_config_copies_default_when_present(self):
        """当 default.toml 存在时，应优先复制为 UI 配置。"""
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            config_dir = root / "config"
            config_dir.mkdir()
            (config_dir / "default.toml").write_text('target_language = "ja"\n', encoding="utf-8")
            (config_dir / "template.toml").write_text('target_language = "ch"\n', encoding="utf-8")

            path = ensure_ui_config(root)

            self.assertEqual(path, config_dir / "ui.toml")
            self.assertEqual(toml.load(path)["target_language"], "ja")

    def test_ensure_ui_config_uses_template_when_default_missing(self):
        """当 default.toml 缺失时，应使用 template.toml 初始化 UI 配置。"""
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            config_dir = root / "config"
            config_dir.mkdir()
            (config_dir / "template.toml").write_text('target_language = "ko"\n', encoding="utf-8")

            path = ensure_ui_config(root)

            self.assertEqual(toml.load(path)["target_language"], "ko")

    def test_load_and_save_ui_config_round_trip(self):
        """保存后的 UI 配置应可从同一路径完整读回。"""
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            config_dir = root / "config"
            config_dir.mkdir()
            (config_dir / "template.toml").write_text('target_language = "ch"\n', encoding="utf-8")

            saved_path = save_ui_config(root, {"target_language": "fr", "ui": {"dark": True}})
            loaded = load_ui_config(root)

            self.assertEqual(saved_path, config_dir / "ui.toml")
            self.assertEqual(loaded["target_language"], "fr")
            self.assertTrue(loaded["ui"]["dark"])

    def test_template_declares_llm_profile(self):
        """模板应提供 LLM profile 配置项。"""
        template = Path("config/template.toml").read_text(encoding="utf-8")

        self.assertIn('profile = "default"', template)

    def test_legacy_config_moves_heavy_fields_and_adds_lite_defaults(self):
        """Legacy heavy fields should migrate without losing user values."""
        legacy = {
            "source_language": "en",
            "tex_sources_dir": "old-tex",
            "output_dir": "old-output",
            "paper_list": ["2508.18791"],
            "retranslate_with_terms": True,
            "validation": {"retry": {"max_attempts": 4}},
        }

        migrated = migrate_ui_config(legacy)

        self.assertEqual(migrated["engine"], "heavy")
        self.assertEqual(migrated["heavy"]["tex_sources_dir"], "old-tex")
        self.assertEqual(migrated["heavy"]["output_dir"], "old-output")
        self.assertEqual(migrated["heavy"]["paper_list"], ["2508.18791"])
        self.assertTrue(migrated["heavy"]["retranslate_with_terms"])
        self.assertEqual(migrated["heavy"]["validation"]["retry"]["max_attempts"], 4)
        self.assertEqual(migrated["lite"]["output_dir"], "output-lite")
        self.assertEqual(migrated["lite"]["mineru_api_key_env"], "MINERU_TOKEN")
        self.assertEqual(legacy["output_dir"], "old-output")
        for key in ("tex_sources_dir", "output_dir", "paper_list", "retranslate_with_terms", "validation"):
            self.assertNotIn(key, migrated)

    def test_migration_preserves_existing_nested_engine_values(self):
        """Existing engine sections should win over legacy duplicates and defaults."""
        legacy = {
            "output_dir": "legacy-output",
            "heavy": {"output_dir": "nested-output", "tex_sources_dir": "nested-tex"},
            "lite": {"output_dir": "nested-lite"},
        }

        migrated = migrate_ui_config(legacy)

        self.assertEqual(migrated["heavy"]["output_dir"], "nested-output")
        self.assertEqual(migrated["heavy"]["tex_sources_dir"], "nested-tex")
        self.assertEqual(migrated["lite"]["output_dir"], "nested-lite")

    def test_load_ui_config_persists_legacy_migration(self):
        """Loading a legacy UI file should migrate and persist it once."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            config_dir = root / "config"
            config_dir.mkdir()
            ui_path = config_dir / "ui.toml"
            ui_path.write_text(
                'source_language = "en"\noutput_dir = "kept-output"\ntex_sources_dir = "kept-tex"\n',
                encoding="utf-8",
            )

            loaded = load_ui_config(root)
            persisted = toml.load(ui_path)

            self.assertEqual(loaded["heavy"]["output_dir"], "kept-output")
            self.assertEqual(loaded["heavy"]["tex_sources_dir"], "kept-tex")
            self.assertEqual(persisted, loaded)

    def test_ensure_ui_config_does_not_rewrite_modern_file(self):
        """A modern UI config should retain its exact formatting and comments."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            config_dir = root / "config"
            config_dir.mkdir()
            ui_path = config_dir / "ui.toml"
            original = '# retain this comment\nengine = "lite"\n\n[heavy]\noutput_dir = "h"\n\n[lite]\noutput_dir = "l"\n'
            ui_path.write_text(original, encoding="utf-8")

            self.assertEqual(ensure_ui_config(root), ui_path)
            self.assertEqual(ui_path.read_text(encoding="utf-8"), original)

    def test_project_configs_use_nested_engine_sections(self):
        """Default and template configs should expose the same engine layout."""
        for path in (Path("config/default.toml"), Path("config/template.toml")):
            with self.subTest(path=path):
                config = toml.load(path)
                self.assertEqual(config["engine"], "heavy")
                self.assertIn("validation", config["heavy"])
                self.assertEqual(config["lite"]["output_dir"], "output-lite")
                self.assertEqual(config["lite"]["mineru_api_key_env"], "MINERU_TOKEN")
                for key in ("tex_sources_dir", "output_dir", "paper_list", "retranslate_with_terms", "validation"):
                    self.assertNotIn(key, config)


if __name__ == "__main__":
    unittest.main()
