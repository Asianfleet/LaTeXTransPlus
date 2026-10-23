import unittest

from src.formats.latex.parser import LatexParser
from src.formats.latex.utils import remove_comments


class LatexSectionSplittingTests(unittest.TestCase):
    """验证章节切分保留标题外层命令及原有章节编号。"""

    def test_hypertarget_heading_stays_in_one_section(self):
        """带锚点的各级标题必须完整留在所属章节中。"""
        headings = [
            ("section", "1"),
            ("subsection", "1_1"),
            ("subsection*", "1_1"),
            ("subsubsection", "1_1_1"),
            ("subsubsection*", "1_1_1"),
            ("section*", "2"),
        ]
        for command, expected_id in headings:
            with self.subTest(command=command):
                prefix = "" if command == "section" else "\\section{Previous}\nPrevious body.\n"
                if command.rstrip("*") == "subsubsection":
                    prefix += "\\subsection{Parent}\nParent body.\n"
                wrapper = (
                    "\\hypertarget{anchor}{%\n"
                    f"\\{command}" + "{A \\textbf{nested} title}\\label{anchor}}"
                )
                tex = (
                    "\\documentclass{article}\n\\begin{document}\nFront matter.\n"
                    + prefix + wrapper + "\nBody.\n\\section{Next}\nNext body.\n\\end{document}"
                )
                parser = LatexParser(".", ".")
                parser._split_to_sections(tex)
                sections = {part["section"]: part["content"] for part in parser.sections_json}

                self.assertTrue(sections[expected_id].startswith(remove_comments(wrapper)))
                self.assertEqual("".join(part["content"] for part in parser.sections_json), remove_comments(tex))
                for part in parser.sections_json:
                    self.assertEqual(part["content"].count("{"), part["content"].count("}"))

    def test_empty_and_body_hypertargets_stay_with_previous_section(self):
        """正文锚点和空锚点不能被误认为下一标题的外层包装。"""
        for anchor in (r"\hypertarget{body}{Some text}", r"\hypertarget{empty}{}"):
            with self.subTest(anchor=anchor):
                tex = "\\begin{document}\n\\section{First}\n" + anchor + "\n\\section{Second}\nText.\\end{document}"
                parser = LatexParser(".", ".")
                parser._split_to_sections(tex)
                sections = {part["section"]: part["content"] for part in parser.sections_json}

                self.assertIn(anchor, sections["1"])
                self.assertTrue(sections["2"].startswith(r"\section{Second}"))

    def test_hypertarget_arguments_allow_whitespace_and_escaped_braces(self):
        """锚点参数含换行、嵌套命令或转义花括号时仍应完整切分。"""
        for target in (r"anchor\{literal\}", r"anchor-\textbf{nested}"):
            with self.subTest(target=target):
                wrapper = "\\hypertarget\n{" + target + "}\n{\n\\section*{Résumé 中文 日本語}\\label{anchor}}"
                tex = "\\begin{document}\nIntro.\n" + wrapper + "\nText.\\end{document}"
                parser = LatexParser(".", ".")
                parser._split_to_sections(tex)

                self.assertTrue(parser.sections_json[2]["content"].startswith(wrapper))
                self.assertEqual("".join(part["content"] for part in parser.sections_json), tex)

    def test_short_section_merging_preserves_complete_hypertargets(self):
        """短章节合并后不能重新引入跨片段的标题包装。"""
        tex = (
            "\\begin{document}\n"
            "\\hypertarget{first}{\\section{First}\\label{first}}\nShort.\n"
            "\\hypertarget{second}{\\subsection{Second}\\label{second}}\nShort.\n"
            "\\hypertarget{third}{\\section{Third}\\label{third}}\nShort.\n"
            "\\end{document}"
        )
        parser = LatexParser(".", ".")
        parser._split_to_sections(tex)
        parser._merge_short_sections(min_tokens=50)

        # 合并逻辑原本会插入换行，只核对非空行和完整的命令结构。
        merged = "".join(part["content"] for part in parser.sections_json)
        self.assertEqual(
            [line for line in merged.splitlines() if line.strip()],
            [line for line in tex.splitlines() if line.strip()],
        )
        for part in parser.sections_json:
            self.assertEqual(part["content"].count("{"), part["content"].count("}"))

    def test_plain_headings_keep_numbering_and_content(self):
        """没有包装命令时继续沿用原有切分与编号。"""
        tex = "\\begin{document}\n\\section{First}\nOne.\n\\subsection{Child}\nTwo.\n\\section{Last}\nThree.\\end{document}"
        parser = LatexParser(".", ".")
        parser._split_to_sections(tex)

        self.assertEqual([part["section"] for part in parser.sections_json], ["-1", "0", "1", "1_1", "2"])
        self.assertEqual("".join(part["content"] for part in parser.sections_json), tex)
