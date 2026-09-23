"""Detect installed font families and resolve the lite engine's CJK main font.

Pandoc's default LaTeX template only loads ``xeCJK`` when ``CJKmainfont`` is set,
so a CJK target needs one resolvable family name. Font names are machine
specific (``Noto Sans SC`` exists here while ``Noto Sans CJK SC`` does not), so
the engine consults fontconfig -- the same font database XeTeX uses to resolve
``\\setCJKmainfont`` -- instead of trusting the configured names blindly.
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable, Sequence


FC_LIST_COMMAND = "fc-list"
_DEFAULT_CANDIDATES = (
    "SimSun",
    "Noto Serif SC",
    "FandolSong",
    "Microsoft YaHei",
)
DEFAULT_CJK_FONT_CANDIDATES = ", ".join(_DEFAULT_CANDIDATES)


def parse_font_candidates(value: object) -> list[str]:
    """Parse a comma-separated font setting into ordered unique family names."""
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        items = [str(item) for item in value]
    else:
        items = str(value).split(",")

    candidates: list[str] = []
    seen: set[str] = set()
    for item in items:
        name = _normalize_family(item)
        key = name.casefold()
        if name and key not in seen:
            seen.add(key)
            candidates.append(name)
    return candidates


def list_available_font_families(
    language: str | None = "zh",
    runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
) -> list[str]:
    """Return font families reported by fontconfig, sorted.

    Args:
        language: Optional language filter such as ``"zh"``; ``None`` lists
            every family so a Latin or Greek body font can be picked as well.
        runner: Injectable process runner for tests.

    Localized aliases (``SimSun,宋体``) are reported as separate families because
    XeTeX resolves either spelling. Machines without ``fc-list`` return an empty
    list so callers can fall back to a best-effort font name.
    """
    executable = _fc_list_executable()
    if executable is None:
        return []

    execute = runner or subprocess.run
    try:
        completed = execute(
            [executable, *_font_query(language)],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except OSError:
        return []
    if completed.returncode != 0:
        return []
    return _parse_family_output(_process_output(completed.stdout))


def resolve_mainfont(value: object) -> str | None:
    """Resolve a configured body font against every family fontconfig knows.

    Returns the canonical spelling this machine reports, the configured name
    unchanged when no font database is available, and ``None`` when the name is
    blank or not installed.
    """
    name = _normalize_family(value) if value is not None else ""
    if not name:
        return None
    families = list_available_font_families(language=None)
    if not families:
        return name
    return _match_family(name, families)


def resolve_cjk_mainfont(
    candidates: Sequence[str],
    available: Sequence[str] | None = None,
) -> str | None:
    """Return the first CJK candidate this machine can resolve, or ``None``.

    When no font listing is available at all, the first candidate is returned
    unchanged: a machine without fontconfig is better served by a best-effort
    name than by silently dropping every CJK glyph.
    """
    if not candidates:
        return None

    families = list_available_font_families("zh") if available is None else list(available)
    if not families:
        return candidates[0]

    for candidate in candidates:
        match = _match_family(candidate, families)
        if match is not None:
            return match
    return None


def _match_family(name: str, families: Sequence[str]) -> str | None:
    """Return the canonical family spelling when ``name`` is installed."""
    resolvable = {_normalize_family(family).casefold(): family for family in families}
    return resolvable.get(_normalize_family(name).casefold())


def _font_query(language: str | None) -> tuple[str, ...]:
    """Build the fc-list pattern and format arguments for one listing."""
    pattern = ":" if language is None else f":lang={language}"
    return (pattern, "family")


def _fc_list_executable() -> str | None:
    """Locate the fontconfig listing tool shipped with TeX Live or MiKTeX."""
    return shutil.which(FC_LIST_COMMAND)


def _parse_family_output(text: str) -> list[str]:
    """Split fontconfig family output into unique, sorted family names."""
    families: dict[str, str] = {}
    for line in text.splitlines():
        for entry in line.split(","):
            name = _normalize_family(entry)
            if name:
                families.setdefault(name, name)
    return sorted(families.values(), key=str.casefold)


def _normalize_family(value: object) -> str:
    """Collapse whitespace in one font family name for matching and display."""
    return " ".join(str(value).split())


def _process_output(value: object) -> str:
    """Normalize captured process output to text for parsing."""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value or "")
