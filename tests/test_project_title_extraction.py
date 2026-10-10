"""复杂 LaTeX 标题与历史标题修正的回归测试。"""

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from src.project_metadata import title_from_latex_captions
from src.agents.coordinator_agent import CoordinatorAgent
from src.tui.history import load_output_history


class ProjectTitleExtractionTests(unittest.TestCase):
    """验证标题只保留可读文字并恢复项目自定义宏。"""

    def test_model_name_inside_centering(self):
        """标题中的模型名称来自宏定义，保留中文正文。"""
        captions = [{"cap_type": "title", "content":
                     r"\title{\centering{\modelname{}: 仅循环一次以实现高效的测试时计算扩展}}"}]
        commands = [{"content": r"\newcommand{\modelname}{\textsc{Loop}}"}]
        self.assertEqual(title_from_latex_captions(captions, commands),
                         "Loop: 仅循环一次以实现高效的测试时计算扩展")

    def test_logo_and_positioning_arguments_are_not_title_text(self):
        """标题 logo 的图片路径、尺寸和位置参数不会进入文字。"""
        captions = [{"cap_type": "title", "content": r"""\title{
\raisebox{-0.15\height}{\includegraphics[width=0.032\textwidth]{figures/logo.pdf}} %
Kimi K2.5: Visual Agentic Intelligence}"""}]
        self.assertEqual(title_from_latex_captions(captions),
                         "Kimi K2.5: Visual Agentic Intelligence")

    def test_nested_argument_macros_and_recursive_macro(self):
        """带参数的嵌套宏可展开，循环定义不会使标题提取挂起。"""
        commands = [{"content": r"\newcommand{\modelname}{\styled{Loop}}"},
                    {"content": r"\newcommand{\styled}[1]{\textbf{#1}}"},
                    {"content": r"\def\cycle{\cycle}"}]
        captions = [{"cap_type": "title", "content":
                     r"\title{\modelname: \raisebox{2pt}[3pt][0pt]{Readable} \cycle Title}"}]
        self.assertEqual(title_from_latex_captions(captions, commands), "Loop: Readable Title")

    def test_history_refreshes_cached_title_using_original_maps(self):
        """已经缓存的错误标题由原文映射修正，不采用译文标题。"""
        with TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "paper"
            output.mkdir()
            (output / ".latextrans-tui.json").write_text(json.dumps(
                {"engine": "heavy", "title": ": Old title", "translation_model": "model-a"}
            ), encoding="utf-8")
            (output / "captions_map.json").write_text(json.dumps([
                {"cap_type": "title", "content": r"\title{\modelname: Original title}",
                 "trans_content": r"\title{Translated title}"}
            ]), encoding="utf-8")
            (output / "newcommands_map.json").write_text(json.dumps([
                {"content": r"\newcommand{\modelname}{Loop}"}
            ]), encoding="utf-8")
            project = load_output_history(root, "heavy")[0].projects[0]
            self.assertEqual(project.title, "Loop: Original title")
            self.assertEqual(project.translation_model, "model-a")

    def test_heavy_event_reads_project_macro_map(self):
        """Heavy 发出的标题事件使用解析器保存的原文宏定义。"""
        with TemporaryDirectory() as directory:
            output = Path(directory)
            (output / "newcommands_map.json").write_text(json.dumps([
                {"name": "modelname", "content": r"\newcommand{\modelname}{Loop}"}
            ]), encoding="utf-8")
            events = []
            agent = CoordinatorAgent(config={"_project_metadata_callback": events.append},
                                     project_dir=str(output / "paper"), output_dir=str(output))
            agent._emit_project_metadata([
                {"cap_type": "title", "content": r"\title{\modelname: Original title}"}
            ], str(output))
            self.assertEqual(events[0]["title"], "Loop: Original title")

    def test_damaged_macro_map_keeps_plain_title_and_missing_maps_keep_cache(self):
        """损坏宏产物不妨碍普通标题，原文产物缺失时保留缓存标题。"""
        with TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "paper"
            output.mkdir()
            (output / ".latextrans-tui.json").write_text(json.dumps(
                {"engine": "heavy", "title": "Cached title"}
            ), encoding="utf-8")
            (output / "newcommands_map.json").write_text("invalid JSON", encoding="utf-8")
            captions_path = output / "captions_map.json"
            captions_path.write_text(json.dumps([
                {"cap_type": "title", "content": r"\title{Original title}"}
            ]), encoding="utf-8")
            self.assertEqual(load_output_history(root, "heavy")[0].projects[0].title, "Original title")
            captions_path.unlink()
            self.assertEqual(load_output_history(root, "heavy")[0].projects[0].title, "Cached title")
