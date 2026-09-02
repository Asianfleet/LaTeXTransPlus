"""Bridge between the Textual UI and the existing runtime workflow."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from src import runtime
from src.tui.config import ensure_ui_config

TuiEventCallback = Callable[[dict[str, Any]], None]


def run_tui_task(
    config_path: str,
    input_type: str,
    items: list[str],
    overrides: dict[str, Any],
    event_callback: TuiEventCallback,
) -> dict[str, Any]:
    """Run a UI-submitted translation task through the existing runtime."""
    resolved_config_path = str(ensure_ui_config(Path.cwd()))
    runtime_overrides = dict(overrides)
    project_items: list[str] = []
    project_url_items: list[str] = []

    if input_type == "arxiv":
        runtime_overrides["paper_list"] = list(items)
    elif input_type == "local":
        runtime_overrides["paper_list"] = []
        project_items = list(items)
    elif input_type == "remote":
        runtime_overrides["paper_list"] = []
        project_url_items = list(items)
    else:
        raise ValueError(f"Unsupported input type: {input_type}")

    config = runtime.load_runtime_config(config_path=resolved_config_path, overrides=runtime_overrides)
    prepare_project_names = _prepare_project_names(input_type, items)
    try:
        projects, config, projects_dir, output_dir = runtime.prepare_projects(
            config=config,
            project_items=project_items,
            project_url_items=project_url_items,
            all_existing=False,
            prepare_log_callback=lambda payload: _emit_prepare_log(
                payload,
                event_callback,
                prepare_project_names,
            ),
        )
    except ValueError:
        _emit_prepare_failure_events(input_type, items, event_callback)
        raise
    _emit_prepare_skip_events(input_type, items, projects, event_callback)
    project_status = runtime.run_projects(
        config=config,
        projects=projects,
        output_dir=output_dir,
        event_callback=event_callback,
    )

    return {
        "config": config,
        "projects": projects,
        "projects_dir": projects_dir,
        "output_dir": output_dir,
        "completed_projects": project_status["completed_projects"],
        "failed_projects": project_status["failed_projects"],
    }


def _emit_prepare_skip_events(
    input_type: str,
    items: list[str],
    projects: list[str],
    event_callback: TuiEventCallback,
) -> None:
    """Emit UI-visible failure events for inputs skipped before runtime processing."""
    if input_type == "remote":
        event_callback({"type": "run_start", "total": len(projects)})
        return
    skipped_items = _prepare_skipped_items(input_type, items, projects)
    for item in skipped_items:
        _emit_prepare_error(item, event_callback)


def _emit_prepare_log(
    payload: dict[str, Any],
    event_callback: TuiEventCallback,
    project_names: set[str] | None = None,
) -> None:
    """将准备阶段工具日志包装为项目日志或任务日志事件。"""
    event = dict(payload)
    project_name = str(event.get("project_name") or "")
    is_known_project = bool(project_name) and (
        project_names is None or project_name in project_names
    )
    event["type"] = "project_log" if is_known_project else "task_log"
    if not is_known_project:
        event.pop("project_name", None)
    event_callback(event)


def _prepare_project_names(input_type: str, items: list[str]) -> set[str]:
    """Return project names that can be confidently tied to submitted inputs."""
    names: set[str] = set()
    for item in items:
        item_name = Path(item).name
        names.add(item_name)
        names.add(_archive_stem(item_name))
    if input_type == "arxiv":
        try:
            names.update(str(item) for item in runtime.extract_arxiv_ids(items))
        except (TypeError, ValueError):
            pass
    return {name for name in names if name}


def _emit_prepare_failure_events(input_type: str, items: list[str], event_callback: TuiEventCallback) -> None:
    """Emit UI-visible failure events for every input when prepare fails completely."""
    if input_type == "remote":
        event_callback({"type": "run_start", "total": 0})
        return
    for item in items:
        _emit_prepare_error(item, event_callback)


def _emit_prepare_error(item: str, event_callback: TuiEventCallback) -> None:
    """Emit one UI-visible prepare failure event for a submitted input."""
    event_callback(
        {
            "type": "project_error",
            "project_name": item,
            "error": f"准备阶段跳过：{item}",
        }
    )


def _prepare_skipped_items(input_type: str, items: list[str], projects: list[str]) -> list[str]:
    """Infer which submitted items did not produce prepared project directories."""
    if len(projects) >= len(items):
        return []

    remaining_projects = [str(project) for project in projects]
    skipped: list[str] = []
    for item in items:
        matched_index = _matching_project_index(item, remaining_projects)
        if matched_index is None:
            skipped.append(item)
            continue
        remaining_projects.pop(matched_index)
    return skipped


def _matching_project_index(item: str, projects: list[str]) -> int | None:
    """Return the index of the prepared project that corresponds to an input item."""
    item_path = Path(item)
    item_name = item_path.name
    item_stem = _archive_stem(item_name)
    for index, project in enumerate(projects):
        project_path = Path(project)
        if project_path.name in {item_name, item_stem}:
            return index
        try:
            if item_path.exists() and item_path.resolve() == project_path.resolve():
                return index
        except OSError:
            continue
    return None


def _archive_stem(name: str) -> str:
    """Return the directory stem produced by archive extraction."""
    lower_name = name.lower()
    for suffix in (".tar.gz", ".tgz", ".tar", ".zip"):
        if lower_name.endswith(suffix):
            return name[: -len(suffix)]
    return Path(name).stem
