import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from src.tui.history import (
    TUI_PROJECT_METADATA_FILENAME,
    infer_project_status,
    load_output_history,
    write_project_metadata,
)
from src.tui.state import ProjectStatus


class TuiHistoryTests(unittest.TestCase):
    """验证 TUI 会从 outputs 目录恢复历史项目并推断状态。"""

    def test_load_output_history_adds_legacy_project_with_empty_task_id(self):
        """确认旧版输出目录没有元数据时会以空任务 id 加入历史列表。"""
        with TemporaryDirectory() as temp_dir:
            output_root = Path(temp_dir) / "outputs"
            project_dir = output_root / "ch_2308.10248"
            project_dir.mkdir(parents=True)
            (project_dir / "ch_2308.10248.pdf").write_bytes(b"%PDF")
            (project_dir / "errors_report.json").write_text("[]", encoding="utf-8")

            tasks = load_output_history(output_root)

            self.assertEqual(len(tasks), 1)
            self.assertEqual(tasks[0].task_id, "")
            self.assertEqual(tasks[0].projects[0].project_name, "2308.10248")
            self.assertEqual(tasks[0].projects[0].status, ProjectStatus.COMPLETED)

    def test_load_output_history_restores_task_id_from_metadata(self):
        """确认新版输出目录会从元数据恢复任务 id。"""
        with TemporaryDirectory() as temp_dir:
            output_root = Path(temp_dir) / "outputs"
            project_dir = output_root / "ch_paper"
            project_dir.mkdir(parents=True)
            (project_dir / "ch_paper.pdf").write_bytes(b"%PDF")
            (project_dir / "errors_report.json").write_text("[]", encoding="utf-8")
            (project_dir / TUI_PROJECT_METADATA_FILENAME).write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "task_id": "20260701T175144.123",
                        "input_type": "local",
                        "input_item": "paper",
                        "project_name": "paper",
                        "status": "completed",
                    }
                ),
                encoding="utf-8",
            )

            tasks = load_output_history(output_root)

            self.assertEqual(len(tasks), 1)
            self.assertEqual(tasks[0].task_id, "20260701T175144.123")
            self.assertEqual(tasks[0].input_type, "local")
            self.assertEqual(tasks[0].inputs, ["paper"])
            self.assertIsNotNone(tasks[0].projects[0].project_dir)
            self.assertTrue(tasks[0].projects[0].project_dir.endswith("ch_paper"))
            self.assertEqual(tasks[0].projects[0].project_dir, str(project_dir))

    def test_infer_project_status_uses_errors_pdf_terms_and_artifacts(self):
        """确认旧版和新版项目可按产物推断 completed、failed、terms_ready 和 pending。"""
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            completed = root / "ch_done"
            completed.mkdir()
            (completed / "ch_done.pdf").write_bytes(b"%PDF")
            (completed / "errors_report.json").write_text("[]", encoding="utf-8")

            failed = root / "ch_failed"
            failed.mkdir()
            (failed / "errors_report.json").write_text('[{"error": "bad"}]', encoding="utf-8")

            terms_ready = root / "ch_terms"
            terms_ready.mkdir()
            (terms_ready / "project_terms.csv").write_text("Source Term,Target Translation\nA,B\n", encoding="utf-8")

            pending = root / "ch_pending"
            pending.mkdir()

            self.assertEqual(infer_project_status(completed), ProjectStatus.COMPLETED)
            self.assertEqual(infer_project_status(failed), ProjectStatus.FAILED)
            self.assertEqual(infer_project_status(terms_ready), ProjectStatus.TERMS_READY)
            self.assertEqual(infer_project_status(pending), ProjectStatus.PENDING)

    def test_running_metadata_is_not_restored_as_running_history(self):
        """确认历史加载不会把上次会话残留的 running 元数据继续显示为 running。"""
        with TemporaryDirectory() as temp_dir:
            output_root = Path(temp_dir) / "outputs"
            project_dir = output_root / "ch_running"
            project_dir.mkdir(parents=True)
            (project_dir / "sections_map.json").write_text("[]", encoding="utf-8")
            (project_dir / TUI_PROJECT_METADATA_FILENAME).write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "task_id": "20260701T175144.123",
                        "project_name": "running",
                        "status": "running",
                    }
                ),
                encoding="utf-8",
            )

            tasks = load_output_history(output_root)

            self.assertEqual(tasks[0].projects[0].status, ProjectStatus.FAILED)

    def test_write_project_metadata_persists_timestamp_task_id(self):
        """确认新版任务会把时间戳任务 id 写入项目输出目录元数据。"""
        with TemporaryDirectory() as temp_dir:
            project_dir = Path(temp_dir) / "outputs" / "ch_paper"
            project_dir.mkdir(parents=True)

            write_project_metadata(
                project_dir=project_dir,
                task_id="20260701T175144.123",
                input_type="arxiv",
                input_item="2308.10248",
                project_name="2308.10248",
                status=ProjectStatus.COMPLETED,
            )

            metadata = json.loads((project_dir / TUI_PROJECT_METADATA_FILENAME).read_text(encoding="utf-8"))
            self.assertEqual(metadata["task_id"], "20260701T175144.123")
            self.assertEqual(metadata["status"], "completed")
            self.assertEqual(metadata["input_item"], "2308.10248")


class TuiHistoryEngineTests(unittest.TestCase):
    """Verify history and metadata remain isolated by translation engine."""

    def test_history_filters_mixed_engine_metadata(self):
        """A scan should only return projects for the requested engine."""
        with TemporaryDirectory() as temp_dir:
            output_root = Path(temp_dir) / "mixed"
            heavy_dir = output_root / "ch_heavy"
            lite_dir = output_root / "lite-paper"
            heavy_dir.mkdir(parents=True)
            lite_dir.mkdir()
            (heavy_dir / "ch_heavy.pdf").write_bytes(b"%PDF")
            (lite_dir / "source.pdf").write_bytes(b"%PDF source")
            (lite_dir / "source.md").write_text("# Source", encoding="utf-8")
            (lite_dir / "translated.md").write_text("# Translated", encoding="utf-8")
            (lite_dir / "translated.pdf").write_bytes(b"%PDF translated")
            write_project_metadata(
                heavy_dir,
                "heavy-task",
                "arxiv",
                "heavy",
                "heavy",
                ProjectStatus.COMPLETED,
                engine="heavy",
            )
            write_project_metadata(
                lite_dir,
                "lite-task",
                "pdf",
                "paper.pdf",
                "lite-paper",
                ProjectStatus.COMPLETED,
                engine="lite",
                source_markdown_path=str(lite_dir / "source.md"),
                translated_markdown_path=str(lite_dir / "translated.md"),
            )

            heavy_tasks = load_output_history(output_root, engine="heavy")
            lite_tasks = load_output_history(output_root, engine="lite")

        self.assertEqual([task.task_id for task in heavy_tasks], ["heavy-task"])
        self.assertEqual([task.task_id for task in lite_tasks], ["lite-task"])
        self.assertEqual(lite_tasks[0].engine, "lite")
        self.assertEqual(lite_tasks[0].projects[0].engine, "lite")

    def test_history_reads_lite_artifacts_without_error_report(self):
        """Metadata-free lite output should use translated artifacts and no errors path."""
        with TemporaryDirectory() as temp_dir:
            output_root = Path(temp_dir) / "output-lite"
            project_dir = output_root / "paper_20260910T120000"
            project_dir.mkdir(parents=True)
            (project_dir / "source.pdf").write_bytes(b"%PDF source")
            (project_dir / "source.md").write_text("# Source", encoding="utf-8")
            (project_dir / "translated.md").write_text("# Translated", encoding="utf-8")
            translated_pdf = project_dir / "translated.pdf"
            translated_pdf.write_bytes(b"%PDF translated")

            tasks = load_output_history(output_root, engine="lite")

        project = tasks[0].projects[0]
        self.assertEqual(project.status, ProjectStatus.COMPLETED)
        self.assertEqual(project.engine, "lite")
        self.assertTrue(project.source_markdown_path.endswith("source.md"))
        self.assertTrue(project.translated_markdown_path.endswith("translated.md"))
        self.assertTrue(project.pdf_path.endswith("translated.pdf"))
        self.assertIsNone(project.errors_report_path)

    def test_lite_source_pdf_is_not_mistaken_for_completed_translation(self):
        """A copied source PDF alone should represent an incomplete lite run."""
        with TemporaryDirectory() as temp_dir:
            project_dir = Path(temp_dir) / "paper"
            project_dir.mkdir()
            (project_dir / "source.pdf").write_bytes(b"%PDF source")
            (project_dir / "source.md").write_text("# Source", encoding="utf-8")

            status = infer_project_status(project_dir, engine="lite")

        self.assertEqual(status, ProjectStatus.FAILED)

    def test_version_one_metadata_defaults_to_heavy(self):
        """Metadata written before engine support should only appear in heavy history."""
        with TemporaryDirectory() as temp_dir:
            output_root = Path(temp_dir) / "outputs"
            project_dir = output_root / "ch_legacy"
            project_dir.mkdir(parents=True)
            (project_dir / "ch_legacy.pdf").write_bytes(b"%PDF")
            (project_dir / TUI_PROJECT_METADATA_FILENAME).write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "task_id": "legacy-task",
                        "project_name": "legacy",
                        "status": "completed",
                    }
                ),
                encoding="utf-8",
            )

            heavy_tasks = load_output_history(output_root, engine="heavy")
            lite_tasks = load_output_history(output_root, engine="lite")

        self.assertEqual([task.task_id for task in heavy_tasks], ["legacy-task"])
        self.assertEqual(lite_tasks, [])

    def test_write_metadata_uses_schema_two_and_markdown_paths(self):
        """Engine-aware metadata should persist all lite history fields."""
        with TemporaryDirectory() as temp_dir:
            project_dir = Path(temp_dir) / "paper"
            write_project_metadata(
                project_dir,
                "task-2",
                "pdf",
                "paper.pdf",
                "paper",
                ProjectStatus.COMPLETED,
                engine="lite",
                source_markdown_path="source.md",
                translated_markdown_path="translated.md",
            )

            metadata = json.loads(
                (project_dir / TUI_PROJECT_METADATA_FILENAME).read_text(encoding="utf-8")
            )

        self.assertEqual(metadata["schema_version"], 2)
        self.assertEqual(metadata["engine"], "lite")
        self.assertEqual(metadata["source_markdown_path"], "source.md")
        self.assertEqual(metadata["translated_markdown_path"], "translated.md")


if __name__ == "__main__":
    unittest.main()
