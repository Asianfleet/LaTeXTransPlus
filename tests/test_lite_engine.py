"""End-to-end tests for lite orchestration and engine-aware runtime dispatch."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.engines.lite import LiteEngine
from src.runtime import run_engine_task


class _FakeMineru:
    """Write deterministic Markdown without invoking the MinerU SDK."""

    def extract(self, source_pdf: Path, output_dir: Path) -> Path:
        """Record a valid source Markdown artifact in the project directory."""
        if source_pdf != output_dir / "source.pdf":
            raise AssertionError("MinerU must receive the project-local source PDF")
        markdown_path = output_dir / "source.md"
        markdown_path.write_text("# Paper\n\n## Method\nSource body.\n", encoding="utf-8")
        return markdown_path


class _FakeTerminology:
    """Act as an injectable Markdown terminology-agent factory and instance."""

    def __call__(
        self,
        config: dict[str, object],
        markdown_path: Path,
        output_dir: Path,
    ) -> "_FakeTerminology":
        """Capture the paths supplied by the lite engine."""
        self.markdown_path = markdown_path
        self.output_dir = output_dir
        return self

    def execute(self) -> dict[str, object]:
        """Create both terminology artifacts and return their paths."""
        terms_path = self.output_dir / "project_terms.csv"
        decisions_path = self.output_dir / "project_terms_decisions.json"
        terms_path.write_text("source_term,target_term\nbody,正文\n", encoding="utf-8")
        decisions_path.write_text("{}\n", encoding="utf-8")
        return {
            "ok": True,
            "project_terms_path": str(terms_path),
            "project_terms_decisions_path": str(decisions_path),
        }


class _FakeTranslator:
    """Act as an injectable asynchronous Markdown translator factory."""

    def __call__(
        self,
        config: dict[str, object],
        source_markdown: Path,
        output_dir: Path,
        blocks: object,
    ) -> "_FakeTranslator":
        """Capture source, output, and split blocks supplied by orchestration."""
        self.source_markdown = source_markdown
        self.output_dir = output_dir
        self.blocks = tuple(blocks)
        return self

    async def execute(self) -> Path:
        """Write one deterministic translated Markdown artifact."""
        if len(self.blocks) != 2:
            raise AssertionError("Markdown must be split before translation")
        translated_path = self.output_dir / "translated.md"
        translated_path.write_text("# 论文\n\n## 方法\n译文。\n", encoding="utf-8")
        return translated_path


class _FailingTranslator(_FakeTranslator):
    """Raise after earlier lite stages have produced their artifacts."""

    async def execute(self) -> Path:
        """Simulate a final provider failure for one Markdown block."""
        raise RuntimeError("translation provider failed")


class _FakePdfGenerator:
    """Write a deterministic nonempty PDF placeholder."""

    def generate(
        self,
        markdown_path: Path,
        pdf_path: Path,
        target_language: str,
    ) -> Path:
        """Verify translated Markdown is used and create the requested PDF."""
        if markdown_path.name != "translated.md":
            raise AssertionError("Pandoc must receive translated Markdown")
        if target_language != "ch":
            raise AssertionError("Target language must reach the PDF generator")
        pdf_path.write_bytes(b"%PDF-fake")
        return pdf_path


class LiteEngineTests(unittest.TestCase):
    """Verify the complete lite pipeline without network or external tools."""

    def _run_engine(self, root: Path, translator: object | None = None):
        """Run a lite engine with deterministic injected stage dependencies."""
        source_pdf = root / "paper.pdf"
        source_pdf.write_bytes(b"%PDF-source")
        logs: list[dict[str, object]] = []
        engine = LiteEngine(
            mineru=_FakeMineru(),
            terminology=_FakeTerminology(),
            translator=translator or _FakeTranslator(),
            pdf_generator=_FakePdfGenerator(),
        )
        result = engine.run(
            str(source_pdf),
            {"source_language": "en", "target_language": "ch"},
            root / "output-lite",
            logs.append,
        )
        return result, logs

    def test_run_creates_all_artifacts_in_one_timestamped_project_directory(self):
        """Every successful lite artifact should share one timestamped directory."""
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            result, logs = self._run_engine(root)

            self.assertTrue(result["ok"])
            self.assertEqual(result["engine"], "lite")
            project_dir = Path(result["project_dir"])
            self.assertEqual(Path(result["output_dir"]), project_dir)
            self.assertRegex(project_dir.name, r"^paper_\d{8}T\d{6}(?:_\d+)?$")
            for artifact_name in (
                "source.pdf",
                "source.md",
                "translated.md",
                "translated.pdf",
                "project_terms.csv",
                "project_terms_decisions.json",
            ):
                self.assertTrue((project_dir / artifact_name).is_file(), artifact_name)
            self.assertFalse((project_dir / "errors_report.json").exists())
            self.assertNotIn("errors_report_path", result)
            self.assertNotIn("validation_summary", result)
            self.assertIsNone(result["error"])

        log_text = "\n".join(str(event["message"]) for event in logs)
        for milestone in ("input", "MinerU", "terminology", "translation", "PDF"):
            self.assertIn(milestone, log_text)

    def test_translation_failure_returns_existing_paths_without_validation_fields(self):
        """A failed late stage should retain paths to every earlier artifact."""
        with tempfile.TemporaryDirectory() as temp_dir:
            result, logs = self._run_engine(Path(temp_dir), _FailingTranslator())

            self.assertFalse(result["ok"])
            self.assertEqual(result["engine"], "lite")
            self.assertIn("translation provider failed", result["error"])
            self.assertTrue(Path(result["source_markdown_path"]).is_file())
            self.assertTrue(Path(result["project_terms_path"]).is_file())
            self.assertTrue(Path(result["project_terms_decisions_path"]).is_file())
            self.assertIsNone(result["translated_markdown_path"])
            self.assertIsNone(result["pdf_path"])
            self.assertNotIn("errors_report_path", result)
            self.assertNotIn("validation_summary", result)

        self.assertEqual(logs[-1]["level"], "error")


class RuntimeEngineDispatchTests(unittest.TestCase):
    """Verify lite dispatch, effective configuration, and failure event payloads."""

    def test_lite_failure_events_include_artifacts_without_heavy_only_fields(self):
        """Lite start and error events must carry engine-specific artifact fields."""
        events: list[dict[str, object]] = []

        class _FailingLiteEngine:
            """Expose a prepared project and then return a failed lite result."""

            def run(self, input_item, config, output_root, log_callback=None):
                """Assert effective config and publish one prepared-stage log."""
                self.effective_config = config
                project_dir = Path(output_root) / "paper_20260910T120000"
                source_markdown = project_dir / "source.md"
                if log_callback:
                    log_callback(
                        {
                            "level": "info",
                            "message": "Lite input preparation completed.",
                            "line": "Lite input preparation completed.",
                            "project_name": project_dir.name,
                            "project_dir": str(project_dir),
                            "output_dir": str(project_dir),
                            "source_markdown_path": str(source_markdown),
                        }
                    )
                return {
                    "ok": False,
                    "engine": "lite",
                    "project_name": project_dir.name,
                    "project_dir": str(project_dir),
                    "output_dir": str(project_dir),
                    "source_markdown_path": str(source_markdown),
                    "translated_markdown_path": None,
                    "pdf_path": None,
                    "project_terms_path": None,
                    "project_terms_decisions_path": None,
                    "error": "MinerU failed",
                }

        with tempfile.TemporaryDirectory() as temp_dir:
            config = {
                "source_language": "en",
                "target_language": "ch",
                "heavy": {
                    "output_dir": "heavy-output",
                    "validation": {"retry": {"max_attempts": 3}},
                },
                "lite": {"output_dir": str(Path(temp_dir) / "output-lite")},
            }
            with patch("src.runtime.LiteEngine", _FailingLiteEngine):
                result = run_engine_task("lite", "pdf", ["paper.pdf"], config, events.append)

        self.assertEqual(len(result["failed_projects"]), 1)
        self.assertEqual(result["config"]["engine"], "lite")
        self.assertEqual(result["config"]["output_dir"], config["lite"]["output_dir"])
        for heavy_only_key in ("heavy", "lite", "validation", "tex_sources_dir"):
            self.assertNotIn(heavy_only_key, result["config"])
        self.assertEqual(events[0]["type"], "project_start")
        self.assertEqual(events[-1]["type"], "project_error")
        for event in (events[0], events[-1]):
            self.assertEqual(event["engine"], "lite")
            self.assertIn("source_markdown_path", event)
            self.assertIn("translated_markdown_path", event)
            self.assertIn("pdf_path", event)
            self.assertIn("project_terms_path", event)
            self.assertIn("project_terms_decisions_path", event)
            self.assertNotIn("errors_report_path", event)
            self.assertNotIn("validation_summary", event)
        self.assertEqual(events[-1]["error"], "MinerU failed")

    def test_lite_dispatch_rejects_multiple_inputs_before_running_engine(self):
        """The lite runtime contract should reject batch tasks explicitly."""
        with self.assertRaisesRegex(ValueError, "exactly one"):
            run_engine_task(
                "lite",
                "pdf",
                ["one.pdf", "two.pdf"],
                {"lite": {"output_dir": "output-lite"}},
                lambda event: None,
            )

    def test_input_failure_keeps_project_visible_and_persists_error_log(self):
        """Acquisition failure should retain its directory for events and logs."""
        events: list[dict[str, object]] = []
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output_root = root / "output-lite"
            missing_pdf = root / "missing.pdf"
            result = run_engine_task(
                "lite",
                "pdf",
                [str(missing_pdf)],
                {"lite": {"output_dir": str(output_root)}},
                events.append,
            )

            failure = result["failed_projects"][0]
            project_dir = Path(failure["project_dir"])
            log_path = Path(failure["log_path"])
            self.assertTrue(project_dir.is_dir())
            self.assertEqual(project_dir.parent, output_root)
            self.assertEqual(log_path, project_dir / "latextrans.log")
            self.assertIn("existing file", log_path.read_text(encoding="utf-8"))

        self.assertEqual(events[0]["type"], "project_start")
        self.assertEqual(events[-1]["type"], "project_error")
        self.assertEqual(events[-1]["project_dir"], failure["project_dir"])
        self.assertEqual(events[-1]["log_path"], failure["log_path"])


if __name__ == "__main__":
    unittest.main()
