import os
import tempfile
import unittest
from pathlib import Path

from src.runtime import load_runtime_config


class RuntimeConfigTests(unittest.TestCase):
    def test_load_runtime_config_loads_llm_profile_from_config_directory(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            config_path = root / "config.toml"
            provider_dir = root / "provider"
            provider_dir.mkdir()
            (provider_dir / "siliconflow.toml").write_text(
                """
model = "deepseek-v4-flash"
api_key_env = ""
base_url = "https://example.test/v1/chat/completions"
custom_json = '{"enable_thinking": true}'
""".strip(),
                encoding="utf-8",
            )
            config_path.write_text(
                """
[llm_config]
profile = "siliconflow"
""".strip(),
                encoding="utf-8",
            )

            config = load_runtime_config(str(config_path))

        self.assertEqual(
            config["llm_config"],
            {
                "profile": "siliconflow",
                "model": "deepseek-v4-flash",
                "api_key_env": "",
                "base_url": "https://example.test/v1/chat/completions",
                "custom_json": {"enable_thinking": True},
            },
        )

    def test_load_runtime_config_rejects_legacy_llm_fields(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "config.toml"
            config_path.write_text(
                """
[llm_config]
profile = "provider"
model = "legacy-model"
""".strip(),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "model"):
                load_runtime_config(str(config_path))

    def test_load_runtime_config_rejects_missing_profile_file(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "config.toml"
            config_path.write_text('[llm_config]\nprofile = "missing"', encoding="utf-8")

            with self.assertRaisesRegex(FileNotFoundError, "missing"):
                load_runtime_config(str(config_path))

    def test_load_runtime_config_reads_api_key_from_configured_env_var(self):
        env_name = "LATEXTRANS_TEST_API_KEY"
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "config.toml"
            config_path.write_text(
                """
[llm_config]
profile = "test"
""".strip(),
                encoding="utf-8",
            )
            (Path(tmp_dir) / "provider").mkdir()
            (Path(tmp_dir) / "provider" / "test.toml").write_text(
                """
model = "test-model"
api_key_env = "LATEXTRANS_TEST_API_KEY"
base_url = "https://example.test/v1/chat/completions"
custom_json = ""
""".strip(),
                encoding="utf-8",
            )

            previous = os.environ.get(env_name)
            os.environ[env_name] = "resolved-test-key"
            try:
                config = load_runtime_config(str(config_path))
            finally:
                if previous is None:
                    os.environ.pop(env_name, None)
                else:
                    os.environ[env_name] = previous

        self.assertEqual(config["llm_config"]["api_key"], "resolved-test-key")
        self.assertEqual(config["llm_config"]["api_key_env"], env_name)


if __name__ == "__main__":
    unittest.main()
