"""TUI 专用配置文件的初始化、加载和保存。"""

from __future__ import annotations

import copy
import shutil
from pathlib import Path
from typing import Any

import toml

UI_CONFIG_PATH = Path("config") / "ui.toml"
_LEGACY_HEAVY_KEYS = (
    "paper_list",
    "tex_sources_dir",
    "output_dir",
    "retranslate_with_terms",
    "validation",
)
_HEAVY_DEFAULTS: dict[str, Any] = {
    "paper_list": [],
    "tex_sources_dir": "tex source",
    "output_dir": "outputs",
    "retranslate_with_terms": False,
    "validation": {
        "retry": {
            "max_attempts": 3,
            "generate_pdf_on_error": True,
            "fail_on_error": True,
        },
        "issues": {
            "command_mismatch": {"severity": "error", "retryable": True},
            "placeholder_mismatch": {"severity": "error", "retryable": True},
            "bracket_mismatch": {"severity": "error", "retryable": True},
        },
    },
}


def _merge_missing_values(target: dict[str, Any], defaults: dict[str, Any]) -> None:
    """Recursively add missing defaults while retaining every existing value."""
    for key, default in defaults.items():
        if key not in target:
            target[key] = copy.deepcopy(default)
        elif isinstance(target[key], dict) and isinstance(default, dict):
            _merge_missing_values(target[key], default)


def _uses_legacy_layout(config: dict[str, Any]) -> bool:
    """Return whether a configuration still lacks the complete engine layout."""
    has_engine_sections = (
        "engine" in config
        and isinstance(config.get("heavy"), dict)
        and isinstance(config.get("lite"), dict)
    )
    return not has_engine_sections or any(key in config for key in _LEGACY_HEAVY_KEYS)


def migrate_ui_config(config: dict[str, Any]) -> dict[str, Any]:
    """Migrate a legacy flat UI config without mutating or replacing user values."""
    migrated = copy.deepcopy(config)
    if not _uses_legacy_layout(migrated):
        return migrated

    heavy = migrated.get("heavy")
    if not isinstance(heavy, dict):
        heavy = {}
        migrated["heavy"] = heavy
    for key in _LEGACY_HEAVY_KEYS:
        if key in migrated:
            heavy.setdefault(key, migrated.pop(key))
    _merge_missing_values(heavy, _HEAVY_DEFAULTS)

    lite = migrated.get("lite")
    if not isinstance(lite, dict):
        lite = {}
        migrated["lite"] = lite
    lite.setdefault("output_dir", "output-lite")
    lite.setdefault("mineru_api_key_env", "MINERU_TOKEN")
    lite.setdefault("protected_token_retry_attempts", 2)
    migrated.setdefault("engine", "heavy")
    return migrated


def _migrate_ui_config_file(ui_path: Path) -> None:
    """Persist a UI config only when its on-disk layout is legacy."""
    config = toml.load(ui_path)
    if not _uses_legacy_layout(config):
        return
    ui_path.write_text(toml.dumps(migrate_ui_config(config)), encoding="utf-8")


def ensure_ui_config(project_root: Path) -> Path:
    """确保 UI 配置文件存在，并返回其路径。"""
    config_dir = project_root / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    ui_path = project_root / UI_CONFIG_PATH
    if ui_path.exists():
        _migrate_ui_config_file(ui_path)
        return ui_path

    default_path = config_dir / "default.toml"
    template_path = config_dir / "template.toml"
    source_path = default_path if default_path.exists() else template_path
    if not source_path.exists():
        raise FileNotFoundError("Missing config/default.toml and config/template.toml.")

    shutil.copyfile(source_path, ui_path)
    _migrate_ui_config_file(ui_path)
    return ui_path


def load_ui_config(project_root: Path) -> dict[str, Any]:
    """加载 UI 配置，必要时先从默认配置或模板初始化。"""
    return toml.load(ensure_ui_config(project_root))


def save_ui_config(project_root: Path, config: dict[str, Any]) -> Path:
    """将 UI 配置保存到 config/ui.toml，并返回保存路径。"""
    ui_path = project_root / UI_CONFIG_PATH
    ui_path.parent.mkdir(parents=True, exist_ok=True)
    ui_path.write_text(toml.dumps(config), encoding="utf-8")
    return ui_path
