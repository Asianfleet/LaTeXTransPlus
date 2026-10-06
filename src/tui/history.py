"""History loading and metadata persistence for the Textual terminal UI."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from src.engines.base import normalize_engine
from src.project_metadata import read_project_title
from src.tui.state import ProjectStatus, ProjectViewState, TaskViewState

TUI_PROJECT_METADATA_FILENAME = ".latextrans-tui.json"


def load_output_history(output_root: Path, engine: str = "heavy") -> list[TaskViewState]:
    """Load only project history rows belonging to the selected engine."""
    selected_engine = normalize_engine(engine)
    if not output_root.is_dir():
        return []

    tasks: list[TaskViewState] = []
    for project_output_dir in sorted(path for path in output_root.iterdir() if path.is_dir()):
        metadata = read_project_metadata(project_output_dir)
        project_engine = _infer_project_engine(project_output_dir, metadata)
        if project_engine != selected_engine:
            continue
        project_name = str(metadata.get("project_name") or _legacy_project_name(project_output_dir))
        task_id = str(metadata.get("task_id") or "")
        input_type = str(metadata.get("input_type") or "history")
        input_item = str(metadata.get("input_item") or project_name)
        status = infer_project_status(project_output_dir, engine=project_engine)
        pdf_path = _find_pdf(project_output_dir, project_engine)
        project = ProjectViewState(
            project_name=project_name,
            title=str(metadata.get("title") or read_project_title(
                project_output_dir, project_engine, metadata.get("source_markdown_path")
            )),
            translation_model=str(metadata.get("translation_model") or ""),
            engine=project_engine,
            status=status,
            output_dir=str(project_output_dir),
            project_dir=str(_infer_project_dir(project_output_dir, metadata, project_name)),
            pdf_path=str(pdf_path) if pdf_path else None,
            source_markdown_path=_metadata_or_artifact_path(
                metadata,
                "source_markdown_path",
                project_output_dir / "source.md",
            ),
            translated_markdown_path=_metadata_or_artifact_path(
                metadata,
                "translated_markdown_path",
                project_output_dir / "translated.md",
            ),
            errors_report_path=str(project_output_dir / "errors_report.json")
            if project_engine == "heavy" and (project_output_dir / "errors_report.json").is_file()
            else None,
            project_terms_path=str(project_output_dir / "project_terms.csv")
            if (project_output_dir / "project_terms.csv").is_file()
            else None,
            project_terms_decisions_path=str(project_output_dir / "project_terms_decisions.json")
            if (project_output_dir / "project_terms_decisions.json").is_file()
            else None,
            log_path=str(project_output_dir / "latextrans.log")
            if (project_output_dir / "latextrans.log").is_file()
            else None,
        )
        task = TaskViewState(
            input_type=input_type,
            inputs=[input_item],
            engine=project_engine,
            task_id=task_id,
        )
        task.projects.append(project)
        task.completed = 1 if status == ProjectStatus.COMPLETED else 0
        task.failed = 1 if status == ProjectStatus.FAILED else 0
        task.total = 1
        tasks.append(task)
    return tasks


def read_project_metadata(project_dir: Path) -> dict[str, Any]:
    """Read TUI metadata from an output project directory."""
    metadata_path = project_dir / TUI_PROJECT_METADATA_FILENAME
    if not metadata_path.is_file():
        return {}
    try:
        data = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def write_project_metadata(
    project_dir: Path,
    task_id: str,
    input_type: str,
    input_item: str,
    project_name: str,
    status: ProjectStatus,
    engine: str = "heavy",
    source_markdown_path: str | None = None,
    translated_markdown_path: str | None = None,
    title: str | None = None,
    translation_model: str | None = None,
) -> None:
    """Persist TUI task metadata for one output project."""
    selected_engine = normalize_engine(engine)
    project_dir.mkdir(parents=True, exist_ok=True)
    previous = read_project_metadata(project_dir)
    if previous.get("task_id") != task_id or previous.get("engine", "heavy") != selected_engine:
        previous = {}
    metadata = {
        "schema_version": 3,
        "engine": selected_engine,
        "task_id": task_id,
        "input_type": input_type,
        "input_item": input_item,
        "project_name": project_name,
        "status": status.value,
        "source_markdown_path": source_markdown_path,
        "translated_markdown_path": translated_markdown_path,
        "title": title or previous.get("title") or "",
        "translation_model": translation_model or previous.get("translation_model") or "",
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }
    (project_dir / TUI_PROJECT_METADATA_FILENAME).write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def infer_project_status(project_dir: Path, engine: str = "heavy") -> ProjectStatus:
    """Infer project status from artifacts owned by the selected engine."""
    selected_engine = normalize_engine(engine)
    metadata_status = _metadata_status(read_project_metadata(project_dir))
    if metadata_status in {ProjectStatus.FAILED, ProjectStatus.CANCELLED}:
        return metadata_status

    if selected_engine == "lite":
        if _find_pdf(project_dir, selected_engine) is not None:
            return ProjectStatus.COMPLETED
        if _has_lite_artifacts(project_dir):
            return ProjectStatus.FAILED
        return ProjectStatus.PENDING

    if _errors_report_has_errors(project_dir / "errors_report.json"):
        return ProjectStatus.FAILED
    if _find_pdf(project_dir, selected_engine) is not None:
        return ProjectStatus.COMPLETED
    if (project_dir / "project_terms.csv").is_file():
        return ProjectStatus.TERMS_READY
    if _has_intermediate_artifacts(project_dir):
        return ProjectStatus.FAILED
    return ProjectStatus.PENDING


def _legacy_project_name(project_output_dir: Path) -> str:
    """Return project name for legacy output directories such as ch_2308.10248."""
    name = project_output_dir.name
    for prefix in ("ch_", "en_", "ja_", "fr_", "de_", "es_"):
        if name.startswith(prefix):
            return name[len(prefix) :]
    return name


def _infer_project_dir(project_output_dir: Path, metadata: dict[str, Any], project_name: str) -> Path | None:
    """Infer the source directory for a historical project."""
    source_dir = metadata.get("source_dir")
    if isinstance(source_dir, str) and source_dir:
        candidate = Path(source_dir)
        if candidate.exists():
            return candidate

    nested_dir = project_output_dir / project_name
    if nested_dir.is_dir():
        return nested_dir
    if project_output_dir.is_dir():
        return project_output_dir
    return None


def _metadata_status(metadata: dict[str, Any]) -> ProjectStatus | None:
    """Return a valid metadata status when present."""
    status = metadata.get("status")
    if not isinstance(status, str):
        return None
    try:
        return ProjectStatus(status)
    except ValueError:
        return None


def _errors_report_has_errors(errors_report_path: Path) -> bool:
    """Return whether errors_report.json contains at least one error entry."""
    if not errors_report_path.is_file():
        return False
    try:
        data = json.loads(errors_report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return True
    if isinstance(data, list):
        return len(data) > 0
    if isinstance(data, dict):
        return bool(data)
    return bool(data)


def _find_pdf(project_dir: Path, engine: str = "heavy") -> Path | None:
    """Find the translated PDF artifact for the selected engine."""
    if engine == "lite":
        translated_pdf = project_dir / "translated.pdf"
        return translated_pdf if translated_pdf.is_file() else None
    try:
        return next(path for path in sorted(project_dir.glob("*.pdf")) if path.is_file())
    except StopIteration:
        return None


def _has_intermediate_artifacts(project_dir: Path) -> bool:
    """Return whether the output directory has artifacts that indicate an incomplete run."""
    artifact_names = {
        "sections_map.json",
        "captions_map.json",
        "envs_map.json",
        "inputs_map.json",
        "newcommands_map.json",
        "initial_errors_report.json",
        "latextrans.log",
    }
    return any((project_dir / name).exists() for name in artifact_names)


def _has_lite_artifacts(project_dir: Path) -> bool:
    """Return whether a lite directory contains evidence of an incomplete run."""
    artifact_names = {
        "source.pdf",
        "source.md",
        "translated.md",
        "project_terms.csv",
        "project_terms_decisions.json",
        "latextrans.log",
    }
    return any((project_dir / name).exists() for name in artifact_names)


def _infer_project_engine(project_dir: Path, metadata: dict[str, Any]) -> str | None:
    """Infer engine identity while treating pre-v2 metadata as heavy."""
    metadata_engine = metadata.get("engine")
    if metadata_engine is not None:
        try:
            return normalize_engine(metadata_engine)
        except ValueError:
            return None
    if metadata:
        return "heavy"
    if any((project_dir / name).is_file() for name in ("source.md", "translated.md", "translated.pdf")):
        return "lite"
    return "heavy"


def _metadata_or_artifact_path(
    metadata: dict[str, Any],
    key: str,
    artifact_path: Path,
) -> str | None:
    """Return a persisted artifact path or infer it from a local file."""
    value = metadata.get(key)
    if isinstance(value, str) and value:
        return value
    return str(artifact_path) if artifact_path.is_file() else None
