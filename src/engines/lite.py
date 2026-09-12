"""Orchestrate the PDF-to-Markdown lite translation workflow."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Callable
from pathlib import Path
from typing import Any

from src.agents.tool_agents.markdown_terminology_agent import MarkdownTerminologyAgent
from src.agents.tool_agents.markdown_translator_agent import MarkdownTranslatorAgent
from src.engines.lite_inputs import (
    LiteInputSpec,
    LiteProjectPreparationError,
    PreparedLiteProject,
    parse_lite_input,
    prepare_lite_project,
)
from src.engines.lite_markdown import split_markdown
from src.engines.lite_fonts import (
    DEFAULT_CJK_FONT_CANDIDATES,
    parse_font_candidates,
    resolve_cjk_mainfont,
    resolve_mainfont,
)
from src.engines.lite_math import normalize_markdown_math_file
from src.engines.lite_mineru import MineruMarkdownExtractor
from src.engines.lite_pdf import PandocPdfGenerator, is_cjk_target_language


LogCallback = Callable[[dict[str, Any]], None]
TerminologyFactory = Callable[[dict[str, Any], Path, Path], Any]
TranslatorFactory = Callable[[dict[str, Any], Path, Path, object], Any]
InputParser = Callable[[str], LiteInputSpec]
ProjectPreparer = Callable[[LiteInputSpec, Path], PreparedLiteProject]


class LiteEngine:
    """Run one self-contained lite project through all translation stages."""

    def __init__(
        self,
        mineru: Any | None = None,
        terminology: TerminologyFactory | None = None,
        translator: TranslatorFactory | None = None,
        pdf_generator: Any | None = None,
        input_parser: InputParser | None = None,
        project_preparer: ProjectPreparer | None = None,
    ) -> None:
        """Configure production stages or injected deterministic test doubles."""
        self._mineru = mineru or MineruMarkdownExtractor()
        self._terminology_factory = terminology or MarkdownTerminologyAgent
        self._translator_factory = translator or MarkdownTranslatorAgent
        self._pdf_generator = pdf_generator
        self._input_parser = input_parser or parse_lite_input
        self._project_preparer = project_preparer or prepare_lite_project

    def run(
        self,
        input_item: str,
        config: dict[str, Any],
        output_root: Path,
        log_callback: LogCallback | None = None,
    ) -> dict[str, Any]:
        """Translate one PDF input and return paths to completed or partial artifacts."""
        result = self._initial_result(input_item)
        project_config = dict(config)

        try:
            spec = self._input_parser(input_item)
            prepared = self._project_preparer(spec, Path(output_root))
            result.update(
                {
                    "project_name": prepared.project_name,
                    "project_dir": str(prepared.project_dir),
                    "output_dir": str(prepared.project_dir),
                }
            )
            project_config["_project_log_callback"] = lambda payload: self._forward_log(
                payload,
                result,
                log_callback,
            )
            self._log("Lite input preparation completed.", "info", result, log_callback)

            source_markdown = Path(
                self._mineru.extract(
                    prepared.source_pdf,
                    prepared.project_dir,
                    project_config.get("mineru_api_key_env"),
                )
            )
            result["source_markdown_path"] = str(source_markdown)
            self._log("MinerU extraction completed.", "info", result, log_callback)
            self._repair_markdown_math(source_markdown, "source", result, log_callback)

            terminology_agent = self._terminology_factory(
                project_config,
                source_markdown,
                prepared.project_dir,
            )
            terminology_result = terminology_agent.execute()
            result["project_terms_path"] = terminology_result.get("project_terms_path")
            result["project_terms_decisions_path"] = terminology_result.get(
                "project_terms_decisions_path"
            )
            if not terminology_result.get("ok", False):
                raise RuntimeError(
                    str(terminology_result.get("error") or "Terminology generation failed.")
                )
            self._log("Markdown terminology generation completed.", "info", result, log_callback)

            source_text = source_markdown.read_text(encoding="utf-8")
            translator_agent = self._translator_factory(
                project_config,
                source_markdown,
                prepared.project_dir,
                split_markdown(source_text),
            )
            translated_markdown = Path(self._await(translator_agent.execute()))
            result["translated_markdown_path"] = str(translated_markdown)
            self._log("Markdown translation completed.", "info", result, log_callback)
            self._repair_markdown_math(
                translated_markdown, "translated", result, log_callback
            )

            target_language = str(project_config.get("target_language", "ch"))
            generator = self._pdf_generator_for(project_config, target_language, result, log_callback)
            try:
                pdf_path = Path(
                    generator.generate(
                        translated_markdown,
                        prepared.project_dir / "translated.pdf",
                        target_language,
                    )
                )
            except Exception as exc:
                # A PDF failure must not discard the finished Markdown artifacts;
                # it is reported as a project warning instead.
                result["pdf_error"] = str(exc)
                self._log(f"PDF generation failed: {exc}", "warning", result, log_callback)
            else:
                result["pdf_path"] = str(pdf_path)
                self._log("PDF generation completed.", "info", result, log_callback)
                self._record_pdf_quality_warning(generator, result, log_callback)
            result["ok"] = True
        except Exception as exc:
            if isinstance(exc, LiteProjectPreparationError):
                result.update(
                    {
                        "project_name": exc.project_name,
                        "project_dir": str(exc.project_dir),
                        "output_dir": str(exc.project_dir),
                    }
                )
            result["error"] = str(exc)
            self._log(f"Lite workflow failed: {exc}", "error", result, log_callback)

        return result

    @staticmethod
    def _initial_result(input_item: str) -> dict[str, Any]:
        """Create the stable lite result shape before any artifact exists."""
        return {
            "ok": False,
            "engine": "lite",
            "project_name": Path(input_item).stem or input_item,
            "project_dir": None,
            "output_dir": None,
            "source_markdown_path": None,
            "translated_markdown_path": None,
            "pdf_path": None,
            "project_terms_path": None,
            "project_terms_decisions_path": None,
            "pdf_error": None,
            "error": None,
        }

    def _repair_markdown_math(
        self,
        markdown_path: Path,
        label: str,
        result: dict[str, Any],
        log_callback: LogCallback | None,
    ) -> None:
        """Merge invalid superscript chains left by extraction or translation."""
        try:
            fixes = normalize_markdown_math_file(markdown_path)
        except OSError as exc:
            self._log(
                f"Markdown math normalization skipped for {label}: {exc}",
                "warning",
                result,
                log_callback,
            )
            return
        if fixes:
            self._log(
                f"Normalized {fixes} invalid superscript chain(s) in {label} Markdown.",
                "warning",
                result,
                log_callback,
            )

    def _pdf_generator_for(
        self,
        project_config: dict[str, Any],
        target_language: str,
        result: dict[str, Any],
        log_callback: LogCallback | None,
    ) -> Any:
        """Return the injected PDF generator or one built from the lite configuration."""
        if self._pdf_generator is not None:
            return self._pdf_generator
        geometry = str(project_config.get("geometry") or "").strip()
        return PandocPdfGenerator(
            cjk_mainfont=self._resolve_cjk_font(
                project_config, target_language, result, log_callback
            ),
            mainfont=self._resolve_mainfont(project_config, result, log_callback),
            geometry=geometry or None,
        )

    def _resolve_mainfont(
        self,
        project_config: dict[str, Any],
        result: dict[str, Any],
        log_callback: LogCallback | None,
    ) -> str | None:
        """Resolve the configured body font, which controls non-CJK glyph coverage."""
        configured = project_config.get("mainfont")
        if configured is None or not str(configured).strip():
            return None
        font = resolve_mainfont(configured)
        if font is None:
            self._log(
                f"Configured mainfont {configured!r} is not installed; keeping the Pandoc "
                "default font, which may drop symbols outside Latin.",
                "warning",
                result,
                log_callback,
            )
            return None
        self._log(f"Body font selected: {font}.", "info", result, log_callback)
        return font

    def _resolve_cjk_font(
        self,
        project_config: dict[str, Any],
        target_language: str,
        result: dict[str, Any],
        log_callback: LogCallback | None,
    ) -> str | None:
        """Resolve the first installed CJK font candidate in configured order."""
        if not is_cjk_target_language(target_language):
            return None
        configured_value = project_config.get("cjk_mainfont_candidates")
        if configured_value is None:
            # Configurations written before this setting existed carry no value; a
            # missing key means "use the shipped order", while an explicitly empty
            # string means "do not set a CJK font".
            configured_value = DEFAULT_CJK_FONT_CANDIDATES
        candidates = parse_font_candidates(configured_value)
        if not candidates:
            return None
        configured = ", ".join(candidates)
        font = resolve_cjk_mainfont(candidates)
        if font is None:
            self._log(
                "No configured CJK font candidate is installed; the PDF may drop CJK glyphs. "
                f"Candidates: {configured}",
                "warning",
                result,
                log_callback,
            )
        elif font.casefold() != candidates[0].casefold():
            self._log(
                f"CJK font fallback selected: {font} (candidate order: {configured}).",
                "info",
                result,
                log_callback,
            )
        else:
            self._log(f"CJK font selected: {font}.", "info", result, log_callback)
        return font

    def _record_pdf_quality_warning(
        self,
        generator: Any,
        result: dict[str, Any],
        log_callback: LogCallback | None,
    ) -> None:
        """Record dropped-glyph warnings from a PDF run that still succeeded."""
        warning = str(getattr(generator, "last_pdf_warning", "") or "").strip()
        if not warning:
            return
        result["pdf_error"] = warning
        self._log(f"PDF generation warning: {warning}", "warning", result, log_callback)

    @staticmethod
    def _await(value: Any) -> Any:
        """Resolve an asynchronous stage result while permitting synchronous fakes."""
        if inspect.isawaitable(value):
            return asyncio.run(value)
        return value

    @staticmethod
    def _forward_log(
        payload: dict[str, Any],
        result: dict[str, Any],
        log_callback: LogCallback | None,
    ) -> None:
        """Attach lite artifact identity to an agent log payload."""
        if log_callback is None:
            return
        event = LiteEngine._artifact_fields(result)
        event.update(payload)
        log_callback(event)

    @staticmethod
    def _log(
        message: str,
        level: str,
        result: dict[str, Any],
        log_callback: LogCallback | None,
    ) -> None:
        """Emit one orchestration milestone through the project log callback."""
        if log_callback is None:
            return
        line = f"[LiteEngine] [{level.upper()}] {message}"
        payload = LiteEngine._artifact_fields(result)
        payload.update(
            {
                "agent_name": "LiteEngine",
                "level": level,
                "message": message,
                "line": line,
            }
        )
        log_callback(payload)

    @staticmethod
    def _artifact_fields(result: dict[str, Any]) -> dict[str, Any]:
        """Return the engine and artifact fields shared by lite logs and events."""
        return {
            key: result.get(key)
            for key in (
                "engine",
                "project_name",
                "project_dir",
                "output_dir",
                "source_markdown_path",
                "translated_markdown_path",
                "pdf_path",
                "pdf_error",
                "project_terms_path",
                "project_terms_decisions_path",
            )
        }
