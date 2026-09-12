"""Tests for lite-engine font detection and CJK font candidate resolution."""

from __future__ import annotations

import subprocess
import unittest
from unittest.mock import patch

from src.engines.lite_fonts import (
    DEFAULT_CJK_FONT_CANDIDATES,
    list_available_font_families,
    parse_font_candidates,
    resolve_cjk_mainfont,
    resolve_mainfont,
)


class FakeFcListRunner:
    """Return deterministic fontconfig output while recording its command."""

    def __init__(self, stdout: str, returncode: int = 0, error: OSError | None = None) -> None:
        """Store the fake process result."""
        self.stdout = stdout
        self.returncode = returncode
        self.error = error
        self.command: list[str] = []

    def __call__(self, command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        """Record the command and return the configured result."""
        self.command = command
        if self.error is not None:
            raise self.error
        return subprocess.CompletedProcess(command, self.returncode, self.stdout, "")


class FontCandidateParsingTests(unittest.TestCase):
    """Verify the comma-separated font setting is parsed predictably."""

    def test_splits_commas_and_collapses_whitespace(self) -> None:
        """Whitespace and duplicates must not survive into the candidate list."""
        self.assertEqual(
            parse_font_candidates("  SimSun ,Microsoft   YaHei, Noto Serif SC "),
            ["SimSun", "Microsoft YaHei", "Noto Serif SC"],
        )

    def test_deduplicates_case_insensitively_while_keeping_order(self) -> None:
        """A repeated family must keep only its first occurrence."""
        self.assertEqual(
            parse_font_candidates("SimSun, noto serif sc, SIMSUN"),
            ["SimSun", "noto serif sc"],
        )

    def test_accepts_list_values_and_empty_input(self) -> None:
        """Configuration lists and blank settings must both be tolerated."""
        self.assertEqual(parse_font_candidates(["FandolSong", "FandolSong"]), ["FandolSong"])
        self.assertEqual(parse_font_candidates(None), [])
        self.assertEqual(parse_font_candidates(""), [])
        self.assertEqual(parse_font_candidates(" , ,"), [])


class AvailableFontListingTests(unittest.TestCase):
    """Verify fontconfig output parsing and failure handling."""

    def test_parses_families_and_localized_aliases(self) -> None:
        """Each comma-separated family from fontconfig must be listed once."""
        runner = FakeFcListRunner(
            "SimSun,宋体\nMicrosoft YaHei,微软雅黑\nFandolSong\n宋体\n"
        )

        with patch("src.engines.lite_fonts.shutil.which", return_value="fc-list"):
            families = list_available_font_families(runner=runner)

        self.assertEqual(
            sorted(families, key=str.casefold),
            sorted(
                ["SimSun", "宋体", "Microsoft YaHei", "微软雅黑", "FandolSong"],
                key=str.casefold,
            ),
        )
        self.assertEqual(families, sorted(families, key=str.casefold))
        self.assertIn(":lang=zh", runner.command)

    def test_lists_every_family_when_no_language_filter_is_given(self) -> None:
        """A mainfont listing must not be restricted to CJK-capable families."""
        runner = FakeFcListRunner("Latin Only\nTimes New Roman\n")

        with patch("src.engines.lite_fonts.shutil.which", return_value="fc-list"):
            families = list_available_font_families(language=None, runner=runner)

        self.assertEqual(families, ["Latin Only", "Times New Roman"])
        self.assertEqual(runner.command[-2:], [":", "family"])

    def test_returns_empty_list_when_fontconfig_is_unavailable(self) -> None:
        """Missing fc-list, a failing query, and OSErrors all mean "cannot detect"."""
        with patch("src.engines.lite_fonts.shutil.which", return_value=None):
            self.assertEqual(list_available_font_families(runner=FakeFcListRunner("")), [])

        with patch("src.engines.lite_fonts.shutil.which", return_value="fc-list"):
            self.assertEqual(
                list_available_font_families(runner=FakeFcListRunner("SimSun", returncode=1)),
                [],
            )
            self.assertEqual(
                list_available_font_families(
                    runner=FakeFcListRunner("", error=FileNotFoundError("fc-list"))
                ),
                [],
            )


class MainFontResolutionTests(unittest.TestCase):
    """Verify a single body-font name is resolved against the font database."""

    def test_returns_the_canonical_spelling_of_an_installed_family(self) -> None:
        """Matching is case-insensitive while the reported spelling is used."""
        with patch(
            "src.engines.lite_fonts.list_available_font_families",
            return_value=["Times New Roman", "DejaVu Serif"],
        ):
            self.assertEqual(resolve_mainfont("times new roman"), "Times New Roman")
            self.assertIsNone(resolve_mainfont("Missing Font"))

    def test_blank_values_resolve_to_no_font(self) -> None:
        """An unset or whitespace-only setting means "keep the Pandoc default"."""
        self.assertIsNone(resolve_mainfont(""))
        self.assertIsNone(resolve_mainfont("   "))
        self.assertIsNone(resolve_mainfont(None))

    def test_keeps_the_configured_name_when_no_font_database_is_available(self) -> None:
        """Without fontconfig the configured name is passed through unchanged."""
        with patch(
            "src.engines.lite_fonts.list_available_font_families", return_value=[]
        ):
            self.assertEqual(resolve_mainfont(" Times  New Roman "), "Times New Roman")


class CjkFontResolutionTests(unittest.TestCase):
    """Verify candidate order decides which font the PDF run uses."""

    def test_selects_the_first_installed_candidate(self) -> None:
        """Candidate order must win over the order fontconfig reports."""
        self.assertEqual(
            resolve_cjk_mainfont(
                ["SimSun", "FandolSong"],
                available=["FandolSong", "SimSun"],
            ),
            "SimSun",
        )

    def test_skips_missing_candidates_and_reports_none_when_nothing_matches(self) -> None:
        """An uninstalled candidate must fall through to the next one."""
        self.assertEqual(
            resolve_cjk_mainfont(
                ["Noto Sans CJK SC", "FandolSong"],
                available=["FandolSong"],
            ),
            "FandolSong",
        )
        self.assertIsNone(
            resolve_cjk_mainfont(["Noto Sans CJK SC"], available=["FandolSong"])
        )

    def test_matches_localized_aliases_and_ignores_case(self) -> None:
        """fontconfig family aliases are usable spellings for CJK fonts."""
        self.assertEqual(
            resolve_cjk_mainfont(["宋体"], available=["SimSun", "宋体"]),
            "宋体",
        )
        self.assertEqual(resolve_cjk_mainfont(["fandolsong"], available=["FandolSong"]), "FandolSong")

    def test_falls_back_to_the_first_candidate_without_a_font_listing(self) -> None:
        """A machine without fontconfig still gets a best-effort font name."""
        self.assertEqual(resolve_cjk_mainfont(["SimSun"], available=[]), "SimSun")
        self.assertIsNone(resolve_cjk_mainfont([], available=["SimSun"]))

    def test_default_candidates_start_with_a_windows_and_a_portable_font(self) -> None:
        """The shipped default order should work on Windows and on TeX Live alone."""
        candidates = parse_font_candidates(DEFAULT_CJK_FONT_CANDIDATES)

        self.assertEqual(candidates[0], "SimSun")
        self.assertIn("FandolSong", candidates)


if __name__ == "__main__":
    unittest.main()
