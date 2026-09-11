import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import main as cli_main


class MainHeavyEngineConfigTests(unittest.TestCase):
    def test_cli_flattens_nested_heavy_config_before_runtime_boundaries(self):
        """CLI passes the effective heavy configuration to both runtime boundaries."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            config_path = root / "config.toml"
            provider_dir = root / "provider"
            provider_dir.mkdir()
            (provider_dir / "test.toml").write_text(
                """
model = "test-model"
api_key_env = ""
base_url = "https://example.test/v1/chat/completions"
custom_json = ""
""".strip(),
                encoding="utf-8",
            )
            config_path.write_text(
                """
target_language = "ch"

[llm_config]
profile = "test"

[heavy]
paper_list = ["configured-paper"]
tex_sources_dir = "configured-source"
output_dir = "configured-output"
retranslate_with_terms = false

[heavy.validation.retry]
max_attempts = 7
""".strip(),
                encoding="utf-8",
            )
            captured_configs = []

            def fake_prepare_projects(*, config, **_kwargs):
                """Capture the config without executing input preparation."""
                captured_configs.append(config)
                return [], config, "projects", "cli-output"

            argv = [
                "latextrans",
                "--config",
                str(config_path),
                "--arxiv",
                "cli-paper",
                "--source",
                "cli-source",
                "--output",
                "cli-output",
                "--retranslate-with-terms",
            ]
            with patch.object(sys, "argv", argv):
                with patch(
                    "main.runtime.prepare_projects",
                    side_effect=fake_prepare_projects,
                ):
                    with patch(
                        "main.runtime.run_projects",
                        return_value={"completed_projects": [], "failed_projects": []},
                    ) as run_projects:
                        cli_main.main()

        expected = {
            "paper_list": ["configured-paper", "cli-paper"],
            "tex_sources_dir": "cli-source",
            "output_dir": "cli-output",
            "retranslate_with_terms": True,
            "validation": {"retry": {"max_attempts": 7}},
        }
        observed = {
            key: captured_configs[0].get(key)
            for key in expected
        }
        self.assertEqual(observed, expected)
        self.assertEqual(run_projects.call_args.kwargs["config"], captured_configs[0])


if __name__ == "__main__":
    unittest.main()
