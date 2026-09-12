"""Repair invalid LaTeX superscript chains found in lite-engine Markdown math."""

from __future__ import annotations

import re
from pathlib import Path

from src.engines.lite_markdown import math_span_ranges


# PDF extractors emit ``x^{\prime}^{(i)}`` for ``x'^{(i)}``. LaTeX rejects the
# chained superscript with "Double superscript", which aborts the PDF pipeline.
_DOUBLE_SUPERSCRIPT_RE = re.compile(r"\^\s*\{([^{}]*)\}\s*\^\s*\{([^{}]*)\}")
_SUPERSCRIPT_SEPARATOR = r"\,"
_MAX_MERGE_PASSES = 8


def normalize_double_superscripts(text: str) -> tuple[str, int]:
    """Return text with invalid superscript chains merged, and the fix count.

    Only math spans are rewritten, so prose, code fences, and code spans keep
    their original characters.
    """
    fixes = 0
    parts: list[str] = []
    cursor = 0
    for start, end in math_span_ranges(text):
        parts.append(text[cursor:start])
        span, span_fixes = _merge_superscript_chain(text[start:end])
        parts.append(span)
        fixes += span_fixes
        cursor = end
    parts.append(text[cursor:])
    return "".join(parts), fixes


def normalize_markdown_math_file(path: Path) -> int:
    """Rewrite one Markdown file in place when its math needs repair.

    Returns:
        The number of repaired superscript chains, or ``0`` when the file was
        already valid and therefore left untouched.
    """
    original = path.read_text(encoding="utf-8")
    normalized, fixes = normalize_double_superscripts(original)
    if fixes:
        path.write_text(normalized, encoding="utf-8")
    return fixes


def _merge_superscript_chain(span: str) -> tuple[str, int]:
    """Merge every chained superscript pair inside one math span."""
    fixes = 0
    for _ in range(_MAX_MERGE_PASSES):
        span, replaced = _DOUBLE_SUPERSCRIPT_RE.subn(_join_superscript_pair, span)
        if not replaced:
            break
        fixes += replaced
    return span, fixes


def _join_superscript_pair(match: re.Match[str]) -> str:
    """Render one chained superscript as a single group of both exponents."""
    first, second = match.group(1), match.group(2)
    return f"^{{{first}{_SUPERSCRIPT_SEPARATOR}{second}}}"
