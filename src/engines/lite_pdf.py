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


class PandocPdfGenerator:
    """Generate a validated PDF from Markdown through Pandoc and XeLaTeX."""

    def __init__(
        self,
        runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
        cjk_mainfont: str | None = None,
        geometry: str | None = None,
    ) -> None:
        """Configure injectable execution and optional portable Pandoc variables."""
        self._runner = runner or subprocess.run
        self._cjk_mainfont = cjk_mainfont
        self._geometry = geometry

    def generate(
        self, markdown_path: Path, pdf_path: Path, target_language: str
    ) -> Path:
        """Render Markdown to a nonempty PDF using explicit language metadata."""
        language_tag = _pandoc_language_tag(target_language)
        pdf_path.parent.mkdir(parents=True, exist_ok=True)
        command = [
            "pandoc",
            str(markdown_path),
            "-o",
            str(pdf_path),
            "--pdf-engine=xelatex",
            f"--metadata=lang:{language_tag}",
        ]
        if self._geometry:
            command.extend(["-V", f"geometry:{self._geometry}"])
        if self._cjk_mainfont and language_tag.startswith(_CJK_LANGUAGE_PREFIXES):
            command.extend(["-V", f"CJKmainfont:{self._cjk_mainfont}"])

        self._runner(command, check=True, capture_output=True, text=True)
        if not pdf_path.is_file() or pdf_path.stat().st_size == 0:
            raise ValueError(f"Pandoc PDF output is missing or empty: {pdf_path}")
        return pdf_path


def _pandoc_language_tag(target_language: str) -> str:
    """Map supported project language aliases to an explicit Pandoc language tag."""
    normalized = target_language.strip().lower().replace("_", "-")
    if not normalized:
        raise ValueError("Target language must not be empty.")
    return _LANGUAGE_TAGS.get(normalized, normalized)
