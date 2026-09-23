"""Tests for terminal UI input parsing and validation."""

import unittest

from src.tui.input_parser import (
    parse_input_items,
    validate_input_items,
    validate_lite_input,
)


class TuiInputParserTests(unittest.TestCase):
    """Regression tests for batch input parsing and input-type validation."""

    def test_parse_accepts_commas_and_newlines(self):
        """Batch text is split on commas and newlines with whitespace trimmed."""
        items = parse_input_items("arxiv", "2508.18791, 2407.01648\n2501.00001")
        self.assertEqual(items, ["2508.18791", "2407.01648", "2501.00001"])

    def test_arxiv_accepts_ids_and_urls(self):
        """arXiv input accepts bare IDs and arXiv URLs."""
        errors = validate_input_items(
            "arxiv",
            ["2508.18791", "https://arxiv.org/abs/2508.18791v2"],
        )
        self.assertEqual(errors, [])

    def test_arxiv_rejects_non_arxiv_url(self):
        """arXiv input rejects URLs outside arxiv.org."""
        errors = validate_input_items("arxiv", ["https://example.test/paper.zip"])
        self.assertEqual(
            errors,
            [
                "arxiv input must be an arXiv ID or arXiv URL: "
                "https://example.test/paper.zip"
            ],
        )

    def test_local_rejects_remote_url(self):
        """Local input rejects remote HTTP URLs."""
        errors = validate_input_items("local", ["https://example.test/paper.zip"])
        self.assertEqual(
            errors,
            ["local input must be a local path, not a URL: https://example.test/paper.zip"],
        )

    def test_remote_accepts_http_archive_url(self):
        """Remote input accepts HTTP archive URLs."""
        errors = validate_input_items("remote", ["https://example.test/paper.tar.gz"])
        self.assertEqual(errors, [])

    def test_remote_rejects_non_http_url(self):
        """Remote input rejects URLs that are not HTTP or HTTPS."""
        errors = validate_input_items("remote", ["file:///tmp/paper.zip"])
        self.assertEqual(
            errors,
            ["remote input must be an http or https URL: file:///tmp/paper.zip"],
        )


class LiteInputParserTests(unittest.TestCase):
    """Regression tests for the lite engine's one-item input boundary."""

    def test_lite_rejects_comma_and_newline_batch_text(self):
        """Lite input rejects either supported heavy batch separator."""
        self.assertTrue(validate_lite_input("first.pdf, second.pdf"))
        self.assertTrue(validate_lite_input("first.pdf\nsecond.pdf"))

    def test_lite_accepts_one_pdf_or_arxiv_value(self):
        """Lite input accepts exactly one value understood by the lite engine."""
        self.assertEqual(validate_lite_input("paper.pdf"), [])
        self.assertEqual(validate_lite_input("2508.18791"), [])


if __name__ == "__main__":
    unittest.main()
