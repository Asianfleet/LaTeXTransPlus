import os
import tempfile
import unittest
from pathlib import Path

from src.runtime import load_runtime_config


class RuntimeConfigTests(unittest.TestCase):
    def test_load_runtime_config_reads_api_key_from_configured_env_var(self):
        env_name = "LATEXTRANS_TEST_API_KEY"
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "config.toml"
            config_path.write_text(
                """
[llm_config]
model = "test-model"
api_key_env = "LATEXTRANS_TEST_API_KEY"
base_url = "https://example.test/v1/chat/completions"
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
