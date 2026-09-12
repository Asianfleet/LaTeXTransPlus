"""Pandoc and XeLaTeX boundary adapter for lite-engine PDF generation."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path


_LANGUAGE_TAGS = {
    "ch": "zh-CN",
    "zh": "zh-CN",
    "zh-cn": "zh-CN",
    "en": "en-US",
    "ja": "ja-JP",
    "ko": "ko-KR",
}
_CJK_LANGUAGE_PREFIXES = ("zh", "ja", "ko")
_STDERR_EXCERPT_LINES = 20
_STDERR_EXCERPT_CHARS = 2000
_MISSING_CHARACTER_MARKER = "Missing character"


class PandocPdfError(RuntimeError):
    """Report a failed Pandoc run together with the captured tool output."""

    def __init__(self, message: str, returncode: int | None, stderr: str) -> None:
        """Store the exit status and full stderr beside the display message."""
        super().__init__(message)
        self.returncode = returncode
        self.stderr = stderr


class PandocPdfGenerator:
    """Generate a validated PDF from Markdown through Pandoc and XeLaTeX.

    The last run's quality warning is exposed through ``last_pdf_warning`` so a
    PDF that Pandoc produced with dropped glyphs is not reported as clean.
    """

    def __init__(
        self,
        runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
        cjk_mainfont: str | None = None,
        mainfont: str | None = None,
        geometry: str | None = None,
    ) -> None:
        """Configure injectable execution and optional portable Pandoc variables."""
        self._runner = runner or subprocess.run
        self._cjk_mainfont = cjk_mainfont
        self._mainfont = mainfont
        self._geometry = geometry
        self.last_pdf_warning = ""

    def generate(
        self, markdown_path: Path, pdf_path: Path, target_language: str
    ) -> Path:
        """Render Markdown to a nonempty PDF using explicit language metadata."""
        language_tag = _pandoc_language_tag(target_language)
        pdf_path.parent.mkdir(parents=True, exist_ok=True)
        # Pandoc resolves relative image paths against the resource path (the
        # working directory by default), so a document in an output directory
        # would lose every extracted figure. Point Pandoc at the document's own
        # directory instead.
        resource_path = Path(markdown_path).resolve().parent
        command = [
            "pandoc",
            str(markdown_path),
            "-o",
            str(pdf_path),
            "--pdf-engine=xelatex",
            f"--metadata=lang:{language_tag}",
            f"--resource-path={resource_path}",
        ]
        if self._geometry:
            command.extend(["-V", f"geometry:{self._geometry}"])
        if self._mainfont:
            command.extend(["-V", f"mainfont:{self._mainfont}"])
        if self._cjk_mainfont and language_tag.startswith(_CJK_LANGUAGE_PREFIXES):
            command.extend(["-V", f"CJKmainfont:{self._cjk_mainfont}"])

        try:
            completed = self._runner(
                command,
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        except subprocess.CalledProcessError as exc:
            raise PandocPdfError(
                _pandoc_failure_message(exc),
                returncode=exc.returncode,
                stderr=_process_output(exc.stderr),
            ) from exc
        if not pdf_path.is_file() or pdf_path.stat().st_size == 0:
            raise ValueError(f"Pandoc PDF output is missing or empty: {pdf_path}")
        self.last_pdf_warning = _missing_character_summary(
            _process_output(getattr(completed, "stderr", ""))
        )
        return pdf_path


def is_cjk_target_language(target_language: str) -> bool:
    """Return whether a target language alias needs the Pandoc CJK font variables."""
    return _pandoc_language_tag(target_language).startswith(_CJK_LANGUAGE_PREFIXES)


def _missing_character_summary(stderr: str) -> str:
    """Summarize dropped-glyph warnings emitted by a successful Pandoc run."""
    warnings = [
        line.strip()
        for line in stderr.splitlines()
        if _MISSING_CHARACTER_MARKER in line
    ]
    if not warnings:
        return ""
    return (
        f"PDF engine reported {len(warnings)} missing character warning(s); "
        f"the PDF may omit glyphs. First warning: {warnings[0]}"
    )


def _pandoc_failure_message(exc: subprocess.CalledProcessError) -> str:
    """Build a diagnostic message carrying the exit status and engine output."""
    stderr = _process_output(exc.stderr).strip()
    if not stderr:
        return f"Pandoc PDF generation failed with exit code {exc.returncode}."
    return (
        f"Pandoc PDF generation failed with exit code {exc.returncode}. "
        f"PDF engine output:\n{_excerpt(stderr)}"
    )


def _process_output(value: object) -> str:
    """Normalize captured process output to text for diagnostics."""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value or "")


def _excerpt(
    text: str,
    max_lines: int = _STDERR_EXCERPT_LINES,
    max_chars: int = _STDERR_EXCERPT_CHARS,
) -> str:
    """Keep the tail of a long engine log, which holds the actual LaTeX error."""
    lines = text.splitlines()
    if len(lines) > max_lines:
        lines = ["...(earlier output truncated)...", *lines[-max_lines:]]
    excerpt = "\n".join(lines)
    if len(excerpt) > max_chars:
        excerpt = "..." + excerpt[-max_chars:]
    return excerpt


def _pandoc_language_tag(target_language: str) -> str:
    """Map supported project language aliases to an explicit Pandoc language tag."""
    normalized = target_language.strip().lower().replace("_", "-")
    if not normalized:
        raise ValueError("Target language must not be empty.")
    return _LANGUAGE_TAGS.get(normalized, normalized)
