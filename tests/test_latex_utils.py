import unittest

from src.formats.latex.utils import LatexNodes2Text, replace_href


class LatexUtilsTests(unittest.TestCase):
    def test_replace_href_handles_nested_braces_in_url_argument(self):
        latex = (
            r"\href{https://example.com/plain}{Plain} "
            r"\href{https://example.com/\model{}}{\model{}}"
        )

        cleaned = replace_href(latex)

        self.assertEqual(cleaned, r"Plain \model{}")
        LatexNodes2Text().latex_to_text(cleaned)


if __name__ == "__main__":
    unittest.main()
