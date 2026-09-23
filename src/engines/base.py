"""Shared types and configuration helpers for translation engines."""

from __future__ import annotations

import copy
from typing import Any, Literal, cast


EngineName = Literal["heavy", "lite"]
_ENGINE_NAMES: tuple[EngineName, ...] = ("heavy", "lite")
_HEAVY_RUNTIME_FIELDS = (
    "tex_sources_dir",
    "output_dir",
    "paper_list",
    "retranslate_with_terms",
    "validation",
)
_ENGINE_RUNTIME_FIELDS: dict[EngineName, tuple[str, ...]] = {
    "heavy": _HEAVY_RUNTIME_FIELDS,
    "lite": (
        "output_dir",
        "mineru_api_key_env",
        "cjk_mainfont_candidates",
        "mainfont",
        "geometry",
        "protected_token_retry_attempts",
        "translate_appendix",
    ),
}


def engine_runtime_fields(engine: str) -> tuple[str, ...]:
    """Return the configuration keys the selected engine may read at runtime."""
    return _ENGINE_RUNTIME_FIELDS[cast(EngineName, normalize_engine(engine))]


def normalize_engine(value: object, default: str = "heavy") -> str:
    """Return a supported lower-case engine name or raise a clear error."""
    candidate = default if value is None or (isinstance(value, str) and not value.strip()) else value
    normalized = candidate.strip().lower() if isinstance(candidate, str) else ""
    if normalized not in _ENGINE_NAMES:
        raise ValueError("Engine must be one of: heavy, lite.")
    return cast(str, normalized)


def engine_config(config: dict[str, Any], engine: str) -> dict[str, Any]:
    """Build an isolated runtime-facing config for the selected engine."""
    selected_engine = normalize_engine(engine)
    effective = copy.deepcopy(config)
    sections = {
        name: effective.pop(name, {})
        for name in _ENGINE_NAMES
    }
    for key in _HEAVY_RUNTIME_FIELDS:
        effective.pop(key, None)

    selected = sections[selected_engine]
    if not isinstance(selected, dict):
        raise ValueError(f"Configuration section [{selected_engine}] must be a table.")
    for key in engine_runtime_fields(selected_engine):
        if key in selected:
            effective[key] = copy.deepcopy(selected[key])
    effective["engine"] = selected_engine
    return effective
