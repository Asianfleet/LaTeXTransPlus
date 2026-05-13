import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.agents.tool_agents.generator_agent import GeneratorAgent
from src.formats.latex.compile import LaTexCompiler
from src.formats.latex.reconstruct import LatexConstructor
from src.formats.latex.utils import add_language_support_package, escape_unescaped_percent_signs, latex_engine_order_for_language


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

    def test_chinese_target_does_not_mix_ctex_with_existing_cjkutf8(self):
        tex = (
            "\\documentclass{article}\n"
            "\\usepackage{CJKutf8}\n"
            "\\begin{document}\n"
            "\\begin{CJK*}{UTF8}{gbsn}\n"
            "本文\n"
            "\\end{CJK*}\n"
            "\\end{document}\n"
        )

        result = add_language_support_package(tex, "ch")

        self.assertNotIn("\\usepackage[UTF8]{ctex}", result)
        self.assertIn("\\usepackage{CJKutf8}", result)
        self.assertIn("\\begin{CJK*}{UTF8}{gbsn}", result)


class LatexPercentEscapingTests(unittest.TestCase):
    def test_escape_unescaped_percent_signs_in_translated_text(self):
        text = r"准确率为 64.2%，且 pass rate 为 36.2% \citep{MATH}，保留 \% 和 \url{https://example.test/a%20b}。"

        result = escape_unescaped_percent_signs(text)

        self.assertIn(r"64.2\%", result)
        self.assertIn(r"36.2\% \citep{MATH}", result)
        self.assertIn(r"\%", result)
        self.assertIn(r"\url{https://example.test/a%20b}", result)


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


class LatexCompilerLanguageTests(unittest.TestCase):
    def test_engine_order_for_supported_languages(self):
        self.assertEqual(latex_engine_order_for_language("ch"), ["pdflatex", "xelatex"])
        self.assertEqual(latex_engine_order_for_language("zh"), ["pdflatex", "xelatex"])
        self.assertEqual(latex_engine_order_for_language("ja"), ["lualatex", "xelatex"])
        self.assertEqual(latex_engine_order_for_language("jp"), ["lualatex", "xelatex"])
        self.assertEqual(latex_engine_order_for_language("ko"), ["xelatex", "pdflatex"])
        self.assertEqual(latex_engine_order_for_language("fr"), ["pdflatex", "xelatex"])
        self.assertEqual(latex_engine_order_for_language("de"), ["pdflatex", "xelatex"])

    def test_compile_uses_target_language_engine_order(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            project_dir = Path(tmp_dir)
            (project_dir / "main.tex").write_text(
                "\\documentclass{article}\n\\begin{document}\n本文\n\\end{document}\n",
                encoding="utf-8",
            )

            calls = []

            def fake_compile(tex_file, out_dir, engine):
                calls.append((engine, Path(out_dir).name))
                if engine == "lualatex":
                    (Path(out_dir) / "main.pdf").write_bytes(b"%PDF")

            compiler = LaTexCompiler(str(project_dir), target_language="ja")

            with patch.object(compiler, "_compile_with_lualatex", side_effect=fake_compile), \
                    patch.object(compiler, "_compile_with_xelatex", side_effect=fake_compile), \
                    patch.object(compiler, "_compile_with_pdflatex", side_effect=fake_compile), \
                    patch("builtins.print"):
                pdf_path = compiler.compile()

        self.assertEqual(calls, [("lualatex", "build_lualatex")])
        self.assertTrue(pdf_path.endswith("main.pdf"))

    def test_compile_falls_back_to_next_language_engine(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            project_dir = Path(tmp_dir)
            (project_dir / "main.tex").write_text(
                "\\documentclass{article}\n\\begin{document}\n本文\n\\end{document}\n",
                encoding="utf-8",
            )

            calls = []

            def fake_compile(tex_file, out_dir, engine):
                calls.append((engine, Path(out_dir).name))
                if engine == "xelatex":
                    (Path(out_dir) / "main.pdf").write_bytes(b"%PDF")

            compiler = LaTexCompiler(str(project_dir), target_language="ja")

            with patch.object(compiler, "_compile_with_lualatex", side_effect=fake_compile), \
                    patch.object(compiler, "_compile_with_xelatex", side_effect=fake_compile), \
                    patch.object(compiler, "_compile_with_pdflatex", side_effect=fake_compile), \
                    patch("builtins.print"):
                pdf_path = compiler.compile()

        self.assertEqual(
            calls,
            [("lualatex", "build_lualatex"), ("xelatex", "build_xelatex")],
        )
        self.assertTrue(pdf_path.endswith("main.pdf"))

    def test_compile_ignores_pdf_when_log_contains_latex_error(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            project_dir = Path(tmp_dir)
            (project_dir / "main.tex").write_text(
                "\\documentclass{article}\n\\begin{document}\n本文\n\\end{document}\n",
                encoding="utf-8",
            )

            calls = []

            def fake_compile(tex_file, out_dir, engine):
                calls.append((engine, Path(out_dir).name))
                out_path = Path(out_dir)
                (out_path / "main.pdf").write_bytes(b"%PDF")
                if engine == "lualatex":
                    (out_path / "main.log").write_text(
                        "LaTeX Error: Environment CJK* undefined.\n",
                        encoding="utf-8",
                    )
                else:
                    (out_path / "main.log").write_text(
                        "Output written on main.pdf.\n",
                        encoding="utf-8",
                    )

            compiler = LaTexCompiler(str(project_dir), target_language="ja")

            with patch.object(compiler, "_compile_with_lualatex", side_effect=fake_compile), \
                    patch.object(compiler, "_compile_with_xelatex", side_effect=fake_compile), \
                    patch.object(compiler, "_compile_with_pdflatex", side_effect=fake_compile), \
                    patch("builtins.print"):
                pdf_path = compiler.compile()

        self.assertEqual(
            calls,
            [("lualatex", "build_lualatex"), ("xelatex", "build_xelatex")],
        )
        self.assertTrue(pdf_path.endswith("build_xelatex\\main.pdf") or pdf_path.endswith("build_xelatex/main.pdf"))

    def test_compile_returns_none_when_all_pdf_outputs_have_hard_errors(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            project_dir = Path(tmp_dir)
            (project_dir / "main.tex").write_text(
                "\\documentclass{article}\n\\begin{document}\n本文\n\\end{document}\n",
                encoding="utf-8",
            )

            def fake_compile(tex_file, out_dir, engine):
                out_path = Path(out_dir)
                (out_path / "main.pdf").write_bytes(b"%PDF")
                (out_path / "main.log").write_text(
                    "! Undefined control sequence.\n",
                    encoding="utf-8",
                )

            compiler = LaTexCompiler(str(project_dir), target_language="ja")

            with patch.object(compiler, "_compile_with_lualatex", side_effect=fake_compile), \
                    patch.object(compiler, "_compile_with_xelatex", side_effect=fake_compile), \
                    patch.object(compiler, "_compile_with_pdflatex", side_effect=fake_compile), \
                    patch("builtins.print"):
                pdf_path = compiler.compile()

        self.assertIsNone(pdf_path)

    def test_compile_removes_stale_success_marker_when_log_has_hard_errors(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            project_dir = Path(tmp_dir)
            (project_dir / "main.tex").write_text(
                "\\documentclass{article}\n\\begin{document}\n本文\n\\end{document}\n",
                encoding="utf-8",
            )

            def fake_compile(tex_file, out_dir, engine):
                (project_dir / "success.txt").write_text("Compilation successful\n", encoding="utf-8")
                out_path = Path(out_dir)
                (out_path / "main.pdf").write_bytes(b"%PDF")
                (out_path / "main.log").write_text(
                    "LaTeX Error: Environment CJK* undefined.\n",
                    encoding="utf-8",
                )

            compiler = LaTexCompiler(str(project_dir), target_language="ja")

            with patch.object(compiler, "_compile_with_lualatex", side_effect=fake_compile), \
                    patch.object(compiler, "_compile_with_xelatex", side_effect=fake_compile), \
                    patch.object(compiler, "_compile_with_pdflatex", side_effect=fake_compile), \
                    patch("builtins.print"):
                compiler.compile()

            self.assertFalse((project_dir / "success.txt").exists())

class GeneratorAgentLanguagePropagationTests(unittest.TestCase):
    def test_generator_passes_target_language_to_constructor_and_compiler(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            source_dir = root / "paper"
            source_dir.mkdir()
            (source_dir / "main.tex").write_text(
                "\\documentclass{article}\n\\begin{document}\nOriginal\n\\end{document}\n",
                encoding="utf-8",
            )

            output_dir = root / "output"
            output_dir.mkdir()
            for filename, data in {
                "sections_map.json": [{"trans_content": "\\documentclass{article}\n\\begin{document}\n本文\n\\end{document}"}],
                "captions_map.json": [],
                "envs_map.json": [],
                "newcommands_map.json": [],
                "inputs_map.json": [],
            }.items():
                (output_dir / filename).write_text(json.dumps(data), encoding="utf-8")

            constructor_languages = []
            compiler_languages = []

            class FakeConstructor:
                def __init__(self, **kwargs):
                    constructor_languages.append(kwargs["target_language"])

                def construct(self):
                    return None

            class FakeCompiler:
                def __init__(self, output_latex_dir, target_language):
                    compiler_languages.append(target_language)

                def compile(self):
                    return str(root / "paper.pdf")

            with patch("src.formats.latex.reconstruct.LatexConstructor", FakeConstructor), \
                    patch("src.formats.latex.compile.LaTexCompiler", FakeCompiler), \
                    patch("src.agents.tool_agents.generator_agent.st"), \
                    patch("time.sleep"), \
                    patch("builtins.print"):
                agent = GeneratorAgent(
                    config={"target_language": "ja"},
                    project_dir=str(source_dir),
                    output_dir=str(output_dir),
                )
                result = agent.execute()

        self.assertEqual(result, str(root / "paper.pdf"))
        self.assertEqual(constructor_languages, ["ja"])
        self.assertEqual(compiler_languages, ["ja"])


if __name__ == "__main__":
    unittest.main()
