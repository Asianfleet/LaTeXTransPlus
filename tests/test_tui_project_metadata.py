"""项目展示元数据、动态 profile 和历史兼容回归测试。"""

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from src.tui import config as tui_config
from src.tui.history import load_output_history, read_project_metadata, write_project_metadata
from src.tui.state import ProjectStatus, TaskViewState


class ProjectMetadataTests(unittest.TestCase):
    """验证元数据获取不依赖当前模型设置或翻译成功状态。"""

    def test_title_extractors_preserve_nested_and_multilingual_text(self):
        """标题保留嵌套格式文字，并排除代码块中的假 Markdown 标题。"""
        from src.project_metadata import title_from_latex_captions, title_from_markdown

        self.assertEqual(title_from_latex_captions([
            {"cap_type": "title", "content": r"\title[Short {name}]{A \textbf{Nested {研究}} Title}"}
        ]), "A Nested 研究 Title")
        self.assertEqual(title_from_markdown("```md\n# Fake\n```\n# **真实** [Title](url)\n"), "真实 Title")
        self.assertEqual(title_from_markdown("No title"), "")

    def test_profiles_only_enumerate_files(self):
        """选项按文件名排序，忽略其他扩展名和同名目录。"""
        with TemporaryDirectory() as directory:
            root = Path(directory)
            providers = root / "provider"
            providers.mkdir()
            (providers / "z.toml").write_text("invalid TOML", encoding="utf-8")
            (providers / "a.toml").write_text("", encoding="utf-8")
            (providers / "ignored.txt").touch()
            (providers / "directory.toml").mkdir()
            self.assertEqual(tui_config.list_llm_profiles(root / "ui.toml"), [("a", "a"), ("z", "z")])
            self.assertEqual(tui_config.list_llm_profiles(root / "absent" / "ui.toml"), [])

    def test_metadata_event_keeps_status_and_ignores_empty_updates(self):
        """补充元数据不改变任务状态，空值不会擦除已经捕获的信息。"""
        for engine in ("heavy", "lite"):
            task = TaskViewState(input_type="local", inputs=["paper"], engine=engine)
            task.apply_event({"type": "project_start", "project_name": "paper"})
            task.apply_event({"type": "project_metadata", "project_name": "paper", "title": "研究", "translation_model": "model-a"})
            project = task.projects[0]
            self.assertEqual(getattr(project, "title", None), "研究")
            task.apply_event({"type": "project_complete", "project_name": "paper", "title": None, "translation_model": ""})
            self.assertEqual(project.title, "研究")
            self.assertEqual(project.translation_model, "model-a")
            self.assertEqual(task.completed, 1)

    def test_history_round_trip_and_new_task_model_isolation(self):
        """状态保存保留本任务元数据，覆盖输出的新任务不继承旧模型。"""
        for engine in ("heavy", "lite"):
            with TemporaryDirectory() as directory:
                root = Path(directory)
                output = root / "paper"
                write_project_metadata(output, "task", "local", "paper", "paper", ProjectStatus.RUNNING,
                                       engine=engine, title="研究", translation_model="model-a")
                write_project_metadata(output, "task", "local", "paper", "paper", ProjectStatus.FAILED, engine=engine)
                project = load_output_history(root, engine)[0].projects[0]
                self.assertEqual(project.title, "研究")
                self.assertEqual(project.translation_model, "model-a")
                self.assertEqual(read_project_metadata(output)["schema_version"], 3)
                write_project_metadata(output, "new-task", "local", "paper", "paper", ProjectStatus.RUNNING, engine=engine)
                self.assertFalse(read_project_metadata(output).get("translation_model"))

    def test_legacy_history_recovers_source_title_without_guessing_model(self):
        """旧历史标题来自原文产物，无法恢复的模型保持空值。"""
        for engine in ("heavy", "lite"):
            with TemporaryDirectory() as directory:
                root = Path(directory)
                output = root / "paper"
                output.mkdir()
                if engine == "lite":
                    (output / "source.md").write_text("# 原文标题", encoding="utf-8")
                else:
                    (output / "captions_map.json").write_text(json.dumps([
                        {"cap_type": "icmltitle", "content": r"\icmltitle{原文标题}", "trans_content": "wrong"}
                    ]), encoding="utf-8")
                project = load_output_history(root, engine)[0].projects[0]
                self.assertEqual(project.title, "原文标题")
                self.assertFalse(project.translation_model)
