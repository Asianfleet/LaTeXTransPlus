"""End-to-end tests for lite orchestration and engine-aware runtime dispatch."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.engines.lite import LiteEngine
from src.engines.lite_fonts import DEFAULT_CJK_FONT_CANDIDATES, parse_font_candidates
from src.runtime import run_engine_task


class _FakeMineru:
    """Write deterministic Markdown without invoking the MinerU SDK."""

    def __init__(self) -> None:
        """Record the token environment variable name supplied by orchestration."""
        self.api_key_env: str | None = None

    def extract(
        self,
        source_pdf: Path,
        output_dir: Path,
        api_key_env: str | None = None,
    ) -> Path:
        """Record a valid source Markdown artifact in the project directory."""
        if source_pdf != output_dir / "source.pdf":
            raise AssertionError("MinerU must receive the project-local source PDF")
        self.api_key_env = api_key_env
        markdown_path = output_dir / "source.md"
        markdown_path.write_text("# Paper\n\n## Method\nSource body.\n", encoding="utf-8")
        return markdown_path


class _AppendixMineru:
    """Write source Markdown containing a body section and an appendix."""

    def extract(
        self,
        source_pdf: Path,
        output_dir: Path,
        api_key_env: str | None = None,
    ) -> Path:
        """Create deterministic Markdown with an appendix heading."""
        markdown_path = output_dir / "source.md"
        markdown_path.write_text(
            "# Paper\n\n## Method\nSource body.\n\n## Appendix A\nRaw appendix.\n",
            encoding="utf-8",
        )
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


class _AppendixTranslator(_FakeTranslator):
    """Write a deterministic artifact after capturing appendix-aware blocks."""

    async def execute(self) -> Path:
        """Write a placeholder translated Markdown artifact for orchestration tests."""
        translated_path = self.output_dir / "translated.md"
        translated_path.write_text("# 论文\n", encoding="utf-8")
        return translated_path


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


class _FailingPdfGenerator:
    """Raise the Pandoc failure reported when XeLaTeX rejects the Markdown."""

    def generate(
        self,
        markdown_path: Path,
        pdf_path: Path,
        target_language: str,
    ) -> Path:
        """Fail with the diagnostic message produced by the Pandoc adapter."""
        raise RuntimeError(
            "Pandoc PDF generation failed with exit code 43. PDF engine output:\n"
            "! Double superscript."
        )


class _WarnedPdfGenerator(_FakePdfGenerator):
    """Succeed at PDF generation while reporting dropped glyphs."""

    last_pdf_warning = ""

    def generate(
        self,
        markdown_path: Path,
        pdf_path: Path,
        target_language: str,
    ) -> Path:
        """Write a placeholder PDF and expose the quality warning of a real run."""
        self.last_pdf_warning = (
            "PDF engine reported 10818 missing character warning(s); the PDF may omit glyphs."
        )
        return super().generate(markdown_path, pdf_path, target_language)


class _BadMathMineru:
    """Write MinerU-style Markdown whose math has a chained superscript."""

    def extract(
        self,
        source_pdf: Path,
        output_dir: Path,
        api_key_env: str | None = None,
    ) -> Path:
        """Record Markdown containing the invalid XeLaTeX superscript chain."""
        markdown_path = output_dir / "source.md"
        markdown_path.write_text(
            "# Paper\n\n## Method\n方向 $x ^ { \\prime } ^ { \\left( i \\right) }$。\n",
            encoding="utf-8",
        )
        return markdown_path


class _BadMathTranslator:
    """Write translated Markdown that repeats the extracted superscript defect."""

    def __call__(
        self,
        config: dict[str, object],
        source_markdown: Path,
        output_dir: Path,
        blocks: object,
    ) -> "_BadMathTranslator":
        """Capture the paths supplied by the lite engine."""
        self.source_markdown = source_markdown
        self.output_dir = output_dir
        self.blocks = tuple(blocks)
        return self

    async def execute(self) -> Path:
        """Write a translated artifact whose math chains two superscripts."""
        translated_path = self.output_dir / "translated.md"
        translated_path.write_text(
            "# 论文\n\n## 方法\n方向 $y ^ { \\prime } ^ { \\left( j \\right) }$。\n",
            encoding="utf-8",
        )
        return translated_path


class LiteEngineTests(unittest.TestCase):
    """Verify the complete lite pipeline without network or external tools."""

    def _run_engine(
        self,
        root: Path,
        translator: object | None = None,
        config: dict[str, object] | None = None,
        mineru: object | None = None,
        pdf_generator: object | None = None,
    ):
        """Run a lite engine with deterministic injected stage dependencies."""
        source_pdf = root / "paper.pdf"
        source_pdf.write_bytes(b"%PDF-source")
        logs: list[dict[str, object]] = []
        engine = LiteEngine(
            mineru=mineru or _FakeMineru(),
            terminology=_FakeTerminology(),
            translator=translator or _FakeTranslator(),
            pdf_generator=pdf_generator or _FakePdfGenerator(),
        )
        result = engine.run(
            str(source_pdf),
            config or {"source_language": "en", "target_language": "ch"},
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
            self.assertRegex(project_dir.name, r"^paper_\d{6}(?:_\d+)?$")
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

    def test_run_forwards_the_configured_mineru_api_key_env(self):
        """Forward ``mineru_api_key_env`` so the adapter resolves the configured token."""
        with tempfile.TemporaryDirectory() as temp_dir:
            mineru = _FakeMineru()
            result, _logs = self._run_engine(
                Path(temp_dir),
                config={
                    "source_language": "en",
                    "target_language": "ch",
                    "mineru_api_key_env": "CUSTOM_MINERU_TOKEN",
                },
                mineru=mineru,
            )

            self.assertTrue(result["ok"])
            self.assertEqual(mineru.api_key_env, "CUSTOM_MINERU_TOKEN")

    def test_run_marks_appendix_blocks_and_logs_when_disabled(self):
        """Lite orchestration should pass preserved appendix blocks to translation."""
        with tempfile.TemporaryDirectory() as temp_dir:
            translator = _AppendixTranslator()
            result, logs = self._run_engine(
                Path(temp_dir),
                translator=translator,
                mineru=_AppendixMineru(),
                config={
                    "source_language": "en",
                    "target_language": "ch",
                    "translate_appendix": False,
                },
            )

        self.assertTrue(result["ok"])
        self.assertEqual(
            [block.translatable for block in translator.blocks], [True, True, False]
        )
        self.assertIn("Raw appendix.", translator.blocks[-1].text)
        self.assertTrue(
            any(
                "appendix detected" in str(event["message"]).casefold()
                for event in logs
            )
        )

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

    def test_run_repairs_extracted_double_superscripts_in_both_artifacts(self):
        """Extracted superscript chains must be merged before Pandoc sees them."""
        with tempfile.TemporaryDirectory() as temp_dir:
            result, logs = self._run_engine(
                Path(temp_dir),
                translator=_BadMathTranslator(),
                mineru=_BadMathMineru(),
            )

            self.assertTrue(result["ok"])
            for key in ("source_markdown_path", "translated_markdown_path"):
                text = Path(result[key]).read_text(encoding="utf-8")
                self.assertNotIn(r"^ { \prime } ^", text)
                self.assertIn(r"\prime \,", text)

        normalized_logs = [
            str(event["message"])
            for event in logs
            if "Normalized" in str(event["message"])
        ]
        self.assertEqual(len(normalized_logs), 2)
        self.assertTrue(any("source" in message for message in normalized_logs))
        self.assertTrue(any("translated" in message for message in normalized_logs))

    def test_pdf_failure_keeps_the_markdown_result_and_records_a_warning(self):
        """A failed PDF stage must not discard the finished Markdown translation."""
        with tempfile.TemporaryDirectory() as temp_dir:
            result, logs = self._run_engine(
                Path(temp_dir), pdf_generator=_FailingPdfGenerator()
            )

            self.assertTrue(result["ok"])
            self.assertIsNone(result["error"])
            self.assertIsNone(result["pdf_path"])
            self.assertIn("exit code 43", result["pdf_error"])
            self.assertTrue(Path(result["translated_markdown_path"]).is_file())
            self.assertTrue(Path(result["source_markdown_path"]).is_file())

        self.assertEqual(logs[-1]["level"], "warning")
        self.assertIn("[WARNING]", str(logs[-1]["line"]))
        self.assertIn("! Double superscript.", str(logs[-1]["line"]))

    def test_pdf_dropped_glyphs_become_a_warning_on_a_successful_project(self):
        """A successful PDF run that dropped glyphs must report a project warning."""
        with tempfile.TemporaryDirectory() as temp_dir:
            result, logs = self._run_engine(
                Path(temp_dir), pdf_generator=_WarnedPdfGenerator()
            )

            self.assertTrue(result["ok"])
            self.assertIsNotNone(result["pdf_path"])
            self.assertIn("missing character warning", result["pdf_error"])

        self.assertEqual(logs[-1]["level"], "warning")
        self.assertIn("PDF generation warning", str(logs[-1]["message"]))

    def _run_engine_with_default_pdf_stage(self, root: Path, config: dict[str, object]):
        """Run a lite engine that builds its own Pandoc PDF generator."""
        source_pdf = root / "paper.pdf"
        source_pdf.write_bytes(b"%PDF-source")
        logs: list[dict[str, object]] = []
        engine = LiteEngine(
            mineru=_FakeMineru(),
            terminology=_FakeTerminology(),
            translator=_FakeTranslator(),
        )
        result = engine.run(str(source_pdf), config, root / "output-lite", logs.append)
        return result, logs

    def test_run_builds_the_pdf_generator_from_lite_font_and_geometry_settings(self):
        """Resolved body font, CJK font, and geometry must reach the generator."""
        captured: list[dict[str, object]] = []

        class _SpyPdfGenerator:
            """Capture constructor settings and write a placeholder PDF."""

            def __init__(self, cjk_mainfont=None, mainfont=None, geometry=None) -> None:
                captured.append(
                    {
                        "cjk_mainfont": cjk_mainfont,
                        "mainfont": mainfont,
                        "geometry": geometry,
                    }
                )

            def generate(self, markdown_path, pdf_path, target_language):
                pdf_path.write_bytes(b"%PDF-spy")
                return pdf_path

        with tempfile.TemporaryDirectory() as temp_dir:
            with patch("src.engines.lite.PandocPdfGenerator", _SpyPdfGenerator):
                with patch(
                    "src.engines.lite.resolve_cjk_mainfont", return_value="FandolSong"
                ):
                    with patch(
                        "src.engines.lite.resolve_mainfont", return_value="Times New Roman"
                    ):
                        result, logs = self._run_engine_with_default_pdf_stage(
                            Path(temp_dir),
                            {
                                "source_language": "en",
                                "target_language": "ch",
                                "cjk_mainfont_candidates": "SimSun, FandolSong",
                                "mainfont": "Times New Roman",
                                "geometry": "margin=2cm",
                            },
                        )

            self.assertTrue(result["ok"])

        self.assertEqual(
            captured,
            [
                {
                    "cjk_mainfont": "FandolSong",
                    "mainfont": "Times New Roman",
                    "geometry": "margin=2cm",
                }
            ],
        )
        self.assertTrue(
            any("CJK font fallback selected: FandolSong" in str(event["message"]) for event in logs)
        )
        self.assertTrue(
            any("Body font selected: Times New Roman" in str(event["message"]) for event in logs)
        )

    def test_run_warns_and_keeps_the_default_when_mainfont_is_not_installed(self):
        """An uninstalled body font must not be passed on to Pandoc."""
        captured: list[dict[str, object]] = []

        class _SpyPdfGenerator:
            """Capture the mainfont passed by the engine."""

            def __init__(self, cjk_mainfont=None, mainfont=None, geometry=None) -> None:
                captured.append(mainfont)

            def generate(self, markdown_path, pdf_path, target_language):
                pdf_path.write_bytes(b"%PDF-spy")
                return pdf_path

        with tempfile.TemporaryDirectory() as temp_dir:
            with patch("src.engines.lite.PandocPdfGenerator", _SpyPdfGenerator):
                with patch("src.engines.lite.resolve_mainfont", return_value=None):
                    _result, logs = self._run_engine_with_default_pdf_stage(
                        Path(temp_dir),
                        {
                            "source_language": "en",
                            "target_language": "ch",
                            "mainfont": "Missing Font",
                        },
                    )

        self.assertEqual(captured, [None])
        self.assertTrue(
            any(
                "is not installed" in str(event["message"])
                for event in logs
                if event.get("level") == "warning"
            )
        )

    def test_run_warns_when_no_configured_cjk_font_is_installed(self):
        """An unresolvable candidate list must be reported instead of failing silently."""
        class _SpyPdfGenerator:
            """Write a placeholder PDF for the configured settings."""

            def __init__(self, cjk_mainfont=None, mainfont=None, geometry=None) -> None:
                self.cjk_mainfont = cjk_mainfont

            def generate(self, markdown_path, pdf_path, target_language):
                pdf_path.write_bytes(b"%PDF-spy")
                return pdf_path

        with tempfile.TemporaryDirectory() as temp_dir:
            with patch("src.engines.lite.PandocPdfGenerator", _SpyPdfGenerator):
                with patch("src.engines.lite.resolve_cjk_mainfont", return_value=None):
                    _result, logs = self._run_engine_with_default_pdf_stage(
                        Path(temp_dir),
                        {
                            "source_language": "en",
                            "target_language": "ch",
                            "cjk_mainfont_candidates": "Missing Font",
                        },
                    )

        warnings = [
            str(event["message"])
            for event in logs
            if event.get("level") == "warning"
        ]
        self.assertTrue(
            any("No configured CJK font candidate is installed" in message for message in warnings)
        )

    def test_run_uses_shipped_font_candidates_when_the_config_omits_them(self):
        """Configurations written before this setting must keep working."""
        class _SpyPdfGenerator:
            """Write a placeholder PDF for the configured settings."""

            def __init__(self, cjk_mainfont=None, mainfont=None, geometry=None) -> None:
                self.cjk_mainfont = cjk_mainfont

            def generate(self, markdown_path, pdf_path, target_language):
                pdf_path.write_bytes(b"%PDF-spy")
                return pdf_path

        with tempfile.TemporaryDirectory() as temp_dir:
            with patch("src.engines.lite.PandocPdfGenerator", _SpyPdfGenerator):
                with patch(
                    "src.engines.lite.resolve_cjk_mainfont", return_value="SimSun"
                ) as resolve:
                    _result, _logs = self._run_engine_with_default_pdf_stage(
                        Path(temp_dir),
                        {"source_language": "en", "target_language": "ch"},
                    )

        resolve.assert_called_once_with(parse_font_candidates(DEFAULT_CJK_FONT_CANDIDATES))

    def test_run_skips_cjk_font_resolution_for_non_cjk_targets(self):
        """A Latin target must not resolve or warn about CJK fonts."""
        captured: list[dict[str, object]] = []

        class _SpyPdfGenerator:
            """Capture the CJK font setting passed by the engine."""

            def __init__(self, cjk_mainfont=None, mainfont=None, geometry=None) -> None:
                captured.append({"cjk_mainfont": cjk_mainfont})

            def generate(self, markdown_path, pdf_path, target_language):
                pdf_path.write_bytes(b"%PDF-spy")
                return pdf_path

        with tempfile.TemporaryDirectory() as temp_dir:
            with patch("src.engines.lite.PandocPdfGenerator", _SpyPdfGenerator):
                with patch("src.engines.lite.resolve_cjk_mainfont") as resolve:
                    _result, logs = self._run_engine_with_default_pdf_stage(
                        Path(temp_dir),
                        {
                            "source_language": "en",
                            "target_language": "fr",
                            "cjk_mainfont_candidates": "SimSun",
                        },
                    )

        resolve.assert_not_called()
        self.assertEqual(captured, [{"cjk_mainfont": None}])
        self.assertFalse(any("CJK font" in str(event.get("message")) for event in logs))


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

    def test_lite_pdf_warning_still_emits_project_complete_with_pdf_error(self):
        """A PDF warning must keep the finished Markdown project out of failures."""
        events: list[dict[str, object]] = []

        class _WarnedLiteEngine:
            """Return a successful lite result carrying a PDF warning."""

            def run(self, input_item, config, output_root, log_callback=None):
                """Publish prepared artifacts plus a failed PDF stage."""
                project_dir = Path(output_root) / "paper_20260910T120000"
                return {
                    "ok": True,
                    "engine": "lite",
                    "project_name": project_dir.name,
                    "project_dir": str(project_dir),
                    "output_dir": str(project_dir),
                    "source_markdown_path": str(project_dir / "source.md"),
                    "translated_markdown_path": str(project_dir / "translated.md"),
                    "pdf_path": None,
                    "pdf_error": "Pandoc PDF generation failed with exit code 43.",
                    "project_terms_path": None,
                    "project_terms_decisions_path": None,
                    "error": None,
                }

        with tempfile.TemporaryDirectory() as temp_dir:
            config = {"lite": {"output_dir": str(Path(temp_dir) / "output-lite")}}
            with patch("src.runtime.LiteEngine", _WarnedLiteEngine):
                result = run_engine_task("lite", "pdf", ["paper.pdf"], config, events.append)

        self.assertEqual([event["type"] for event in events], ["project_start", "project_complete"])
        self.assertIn("exit code 43", str(events[-1]["pdf_error"]))
        self.assertEqual(len(result["completed_projects"]), 1)
        self.assertEqual(result["failed_projects"], [])


if __name__ == "__main__":
    unittest.main()
