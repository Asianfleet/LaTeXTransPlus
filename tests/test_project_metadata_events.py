"""两种引擎标题事件和任务模型快照回归测试。"""

import asyncio
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from src.agents.coordinator_agent import CoordinatorAgent
from src.engines.lite import LiteEngine
from src.tui.runner import run_tui_task


class ProjectMetadataEventTests(unittest.TestCase):
    """验证标题在翻译前可用，模型来自本次运行的有效配置。"""

    def test_heavy_emits_title_before_unsupported_source_failure(self):
        """即使解析后判定不支持，也先发送已提取的标题。"""
        events = []
        with TemporaryDirectory() as directory:
            root = Path(directory)
            config = {"target_language": "ch", "llm_config": {"model": "model-a"},
                      "_project_metadata_callback": events.append}
            agent = CoordinatorAgent(config=config, project_dir=str(root / "paper"), output_dir=str(root / "out"))
            with patch("src.agents.coordinator_agent.ParserAgent"), patch(
                "src.agents.coordinator_agent.read_parsed_latex_maps",
                return_value=([], [{"cap_type": "title", "content": r"\title{研究 Title}"}], [])
            ), patch("src.agents.coordinator_agent.is_pdf_only_latex_source", return_value=True), patch(
                "src.agents.coordinator_agent.save_unsupported_source_report"
            ):
                asyncio.run(agent.workflow_latextrans_async())
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["title"], "研究 Title")
        self.assertEqual(events[0]["type"], "project_metadata")

    def test_lite_emits_title_before_translation_failure(self):
        """Markdown 已提取但术语生成失败时，标题事件仍能到达 TUI。"""
        events = []
        with TemporaryDirectory() as directory:
            root = Path(directory)
            markdown = root / "source.md"
            markdown.write_text("# 原文 Title\n", encoding="utf-8")
            prepared = Mock(project_name="paper", project_dir=root, source_pdf=root / "source.pdf")
            mineru = Mock()
            mineru.extract.return_value = markdown
            terminology = Mock()
            terminology.execute.return_value = {"ok": False, "error": "expected failure"}
            engine = LiteEngine(input_parser=Mock(), project_preparer=Mock(return_value=prepared),
                                mineru=mineru, terminology=Mock(return_value=terminology))
            result = engine.run("paper.pdf", {"llm_config": {"model": "model-a"},
                                             "_project_metadata_callback": events.append}, root, events.append)
        metadata = [event for event in events if event.get("type") == "project_metadata"]
        self.assertEqual(len(metadata), 1)
        self.assertEqual(metadata[0]["title"], "原文 Title")
        self.assertFalse(result["ok"])

    def test_runner_freezes_resolved_model_for_both_engines(self):
        """事件中的模型不受后续修改配置影响，并不传播其他 LLM 配置。"""
        for engine in ("heavy", "lite"):
            events = []
            config = {"llm_config": {"model": "effective-model"}}

            def fake_run(**kwargs):
                """模拟运行期间配置变化与终止事件。"""
                kwargs["config"]["llm_config"]["model"] = "changed-model"
                kwargs["event_callback"]({"type": "project_metadata", "project_name": "paper", "title": "Title"})
                kwargs["event_callback"]({"type": "project_error", "project_name": "paper"})
                return {"projects": ["paper"]}

            with patch("src.tui.runner.ensure_ui_config", return_value=Path("ui.toml")), patch(
                "src.tui.runner.runtime.load_runtime_config", return_value=config
            ), patch("src.tui.runner.runtime.run_engine_task", side_effect=fake_run):
                run_tui_task("ui.toml", "local", ["paper"], {}, events.append, engine=engine)
            projects = [event for event in events if event.get("project_name")]
            self.assertEqual([event.get("translation_model") for event in projects], ["effective-model"] * 2)
            self.assertTrue(all("llm_config" not in event for event in projects))
