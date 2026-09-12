import unittest

from src.engines.base import engine_config, normalize_engine


class EngineConfigTests(unittest.TestCase):
    """Test engine normalization and runtime-facing configuration views."""

    def test_normalize_engine_accepts_only_heavy_and_lite(self):
        """Engine names should be case-insensitive and reject unknown values."""
        self.assertEqual(normalize_engine("heavy"), "heavy")
        self.assertEqual(normalize_engine("LITE"), "lite")

        with self.assertRaisesRegex(ValueError, "heavy.*lite"):
            normalize_engine("unknown")

    def test_normalize_engine_uses_requested_default_for_missing_value(self):
        """Missing values should resolve through the validated default."""
        self.assertEqual(normalize_engine(None, default="lite"), "lite")
        self.assertEqual(normalize_engine("", default="heavy"), "heavy")

    def test_engine_config_merges_heavy_fields_without_mutating_source(self):
        """Heavy settings should be copied into the legacy runtime shape."""
        source = {
            "engine": "lite",
            "source_language": "en",
            "heavy": {
                "tex_sources_dir": "custom-tex",
                "output_dir": "custom-output",
                "paper_list": ["2508.18791"],
                "retranslate_with_terms": True,
                "validation": {"retry": {"max_attempts": 4}},
            },
            "lite": {"output_dir": "custom-lite"},
        }

        effective = engine_config(source, "heavy")
        effective["paper_list"].append("changed")
        effective["validation"]["retry"]["max_attempts"] = 1

        self.assertEqual(effective["engine"], "heavy")
        self.assertEqual(effective["tex_sources_dir"], "custom-tex")
        self.assertEqual(effective["output_dir"], "custom-output")
        self.assertTrue(effective["retranslate_with_terms"])
        self.assertEqual(source["heavy"]["paper_list"], ["2508.18791"])
        self.assertEqual(source["heavy"]["validation"]["retry"]["max_attempts"], 4)

    def test_engine_config_excludes_heavy_runtime_fields_for_lite(self):
        """Lite settings should not expose heavy-only runtime fields."""
        source = {
            "validation": {"legacy": True},
            "tex_sources_dir": "legacy-tex",
            "paper_list": ["legacy"],
            "retranslate_with_terms": True,
            "heavy": {
                "output_dir": "heavy-output",
                "validation": {"retry": {"max_attempts": 4}},
            },
            "lite": {
                "output_dir": "lite-output",
                "validation": {"should_not_leak": True},
            },
        }

        effective = engine_config(source, "lite")

        self.assertEqual(effective["engine"], "lite")
        self.assertEqual(effective["output_dir"], "lite-output")
        for key in ("validation", "tex_sources_dir", "paper_list", "retranslate_with_terms"):
            self.assertNotIn(key, effective)
    def test_engine_config_copies_lite_mineru_api_key_env_but_not_for_heavy(self):
        """The lite MinerU token env var should reach lite runtime config only."""
        source = {
            "heavy": {"output_dir": "heavy-output"},
            "lite": {
                "output_dir": "lite-output",
                "mineru_api_key_env": "CUSTOM_MINERU_TOKEN",
            },
        }

        lite_effective = engine_config(source, "lite")
        heavy_effective = engine_config(source, "heavy")

        self.assertEqual(lite_effective["mineru_api_key_env"], "CUSTOM_MINERU_TOKEN")
        self.assertNotIn("mineru_api_key_env", heavy_effective)

    def test_engine_config_copies_lite_pdf_settings_but_not_for_heavy(self):
        """CJK font candidates and geometry should reach lite runtime config only."""
        source = {
            "heavy": {"output_dir": "heavy-output"},
            "lite": {
                "output_dir": "lite-output",
                "cjk_mainfont_candidates": "SimSun, FandolSong",
                "geometry": "margin=2cm",
            },
        }

        lite_effective = engine_config(source, "lite")
        heavy_effective = engine_config(source, "heavy")

        self.assertEqual(
            lite_effective["cjk_mainfont_candidates"], "SimSun, FandolSong"
        )
        self.assertEqual(lite_effective["geometry"], "margin=2cm")
        self.assertNotIn("cjk_mainfont_candidates", heavy_effective)
        self.assertNotIn("geometry", heavy_effective)


if __name__ == "__main__":
    unittest.main()
