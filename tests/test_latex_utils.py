import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.formats.latex.parser import LatexParser
from src.formats.latex.utils import (
    LatexNodes2Text,
    batch_download_arxiv_tex,
    is_already_downloaded,
    merge_tex_from_inputs,
    replace_href,
)


class LatexUtilsTests(unittest.TestCase):
    def test_parser_prefers_tex_file_when_input_name_is_also_a_directory(self):
        """目录与同名 TeX 文件并存时，解析器应读取 TeX 文件。"""
        with tempfile.TemporaryDirectory() as tmp_dir:
            project_dir = Path(tmp_dir)
            (project_dir / "appendix").mkdir()
            (project_dir / "appendix.tex").write_text("Appendix content", encoding="utf-8")

            parser = LatexParser(str(project_dir), str(project_dir / "output"))

            merged = parser._merge_inputs(r"\begin{document}\input{appendix}\end{document}")

            self.assertIn("Appendix content", merged)
            self.assertEqual(parser.inputs_json[0]["path"], "appendix")

    def test_merge_tex_from_inputs_rejects_directory_as_explicit_tex_input(self):
        """显式 .tex 输入指向目录时，应报告文件不存在而不是打开目录。"""
        with tempfile.TemporaryDirectory() as tmp_dir:
            project_dir = Path(tmp_dir)
            main_file = project_dir / "main.tex"
            (project_dir / "appendix.tex").mkdir()
            main_file.write_text(
                r"\documentclass{article}\begin{document}\input{appendix.tex}\end{document}",
                encoding="utf-8",
            )

            with self.assertRaises(FileNotFoundError):
                merge_tex_from_inputs(str(main_file))

    def test_replace_href_handles_nested_braces_in_url_argument(self):
        latex = (
            r"\href{https://example.com/plain}{Plain} "
            r"\href{https://example.com/\model{}}{\model{}}"
        )

        cleaned = replace_href(latex)

        self.assertEqual(cleaned, r"Plain \model{}")
        LatexNodes2Text().latex_to_text(cleaned)

    def test_empty_arxiv_source_directory_is_not_already_downloaded(self):
        """确认空的 arXiv 源码目录不会被当作已下载项目。"""
        with tempfile.TemporaryDirectory() as tmp_dir:
            source_root = Path(tmp_dir)
            (source_root / "2512.16912").mkdir()

            self.assertFalse(is_already_downloaded("2512.16912", str(source_root)))

    def test_batch_download_redownloads_empty_arxiv_source_directory(self):
        """确认空的 arXiv 源码目录会触发重新下载源码。"""
        class FakePdfResponse:
            """模拟 arXiv PDF 下载响应，避免测试访问真实网络。"""

            content = b"%PDF"

            def raise_for_status(self):
                """模拟成功的 HTTP 状态检查。"""
                return None

        with tempfile.TemporaryDirectory() as tmp_dir:
            source_root = Path(tmp_dir)
            stale_dir = source_root / "2512.16912"
            stale_dir.mkdir()

            def fake_download(arxiv_id, tex_url, save_dir, headers):
                """记录重新下载请求并返回预期源码目录。"""
                self.assertEqual(arxiv_id, "2512.16912")
                self.assertEqual(tex_url, "https://arxiv.org/e-print/2512.16912")
                self.assertEqual(save_dir, str(source_root))
                return str(source_root / arxiv_id)

            with patch(
                "src.formats.latex.utils.get_tex_url",
                return_value="https://arxiv.org/e-print/2512.16912",
            ):
                with patch("src.formats.latex.utils.download_tex", side_effect=fake_download) as download_tex:
                    with patch("src.formats.latex.utils.requests.get", return_value=FakePdfResponse()):
                        source_dirs = batch_download_arxiv_tex(["2512.16912"], str(source_root))

            download_tex.assert_called_once()
            self.assertEqual(source_dirs, [str(stale_dir)])


if __name__ == "__main__":
    unittest.main()
