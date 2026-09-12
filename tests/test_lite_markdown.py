"""Tests for lite-engine Markdown splitting and structure protection."""

import unittest

from src.engines.lite_markdown import (
    MarkdownBlock,
    ProtectedTokenValidationError,
    protect_markdown,
    rebuild_markdown,
    restore_markdown,
    split_markdown,
)


class MarkdownBlockTests(unittest.TestCase):
    """Verify stateful second-level heading scanning and ordered rebuilding."""

    def test_splits_before_first_heading_and_at_second_level_headings_only(self):
        """Keep preamble and child headings in their original logical blocks."""
        source = "front\n\n## First\nbody\n### Child\nchild\n\n## Second\nbody2"

        blocks = split_markdown(source)

        self.assertEqual(len(blocks), 3)
        self.assertEqual(blocks[0].text, "front\n\n")
        self.assertIn("## First", blocks[1].text)
        self.assertIn("### Child", blocks[1].text)
        self.assertIn("## Second", blocks[2].text)
        self.assertEqual([block.index for block in blocks], [0, 1, 2])

    def test_heading_inside_fenced_code_is_not_a_split(self):
        """Ignore apparent headings inside backtick and tilde code fences."""
        source = (
            "## A\n```text\n## not a heading\n```\nbody\n"
            "~~~text\n## also not a heading\n~~~\n## B\nend"
        )

        blocks = split_markdown(source)

        self.assertEqual(len(blocks), 2)
        self.assertIn("## not a heading", blocks[0].text)
        self.assertIn("## also not a heading", blocks[0].text)

    def test_front_matter_heading_like_line_is_not_a_split(self):
        """Treat a leading YAML front-matter region as opaque scanner input."""
        source = "---\ntitle: Paper\n## metadata comment\n---\n## Body\ntext"

        blocks = split_markdown(source)

        self.assertEqual(len(blocks), 2)
        self.assertEqual(blocks[0].text, "---\ntitle: Paper\n## metadata comment\n---\n")
        self.assertTrue(blocks[1].text.startswith("## Body"))

    def test_unclosed_front_matter_opener_is_a_thematic_break(self):
        """Do not hide headings after a leading thematic break without a closer."""
        source = "---\n## Body\ntext"

        blocks = split_markdown(source)

        self.assertEqual(len(blocks), 2)
        self.assertEqual(blocks[0].text, "---\n")
        self.assertEqual(blocks[1].text, "## Body\ntext")

    def test_only_exact_second_level_headings_split(self):
        """Reject deeper, compact, and indented-code heading lookalikes."""
        source = (
            "# Top\n### Child\n##compact\n    ## indented code\n"
            "   ## Valid with three spaces\nbody"
        )

        blocks = split_markdown(source)

        self.assertEqual(len(blocks), 2)
        self.assertIn("##compact", blocks[0].text)
        self.assertIn("    ## indented code", blocks[0].text)
        self.assertTrue(blocks[1].text.startswith("   ## Valid"))

    def test_unclosed_fence_keeps_remaining_headings_in_same_block(self):
        """Keep the remainder opaque when a code fence is not closed."""
        source = "## A\n````python\nvalue = 1\n```\n## still code"

        blocks = split_markdown(source)

        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0].text, source)

    def test_backtick_in_info_string_does_not_open_a_fence(self):
        """Treat a backtick fence with a backtick in its info string as prose."""
        source = "```lang`invalid\n## Body\ntext"

        blocks = split_markdown(source)

        self.assertEqual(len(blocks), 2)
        self.assertEqual(blocks[0].text, "```lang`invalid\n")
        self.assertTrue(blocks[1].text.startswith("## Body"))

    def test_rebuild_preserves_original_order(self):
        """Sort translated blocks by source index before concatenation."""
        blocks = split_markdown("## A\na\n## B\nb")
        blocks[0] = MarkdownBlock(blocks[0].index, "## A\n翻译A\n")
        blocks[1] = MarkdownBlock(blocks[1].index, "## B\n翻译B")

        self.assertEqual(
            rebuild_markdown(list(reversed(blocks))),
            "## A\n翻译A\n\n## B\n翻译B",
        )

    def test_rebuild_separates_blocks_when_a_translation_omits_its_final_newline(self):
        """Keep a following heading at the line start after a trimmed response."""
        blocks = [
            MarkdownBlock(0, "## A\n译文A"),
            MarkdownBlock(1, "## B\n译文B"),
        ]

        self.assertEqual(
            rebuild_markdown(blocks),
            "## A\n译文A\n\n## B\n译文B",
        )

    def test_rebuild_keeps_a_blank_line_between_adjacent_markdown_blocks(self):
        """Keep headings and neighboring block content separated by an empty line."""
        blocks = [
            MarkdownBlock(0, "## A"),
            MarkdownBlock(1, "## B\n正文"),
        ]

        self.assertEqual(
            rebuild_markdown(blocks),
            "## A\n\n## B\n正文",
        )

    def test_rebuild_rejects_duplicate_indices(self):
        """Reject ambiguous ordering instead of silently dropping a block."""
        blocks = [MarkdownBlock(0, "a"), MarkdownBlock(0, "b")]

        with self.assertRaisesRegex(ValueError, "duplicate"):
            rebuild_markdown(blocks)

    def test_rebuild_rejects_missing_indices(self):
        """Require contiguous indices beginning at zero."""
        blocks = [MarkdownBlock(0, "a"), MarkdownBlock(2, "c")]

        with self.assertRaisesRegex(ValueError, "contiguous"):
            rebuild_markdown(blocks)

    def test_empty_document_has_one_empty_block_and_rebuilds(self):
        """Represent an empty source without losing its ordered block model."""
        blocks = split_markdown("")

        self.assertEqual(blocks, [MarkdownBlock(0, "")])
        self.assertEqual(rebuild_markdown(blocks), "")


class MarkdownProtectionTests(unittest.TestCase):
    """Verify protected structures round-trip while prose remains editable."""

    def test_inline_destination_with_reference_like_text_round_trips(self):
        """Do not nest a destination token inside later reference protection."""
        source = (
            "[x](https://example.test/[paper])\n"
            "[paper]: https://target.test"
        )

        protected = protect_markdown(source)

        self.assertEqual(restore_markdown(protected.text, protected), source)

    def test_shortcut_reference_before_angle_definition_round_trips(self):
        """Do not nest an autolink token inside its definition-line token."""
        source = "See [paper].\n[paper]: <https://target.test>"

        protected = protect_markdown(source)

        self.assertEqual(restore_markdown(protected.text, protected), source)

    def test_footnote_definition_prefix_is_one_protected_structure(self):
        """Keep the footnote marker and delimiter opaque while exposing its body."""
        source = "[^note]: Footnote body may translate."

        protected = protect_markdown(source)
        translated = protected.text.replace(": ", "：")

        self.assertIn("Footnote body may translate.", protected.text)
        self.assertEqual(restore_markdown(translated, protected), source)

    def test_table_boundaries_survive_translation_of_cell_text(self):
        """Protect table pipes while allowing header and data cells to change."""
        source = (
            "| Name | Value |\n"
            "| :--- | ----: |\n"
            "| alpha | beta |\n"
        )

        protected = protect_markdown(source)
        translated = (
            protected.text.replace("|", "")
            .replace("Name", "名称")
            .replace("Value", "值")
            .replace("alpha", "甲")
            .replace("beta", "乙")
        )

        self.assertIn("名称", translated)
        self.assertIn("甲", translated)
        self.assertEqual(
            restore_markdown(translated, protected),
            "| 名称 | 值 |\n| :--- | ----: |\n| 甲 | 乙 |\n",
        )

    def test_protect_and_restore_all_structural_regions(self):
        """Round-trip front matter, code, math, URLs, tables, and footnotes."""
        source = (
            "---\n"
            "title: Keep This\n"
            "tags: [one, two]\n"
            "---\n"
            "# Heading to translate\n\n"
            "Paragraph with `inline()` and $x + y$ plus \\(z^2\\).\n"
            "Display $$a = b$$ and:\n\\[c = d\\]\n\n"
            "[link text](https://example.com/a_(b)?q=1#part) and "
            "<https://example.org/doc> and https://example.net/raw?q=yes.\n"
            "![alt text](images/chart (final).png \"caption\")\n\n"
            "| Name | Value |\n"
            "| :--- | ----: |\n"
            "| alpha | beta |\n\n"
            "Reference[^note] and repeated[^note].\n"
            "[^note]: Footnote body may translate.\n\n"
            "```python\n"
            "## code heading\n"
            "print('$not_math$', 'https://inside.example')\n"
            "```\n"
        )

        protected = protect_markdown(source)

        self.assertNotIn("title: Keep This", protected.text)
        self.assertNotIn("`inline()`", protected.text)
        self.assertNotIn("$x + y$", protected.text)
        self.assertNotIn("https://example.com", protected.text)
        self.assertNotIn("images/chart (final).png", protected.text)
        self.assertNotIn("| :--- | ----: |", protected.text)
        self.assertNotIn("[^note]", protected.text)
        self.assertNotIn("print('$not_math$'", protected.text)
        self.assertIn("# Heading to translate", protected.text)
        self.assertIn("Paragraph with", protected.text)
        self.assertIn("link text", protected.text)
        self.assertIn("alt text", protected.text)
        self.assertIn("Name", protected.text)
        self.assertIn("Value", protected.text)
        self.assertIn("alpha", protected.text)
        self.assertIn("beta", protected.text)
        self.assertNotIn("| Name | Value |", protected.text)
        self.assertNotIn("| alpha | beta |", protected.text)
        self.assertIn("Footnote body may translate.", protected.text)
        self.assertEqual(restore_markdown(protected.text, protected), source)

    def test_multiline_math_and_inline_code_with_variable_delimiters_round_trip(self):
        """Protect multiline display math and matching inline-code delimiters."""
        source = "Before ``code ` literal``.\n$$\na+b\n$$\nAfter"

        protected = protect_markdown(source)

        self.assertNotIn("code ` literal", protected.text)
        self.assertNotIn("a+b", protected.text)
        self.assertEqual(restore_markdown(protected.text, protected), source)

    def test_escaped_backticks_remain_translatable_before_inline_code(self):
        """Skip escaped backtick pairs without consuming later inline code."""
        source = r"Escaped \`term\` and `code`."

        protected = protect_markdown(source)
        translated = protected.text.replace("term", "术语")

        self.assertIn(r"\`term\`", protected.text)
        self.assertNotIn("`code`", protected.text)
        self.assertEqual(
            restore_markdown(translated, protected),
            r"Escaped \`术语\` and `code`.",
        )

    def test_reference_destinations_are_protected_but_labels_remain(self):
        """Protect inline and reference destinations without hiding labels."""
        source = (
            "Read [visible label][paper] and ![visible alt][figure].\n"
            "[paper]: https://example.com/paper \"Paper title\"\n"
            "[figure]: assets/figure-1.png\n"
        )

        protected = protect_markdown(source)

        self.assertIn("visible label", protected.text)
        self.assertIn("visible alt", protected.text)
        self.assertNotIn("[paper]", protected.text)
        self.assertNotIn("[figure]", protected.text)
        self.assertNotIn("https://example.com/paper", protected.text)
        self.assertNotIn("assets/figure-1.png", protected.text)
        self.assertEqual(restore_markdown(protected.text, protected), source)

    def test_translated_shortcut_references_expand_with_original_targets(self):
        """Keep shortcut labels editable without disconnecting their definitions."""
        source = (
            "Read [paper] and inspect ![diagram].\n"
            "[paper]: https://example.com/paper\n"
            "[diagram]: assets/diagram.png\n"
        )

        protected = protect_markdown(source)
        translated = protected.text.replace("paper", "论文").replace(
            "diagram", "示意图"
        )

        self.assertIn("[paper]", protected.text)
        self.assertIn("![diagram]", protected.text)
        self.assertEqual(restore_markdown(protected.text, protected), source)
        self.assertEqual(
            restore_markdown(translated, protected),
            "Read [论文][paper] and inspect ![示意图][diagram].\n"
            "[paper]: https://example.com/paper\n"
            "[diagram]: assets/diagram.png\n",
        )

    def test_translated_collapsed_reference_uses_original_target(self):
        """Expand a translated collapsed label with its original reference ID."""
        source = "Read [paper][].\n[paper]: https://example.test/paper"

        protected = protect_markdown(source)
        translated = protected.text.replace("paper", "论文")

        self.assertEqual(restore_markdown(protected.text, protected), source)
        self.assertEqual(
            restore_markdown(translated, protected),
            "Read [论文][paper].\n[paper]: https://example.test/paper",
        )

    def test_restore_reports_missing_or_duplicate_tokens(self):
        """Report every missing or duplicate protected token for a retry caller."""
        protected = protect_markdown("Text with `code` and $math$.")
        first_token = next(iter(protected.tokens))

        with self.assertRaises(ProtectedTokenValidationError) as missing_error:
            restore_markdown(protected.text.replace(first_token, ""), protected)
        self.assertEqual(missing_error.exception.missing_tokens, (first_token,))
        self.assertEqual(missing_error.exception.duplicate_tokens, ())

        with self.assertRaises(ProtectedTokenValidationError) as duplicate_error:
            restore_markdown(protected.text + first_token, protected)
        self.assertEqual(duplicate_error.exception.missing_tokens, ())
        self.assertEqual(duplicate_error.exception.duplicate_tokens, (first_token,))

    def test_tokens_are_typed_and_avoid_exact_source_collisions(self):
        """Use readable typed tokens while preserving literal source lookalikes."""
        source = "Literal [[LTP_CODE_0]] with `protected`, $math$, and https://example.test."

        protected = protect_markdown(source)

        self.assertIn("[[LTP_CODE_0]]", protected.text)
        self.assertIn("[[LTP_CODE_1]]", protected.tokens)
        self.assertIn("[[LTP_MATH_0]]", protected.tokens)
        self.assertIn("[[LTP_URL_0]]", protected.tokens)
        self.assertEqual(restore_markdown(protected.text, protected), source)


if __name__ == "__main__":
    unittest.main()
