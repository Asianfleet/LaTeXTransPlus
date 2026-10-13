"""验证生成 PDF 后仍有校验错误的独立完成状态。"""

import json
import os
import unittest
from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from src.tui.app import PAGE_TASKS, LaTeXTransTuiApp, ProjectManagementTable
from src.tui.history import load_output_history, write_project_metadata
from src.tui.state import ProjectStatus, TaskViewState


class CompletedErrorsTests(unittest.TestCase):
    """覆盖实时事件、历史兼容和完成统计。"""

    def test_pdf_with_validation_errors_is_completed_with_errors(self):
        """严格和宽松校验策略的终态事件都显示未解决错误数。"""
        for event_type in ("project_error", "project_complete"):
            with self.subTest(event_type=event_type):
                task = TaskViewState(input_type="arxiv", inputs=["paper"], total=1)
                task.apply_event({
                    "type": event_type, "project_name": "paper",
                    "pdf_path": "translated.pdf",
                    "validation_summary": {"errors": 2, "warnings": 1, "total": 3},
                })
                project = task.projects[0]
                self.assertEqual(project.status.value, "completed_with_errors")
                self.assertEqual(project.status_label, "completed(2errors)")
                self.assertEqual((task.completed, task.failed), (1, 0))
                app = LaTeXTransTuiApp(load_history_on_mount=False)
                self.assertTrue(app._task_is_finished(task))
                app._notify = Mock()
                app._notify_task_event(task.events[-1], task)
                self.assertIn("2", app._notify.call_args_list[0].args[0])
                self.assertEqual(app._notify.call_args_list[0].kwargs["severity"], "warning")

    def test_pdf_generation_failure_and_cancellation_keep_their_status(self):
        """残留 PDF 不应掩盖明确的生成失败或取消。"""
        for event, expected in (
            ({"type": "project_error", "pdf_error": "compile failed"}, ProjectStatus.FAILED),
            ({"type": "project_cancelled"}, ProjectStatus.CANCELLED),
            ({"type": "project_error", "pdf_path": None}, ProjectStatus.FAILED),
        ):
            with self.subTest(event=event):
                task = TaskViewState(input_type="arxiv", inputs=["paper"])
                task.apply_event({
                    "project_name": "paper", "pdf_path": "old.pdf",
                    "validation_summary": {"errors": 1}, **event,
                })
                self.assertEqual(task.projects[0].status, expected)

    def test_legacy_failed_history_with_pdf_restores_error_count(self):
        """旧 failed 元数据结合 PDF 和最终报告恢复独立完成状态。"""
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output = root / "ch_paper"
            write_project_metadata(output, "task", "arxiv", "paper", "paper", ProjectStatus.FAILED)
            (output / "ch_paper.pdf").write_bytes(b"%PDF")
            (output / "errors_report.json").write_text(json.dumps([
                {"severity": "error"}, {"severity": "warning"}, {"severity": "error"},
            ]), encoding="utf-8")
            task = load_output_history(root)[0]
            self.assertEqual(task.projects[0].status.value, "completed_with_errors")
            self.assertEqual(task.projects[0].status_label, "completed(2errors)")
            self.assertEqual((task.completed, task.failed), (1, 0))

    def test_warning_only_history_remains_completed(self):
        """警告不计入未解决错误数。"""
        with TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "ch_paper"
            output.mkdir()
            (output / "ch_paper.pdf").write_bytes(b"%PDF")
            (output / "errors_report.json").write_text('[{"severity": "warning"}]', encoding="utf-8")
            project = load_output_history(Path(temp_dir))[0].projects[0]
            self.assertEqual(project.status, ProjectStatus.COMPLETED)
            self.assertEqual(project.status_label, "completed")

    def test_summary_is_persisted_without_report(self):
        """持久化的错误数可在最终报告缺失时恢复。"""
        with TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "ch_paper"
            write_project_metadata(
                output, "task", "arxiv", "paper", "paper",
                ProjectStatus.COMPLETED_WITH_ERRORS,
                validation_summary={"errors": 3, "warnings": 0, "total": 3},
            )
            (output / "ch_paper.pdf").write_bytes(b"%PDF")
            project = load_output_history(Path(temp_dir))[0].projects[0]
            self.assertEqual(project.status_label, "completed(3errors)")

    def test_history_preserves_cancelled_and_pdf_failure(self):
        """历史中的残留 PDF 不掩盖取消和明确的编译失败。"""
        for status, pdf_error in ((ProjectStatus.CANCELLED, None), (ProjectStatus.FAILED, "compile failed")):
            with self.subTest(status=status), TemporaryDirectory() as temp_dir:
                output = Path(temp_dir) / "ch_paper"
                write_project_metadata(
                    output, "task", "arxiv", "paper", "paper", status,
                    validation_summary={"errors": 1}, pdf_error=pdf_error,
                )
                (output / "ch_paper.pdf").write_bytes(b"%PDF")
                project = load_output_history(Path(temp_dir))[0].projects[0]
                self.assertEqual(project.status, status)

    def test_unreadable_report_is_not_a_completed_validation_result(self):
        """损坏的报告无法提供错误数，不能据此宣称任务已完成。"""
        with TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "ch_paper"
            output.mkdir()
            (output / "ch_paper.pdf").write_bytes(b"%PDF")
            (output / "errors_report.json").write_text("{broken", encoding="utf-8")
            project = load_output_history(Path(temp_dir))[0].projects[0]
            self.assertEqual(project.status, ProjectStatus.FAILED)


class CompletedErrorsUiTests(unittest.IsolatedAsyncioTestCase):
    """在临时工作目录验证项目表与元数据同步。"""

    async def test_project_table_displays_error_count_and_persists_state(self):
        """实时状态和重载历史显示相同的 completed(nerrors)。"""
        original_cwd = Path.cwd()
        with TemporaryDirectory() as temp_dir, ExitStack() as stack:
            os.chdir(temp_dir)
            try:
                for target, value in {
                    "src.tui.app.load_ui_config": {},
                    "src.tui.config_page.load_ui_config": {},
                    "src.tui.config_page.list_llm_profiles": [],
                    "src.tui.config_page.list_available_font_families": [],
                }.items():
                    stack.enter_context(patch(target, return_value=value))
                for target in ("src.tui.config.save_ui_config", "src.tui.config_page.save_ui_config"):
                    stack.enter_context(patch(target))
                output = Path(temp_dir) / "outputs" / "ch_paper"
                output.mkdir(parents=True)
                pdf = output / "ch_paper.pdf"
                pdf.write_bytes(b"%PDF")
                app = LaTeXTransTuiApp(load_history_on_mount=False)
                task = TaskViewState(input_type="arxiv", inputs=["paper"], task_id="task", total=1)
                app.tasks = [task]
                async with app.run_test(size=(120, 40)) as pilot:
                    app.handle_runtime_event({
                        "type": "project_error", "project_name": "paper",
                        "output_dir": str(output), "pdf_path": str(pdf),
                        "validation_summary": {"errors": 2, "warnings": 0, "total": 2},
                    }, task)
                    app.switch_page(PAGE_TASKS)
                    await pilot.pause()
                    table = app.query_one("#task-table", ProjectManagementTable)
                    self.assertEqual(table.get_row_at(0)[4], "completed(2errors)")
                    self.assertEqual(load_output_history(output.parent)[0].projects[0].status_label, "completed(2errors)")
            finally:
                os.chdir(original_cwd)
