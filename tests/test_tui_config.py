import tempfile
import unittest
from pathlib import Path

import toml

from src.tui.config import ensure_ui_config, load_ui_config, save_ui_config


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

    def test_template_declares_custom_llm_json(self):
        """模板应提供可编辑的 LLM 自定义 JSON 配置项。"""
        template = Path("config/template.toml").read_text(encoding="utf-8")

        self.assertIn('custom_json = ""', template)


if __name__ == "__main__":
    unittest.main()
