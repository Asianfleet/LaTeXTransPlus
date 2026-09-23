"""Public workflow contract tests for the lite translation engine."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.runtime import run_engine_task


class SuccessfulLiteEngine:
    """Provide a deterministic completed Lite result at the runtime boundary."""

    def run(
        self,
        input_item: str,
        config: dict[str, object],
        output_root: Path,
        log_callback: object = None,
    ) -> dict[str, object]:
        """Return the artifact paths expected from a successful Lite workflow."""
        project_dir = output_root / "paper_20260910T120000"
        return {
            "ok": True,
            "engine": "lite",
            "project_name": project_dir.name,
            "project_dir": str(project_dir),
            "output_dir": str(project_dir),
            "source_markdown_path": str(project_dir / "source.md"),
            "translated_markdown_path": str(project_dir / "translated.md"),
            "pdf_path": str(project_dir / "translated.pdf"),
            "project_terms_path": str(project_dir / "project_terms.csv"),
            "project_terms_decisions_path": str(
                project_dir / "project_terms_decisions.json"
            ),
            "error": None,
        }


class LiteIntegrationTests(unittest.TestCase):
    """Verify the public Lite runtime event contract."""

    def test_lite_complete_event_contains_markdown_paths_without_validation_report(self):
        """A completed Lite project should expose Markdown artifacts only."""
        events: list[dict[str, object]] = []

        with tempfile.TemporaryDirectory() as temporary_directory:
            output_root = Path(temporary_directory) / "output-lite"
            with patch("src.runtime.LiteEngine", SuccessfulLiteEngine):
                run_engine_task(
                    "lite",
                    "pdf",
                    ["paper.pdf"],
                    {"lite": {"output_dir": str(output_root)}},
                    events.append,
                )

        complete = next(event for event in events if event["type"] == "project_complete")
        self.assertEqual(complete["engine"], "lite")
        self.assertIn("source_markdown_path", complete)
        self.assertIn("translated_markdown_path", complete)
        self.assertNotIn("errors_report_path", complete)
        self.assertNotIn("validation_summary", complete)


if __name__ == "__main__":
    unittest.main()
