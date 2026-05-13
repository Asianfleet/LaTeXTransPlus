import unittest

from src.formats.latex.utils import add_language_support_package


BASE_TEX = "\\documentclass{article}\n\\begin{document}\nHello\n\\end{document}\n"


class LatexLanguagePackageTests(unittest.TestCase):
    def test_chinese_targets_insert_ctex(self):
        for language in ("ch", "cn", "zh"):
            with self.subTest(language=language):
                result = add_language_support_package(BASE_TEX, language)

                self.assertIn("\\usepackage[UTF8]{ctex}", result)
                self.assertLess(
                    result.index("\\documentclass{article}"),
                    result.index("\\usepackage[UTF8]{ctex}"),
                )

    def test_japanese_targets_insert_luatexja_without_ctex(self):
        for language in ("ja", "jp"):
            with self.subTest(language=language):
                result = add_language_support_package(BASE_TEX, language)

                self.assertIn("\\usepackage{luatexja}", result)
                self.assertNotIn("\\usepackage[UTF8]{ctex}", result)

    def test_korean_target_inserts_kotex_without_ctex(self):
        result = add_language_support_package(BASE_TEX, "ko")

        self.assertIn("\\usepackage{kotex}", result)
        self.assertNotIn("\\usepackage[UTF8]{ctex}", result)

    def test_french_target_does_not_insert_cjk_packages(self):
        result = add_language_support_package(BASE_TEX, "fr")

        self.assertNotIn("\\usepackage[UTF8]{ctex}", result)
        self.assertNotIn("\\usepackage{luatexja}", result)
        self.assertNotIn("\\usepackage{kotex}", result)
        self.assertEqual(result, BASE_TEX)

    def test_unknown_target_does_not_insert_cjk_packages(self):
        result = add_language_support_package(BASE_TEX, "de")

        self.assertNotIn("\\usepackage[UTF8]{ctex}", result)
        self.assertNotIn("\\usepackage{luatexja}", result)
        self.assertNotIn("\\usepackage{kotex}", result)
        self.assertEqual(result, BASE_TEX)

    def test_existing_target_package_is_not_duplicated(self):
        tex = "\\documentclass{article}\n\\usepackage{luatexja}\n\\begin{document}\n本文\n\\end{document}\n"

        result = add_language_support_package(tex, "ja")

        self.assertEqual(result.count("\\usepackage{luatexja}"), 1)


if __name__ == "__main__":
    unittest.main()
