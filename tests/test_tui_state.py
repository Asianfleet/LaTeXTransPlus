"""Tests for Textual UI task state merging."""

import json
import tempfile
import unittest
from pathlib import Path

from src.tui.history import load_output_history
from src.tui.state import ProjectStatus, TaskViewState


class TuiStateTests(unittest.TestCase):
    """Regression tests for runtime event merging into UI state."""

    def test_apply_run_start_sets_total(self):
        """run_start events should set the task total."""
        state = TaskViewState(input_type="arxiv", inputs=["2508.18791"])
        state.apply_event({"type": "run_start", "total": 2})
        self.assertEqual(state.total, 2)

    def test_project_lifecycle_events_update_counts_and_paths(self):
        """Project lifecycle events should update status, counts, and paths."""
        state = TaskViewState(input_type="arxiv", inputs=["2508.18791"])
        state.apply_event(
            {
                "type": "project_start",
                "project_name": "2508.18791",
                "project_dir": r"D:\src",
                "output_dir": r"D:\out",
                "log_path": r"D:\out\latextrans.log",
            }
        )
        self.assertEqual(state.projects[0].status, ProjectStatus.RUNNING)

        state.apply_event(
            {
                "type": "project_complete",
                "project_name": "2508.18791",
                "project_dir": r"D:\src",
                "output_dir": r"D:\out",
                "pdf_path": r"D:\out\ch_2508.18791.pdf",
                "errors_report_path": r"D:\out\errors_report.json",
                "validation_summary": {"warnings": 0, "errors": 0, "total": 0},
                "log_path": r"D:\out\latextrans.log",
            }
        )

        self.assertEqual(state.completed, 1)
        self.assertEqual(state.failed, 0)
        self.assertEqual(state.projects[0].status, ProjectStatus.COMPLETED)
        self.assertEqual(state.projects[0].pdf_path, r"D:\out\ch_2508.18791.pdf")

    def test_project_lifecycle_events_copy_terms_paths(self):
        """Project lifecycle events should preserve generated terminology paths."""
        state = TaskViewState(input_type="arxiv", inputs=["2508.18791"])
        state.apply_event(
            {
                "type": "project_complete",
                "project_name": "2508.18791",
                "project_terms_path": r"D:\out\project_terms.csv",
                "project_terms_decisions_path": r"D:\out\project_terms_decisions.json",
            }
        )

        self.assertEqual(state.projects[0].project_terms_path, r"D:\out\project_terms.csv")
        self.assertEqual(
            state.projects[0].project_terms_decisions_path,
            r"D:\out\project_terms_decisions.json",
        )

    def test_review_required_event_marks_project_terms_ready(self):
        """等待术语确认的项目应显示为术语就绪，而不是失败。"""
        state = TaskViewState(input_type="arxiv", inputs=["2508.18791"], total=1)
        state.apply_event(
            {
                "type": "project_error",
                "project_name": "2508.18791",
                "status": "needs_term_review",
                "project_terms_path": r"D:\out\project_terms.csv",
                "project_terms_decisions_path": r"D:\out\project_terms_decisions.json",
            }
        )

        self.assertEqual(state.projects[0].status, ProjectStatus.TERMS_READY)
        self.assertEqual(state.completed, 0)
        self.assertEqual(state.failed, 0)

    def test_project_error_updates_failed_count(self):
        """project_error events should mark failed projects and count them."""
        state = TaskViewState(input_type="remote", inputs=["https://example.test/paper.zip"])
        state.apply_event({"type": "project_error", "project_name": "paper", "error": "boom"})
        self.assertEqual(state.failed, 1)
        self.assertEqual(state.projects[0].status, ProjectStatus.FAILED)
        self.assertEqual(state.projects[0].error, "boom")

    def test_project_log_event_appends_project_log_lines(self):
        """project_log 事件应追加到对应项目的内存日志。"""
        state = TaskViewState(input_type="arxiv", inputs=["2508.18791"])

        state.apply_event(
            {
                "type": "project_log",
                "project_name": "2508.18791",
                "line": "[ParserAgent] [INFO] parsed",
            }
        )

        self.assertEqual(state.projects[0].log_lines, ["[ParserAgent] [INFO] parsed"])
        self.assertEqual(state.completed, 0)
        self.assertEqual(state.failed, 0)

    def test_task_log_event_does_not_create_project(self):
        """无项目归属的准备日志应保存在任务状态，不创建虚假项目。"""
        state = TaskViewState(input_type="arxiv", inputs=["2508.18791"])

        state.apply_event({"type": "task_log", "line": "preparing"})

        self.assertEqual(state.projects, [])
        self.assertEqual(state.task_log_lines, ["preparing"])

    def test_cancelled_status_is_a_stopped_project_state(self):
        """强制终止事件应标记取消状态且不计入成功或失败。"""
        state = TaskViewState(input_type="arxiv", inputs=["paper"], total=1)
        state.apply_event(
            {
                "type": "project_cancelled",
                "project_name": "paper",
                "output_dir": r"D:\\out",
                "error": "terminated",
            }
        )

        self.assertEqual(state.projects[0].status, ProjectStatus.CANCELLED)
        self.assertEqual(state.completed, 0)
        self.assertEqual(state.failed, 0)
        self.assertEqual(state.projects[0].output_dir, r"D:\\out")

    def test_cancelled_event_takes_priority_over_review_status(self):
        """取消事件即使携带术语状态也必须保持 cancelled。"""
        state = TaskViewState(input_type="arxiv", inputs=["paper"], total=1)
        state.apply_event(
            {
                "type": "project_cancelled",
                "project_name": "paper",
                "status": "needs_term_review",
            }
        )
        self.assertEqual(state.projects[0].status, ProjectStatus.CANCELLED)

    def test_history_metadata_loads_cancelled_status(self):
        """历史元数据中的 cancelled 状态应恢复为取消项目。"""
        with tempfile.TemporaryDirectory() as temp_dir:
            output_root = Path(temp_dir)
            project_dir = output_root / "paper"
            project_dir.mkdir()
            (project_dir / ".latextrans-tui.json").write_text(
                json.dumps(
                    {
                        "task_id": "task-1",
                        "input_type": "arxiv",
                        "input_item": "paper",
                        "project_name": "paper",
                        "status": "cancelled",
                    }
                ),
                encoding="utf-8",
            )

            tasks = load_output_history(output_root)

        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0].projects[0].status, ProjectStatus.CANCELLED)
        self.assertEqual(tasks[0].completed, 0)
        self.assertEqual(tasks[0].failed, 0)


if __name__ == "__main__":
    unittest.main()
