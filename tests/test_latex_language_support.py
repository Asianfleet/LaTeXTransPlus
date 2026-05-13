import json
import tempfile
import unittest
from pathlib import Path

from src.formats.latex.reconstruct import LatexConstructor
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


class LatexConstructorLanguageSupportTests(unittest.TestCase):
    def _construct_project(self, target_language):
        with tempfile.TemporaryDirectory() as tmp_dir:
            project_dir = Path(tmp_dir)
            main_tex = project_dir / "main.tex"
            main_tex.write_text(
                "\\documentclass{article}\n\\begin{document}\nOriginal\n\\end{document}\n",
                encoding="utf-8",
            )
            (project_dir / "00README.json").write_text(
                json.dumps({"sources": [{"usage": "toplevel", "filename": "main.tex"}]}),
                encoding="utf-8",
            )

            constructor = LatexConstructor(
                sections=[
                    {
                        "trans_content": "\\documentclass{article}\n\\begin{document}\n本文\n\\end{document}"
                    }
                ],
                captions=[],
                envs=[],
                inputs=[],
                newcommands=[],
                output_latex_dir=str(project_dir),
                target_language=target_language,
            )
            constructor.construct()

            return main_tex.read_text(encoding="utf-8")

    def test_constructor_uses_japanese_package_without_ctex(self):
        result = self._construct_project("ja")

        self.assertIn("\\usepackage{luatexja}", result)
        self.assertNotIn("\\usepackage[UTF8]{ctex}", result)

    def test_constructor_does_not_add_cjk_package_for_french(self):
        result = self._construct_project("fr")

        self.assertNotIn("\\usepackage[UTF8]{ctex}", result)
        self.assertNotIn("\\usepackage{luatexja}", result)
        self.assertNotIn("\\usepackage{kotex}", result)


if __name__ == "__main__":
    unittest.main()
