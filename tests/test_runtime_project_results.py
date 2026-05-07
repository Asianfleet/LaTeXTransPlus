import unittest
from contextlib import redirect_stdout
from io import StringIO
from unittest.mock import patch

from src.runtime import classify_project_result, run_projects, should_exit_with_failure


class RuntimeProjectResultTests(unittest.TestCase):
    def test_classify_project_result_completed(self):
        result = classify_project_result(
            index=1,
            total=2,
            project_name="paper",
            project_dir=r"D:\paper",
            workflow_result={
                "ok": True,
                "pdf_path": r"outputs\ch_paper\ch_paper.pdf",
                "validation_summary": {"warnings": 0, "errors": 0, "total": 0},
            },
        )

        self.assertEqual(result["type"], "completed")
        self.assertTrue(result["ok"])

    def test_classify_project_result_failed(self):
        result = classify_project_result(
            index=1,
            total=2,
            project_name="paper",
            project_dir=r"D:\paper",
            workflow_result={
                "ok": False,
                "pdf_path": r"outputs\ch_paper\ch_paper.pdf",
                "validation_summary": {"warnings": 0, "errors": 1, "total": 1},
            },
        )

        self.assertEqual(result["type"], "failed")
        self.assertFalse(result["ok"])
        self.assertEqual(result["validation_summary"]["errors"], 1)

    def test_classify_project_result_preserves_term_review_status(self):
        result = classify_project_result(
            index=1,
            total=2,
            project_name="paper",
            project_dir=r"D:\paper",
            workflow_result={
                "ok": False,
                "status": "needs_term_review",
                "project_terms_path": r"outputs\ch_paper\project_terms.csv",
                "project_terms_decisions_path": r"outputs\ch_paper\project_terms_decisions.json",
                "error": "review terms",
            },
        )

        self.assertEqual(result["type"], "failed")
        self.assertEqual(result["status"], "needs_term_review")
        self.assertEqual(result["project_terms_path"], r"outputs\ch_paper\project_terms.csv")
        self.assertEqual(
            result["project_terms_decisions_path"],
            r"outputs\ch_paper\project_terms_decisions.json",
        )

    def test_should_exit_with_failure_when_any_project_failed(self):
        self.assertTrue(should_exit_with_failure({
            "completed_projects": [{"project_name": "a"}],
            "failed_projects": [{"project_name": "b"}],
        }))
        self.assertFalse(should_exit_with_failure({
            "completed_projects": [{"project_name": "a"}],
            "failed_projects": [],
        }))

    def test_run_projects_continues_after_workflow_failure_result(self):
        workflow_results = [
            {
                "ok": False,
                "pdf_path": None,
                "validation_summary": {"warnings": 0, "errors": 1, "total": 1},
                "error": None,
            },
            {
                "ok": True,
                "pdf_path": r"outputs\ch_second\ch_second.pdf",
                "validation_summary": {"warnings": 0, "errors": 0, "total": 0},
                "error": None,
            },
        ]
        processed_projects = []

        class FakeCoordinatorAgent:
            def __init__(self, config, project_dir, output_dir):
                processed_projects.append(project_dir)

            def workflow_latextrans(self):
                return workflow_results.pop(0)

        with patch("src.runtime.CoordinatorAgent", FakeCoordinatorAgent):
            with redirect_stdout(StringIO()):
                status = run_projects(
                    config={},
                    projects=[r"D:\first", r"D:\second"],
                    output_dir="outputs",
                )

        self.assertEqual(processed_projects, [r"D:\first", r"D:\second"])
        self.assertEqual(len(status["failed_projects"]), 1)
        self.assertEqual(len(status["completed_projects"]), 1)
        self.assertEqual(status["failed_projects"][0]["project_name"], "first")
        self.assertEqual(status["completed_projects"][0]["project_name"], "second")

    def test_run_projects_uses_retranslation_workflow_when_requested(self):
        calls = []

        class FakeCoordinatorAgent:
            def __init__(self, config, project_dir, output_dir):
                self.project_dir = project_dir

            def workflow_latextrans_with_existing_terms(self):
                calls.append(("retranslate", self.project_dir))
                return {
                    "ok": True,
                    "pdf_path": r"outputs\ch_paper\ch_paper.pdf",
                    "validation_summary": {"warnings": 0, "errors": 0, "total": 0},
                    "error": None,
                }

            def workflow_latextrans(self):
                calls.append(("normal", self.project_dir))
                return {"ok": False, "error": "wrong path"}

        with patch("src.runtime.CoordinatorAgent", FakeCoordinatorAgent):
            with redirect_stdout(StringIO()):
                status = run_projects(
                    config={"retranslate_with_terms": True},
                    projects=[r"D:\paper"],
                    output_dir="outputs",
                )

        self.assertEqual(calls, [("retranslate", r"D:\paper")])
        self.assertEqual(len(status["completed_projects"]), 1)

    def test_run_projects_event_payload_preserves_term_review_status(self):
        events = []

        class FakeCoordinatorAgent:
            def __init__(self, config, project_dir, output_dir):
                pass

            def workflow_latextrans(self):
                return {
                    "ok": False,
                    "status": "needs_term_review",
                    "project_terms_path": r"outputs\ch_paper\project_terms.csv",
                    "project_terms_decisions_path": r"outputs\ch_paper\project_terms_decisions.json",
                    "error": "review terms",
                }

        with patch("src.runtime.CoordinatorAgent", FakeCoordinatorAgent):
            with redirect_stdout(StringIO()):
                run_projects(
                    config={},
                    projects=[r"D:\paper"],
                    output_dir="outputs",
                    event_callback=events.append,
                )

        final_event = events[-1]
        self.assertEqual(final_event["type"], "project_error")
        self.assertEqual(final_event["status"], "needs_term_review")
        self.assertEqual(final_event["project_terms_path"], r"outputs\ch_paper\project_terms.csv")
        self.assertEqual(
            final_event["project_terms_decisions_path"],
            r"outputs\ch_paper\project_terms_decisions.json",
        )


if __name__ == "__main__":
    unittest.main()
