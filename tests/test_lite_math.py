"""Tests for repairing invalid LaTeX superscript chains in lite Markdown math."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.engines.lite_math import (
    normalize_double_superscripts,
    normalize_markdown_math_file,
)


class LiteMathNormalizationTests(unittest.TestCase):
    """Verify math repair stays inside math spans and is idempotent."""

    def test_merges_the_superscript_chain_that_aborted_xelatex(self) -> None:
        """The MinerU prime pattern must collapse into one exponent group."""
        normalized, fixes = normalize_double_superscripts(
            r"$x^{\prime}^{\left(i\right)}$"
        )

        self.assertEqual(fixes, 1)
        self.assertEqual(normalized, r"$x^{\prime\,\left(i\right)}$")

    def test_merges_every_chain_in_the_spaced_mineru_layout(self) -> None:
        """Spaced math produced by the extractor must be repaired as well."""
        text = (
            r"方向 $\lambda _ { X } ^ { \left( i \right) } , x ^ { \prime } ^ { \left( i \right) } ,"
            r" y ^ { \prime } ^ { \left( j \right) }$ 。"
        )
        normalized, fixes = normalize_double_superscripts(text)

        self.assertEqual(fixes, 2)
        self.assertNotIn(r"^ { \prime } ^", normalized)
        self.assertIn(r"^{ \prime \, \left( i \right) }", normalized)

    def test_merges_three_or_more_chained_superscripts(self) -> None:
        """Repeated chained superscripts must keep collapsing until stable."""
        normalized, fixes = normalize_double_superscripts(r"$a^{1}^{2}^{3}$")

        self.assertEqual(fixes, 2)
        self.assertEqual(normalized, r"$a^{1\,2\,3}$")

    def test_repairs_display_math_and_leaves_valid_math_untouched(self) -> None:
        """Display math is repaired while already valid math stays byte-identical."""
        normalized, fixes = normalize_double_superscripts(
            r"$$x^{\prime}^{\left(i\right)}$$ 与 $m _ { 1 } ^ { \prime }$"
        )

        self.assertEqual(fixes, 1)
        self.assertTrue(normalized.startswith(r"$$x^{\prime\,\left(i\right)}$$"))
        self.assertIn(r"$m _ { 1 } ^ { \prime }$", normalized)

    def test_ignores_prose_code_fences_and_code_spans(self) -> None:
        """Non-math text must never be rewritten."""
        text = (
            "正文里的 a^{1}^{2} 不是公式。\n\n"
            "```\n$b^{1}^{2}$\n```\n\n"
            "`$c^{1}^{2}$`\n"
        )
        normalized, fixes = normalize_double_superscripts(text)

        self.assertEqual(fixes, 0)
        self.assertEqual(normalized, text)

    def test_file_helper_rewrites_only_when_repairs_are_needed(self) -> None:
        """The file helper reports its fix count and keeps valid files untouched."""
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "translated.md"
            path.write_text(r"$x^{\prime}^{\left(i\right)}$", encoding="utf-8")

            self.assertEqual(normalize_markdown_math_file(path), 1)
            self.assertEqual(path.read_text(encoding="utf-8"), r"$x^{\prime\,\left(i\right)}$")
            self.assertEqual(normalize_markdown_math_file(path), 0)

            valid = Path(temp_dir) / "valid.md"
            valid.write_text("# 标题\n\n正文。\n", encoding="utf-8")
            self.assertEqual(normalize_markdown_math_file(valid), 0)
            self.assertEqual(valid.read_text(encoding="utf-8"), "# 标题\n\n正文。\n")


if __name__ == "__main__":
    unittest.main()
