"""Bridge between the Textual UI and the existing runtime workflow."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from src import runtime
from src.tui.config import ensure_ui_config

TuiEventCallback = Callable[[dict[str, Any]], None]

_HEAVY_PREPARE_ERROR_MESSAGES = {
    "No projects found. Check 'tex_sources_dir' and 'paper_list' in config.",
    "No valid TeX projects available for processing.",
    "No input provided. Use --arxiv, --project, or --project-url. "
    "To process existing projects, pass --all-existing.",
}


def run_tui_task(
    config_path: str,
    input_type: str,
    items: list[str],
    overrides: dict[str, Any],
    event_callback: TuiEventCallback,
    engine: str = "heavy",
) -> dict[str, Any]:
    """Run a UI task through the engine captured when the task was created."""
    selected_engine = runtime.normalize_engine(engine)
    resolved_config_path = str(ensure_ui_config(Path.cwd()))
    runtime_overrides = dict(overrides)
    remote_start_emitted = False
    full_input_start_emitted = False

    if selected_engine == "lite":
        runtime_overrides.pop("retranslate_with_terms", None)
    else:
        if input_type == "arxiv":
            runtime_overrides["paper_list"] = list(items)
        elif input_type in {"local", "remote"}:
            runtime_overrides["paper_list"] = []
        else:
            raise ValueError(f"Unsupported input type: {input_type}")

    config = runtime.load_runtime_config(config_path=resolved_config_path, overrides=runtime_overrides)
    translation_model = str(config.get("llm_config", {}).get("model", "gpt-4o") or "")
    prepare_project_names = _prepare_project_names(input_type, items)

    def emit_full_input_start() -> None:
        """Set the heavy task total to all submitted local or ArXiv inputs once."""
        nonlocal full_input_start_emitted
        if full_input_start_emitted:
            return
        event_callback(
            {
                "type": "run_start",
                "engine": selected_engine,
                "total": len(items),
            }
        )
        full_input_start_emitted = True

    def forward_event(event: dict[str, Any]) -> None:
        """Tag events with the immutable task engine before forwarding them."""
        nonlocal remote_start_emitted
        tagged_event = dict(event)
        tagged_event["engine"] = selected_engine
        if tagged_event.get("project_name"):
            tagged_event["translation_model"] = translation_model
        if (
            selected_engine == "heavy"
            and input_type in {"arxiv", "local"}
            and tagged_event.get("type")
            in {"project_start", "project_complete", "project_error"}
        ):
            emit_full_input_start()
        if (
            selected_engine == "heavy"
            and input_type == "remote"
            and not remote_start_emitted
            and tagged_event.get("type")
            in {"project_start", "project_complete", "project_error"}
        ):
            event_callback(
                {
                    "type": "run_start",
                    "engine": selected_engine,
                    "total": int(tagged_event.get("total") or 0),
                }
            )
            remote_start_emitted = True
        event_callback(tagged_event)

    try:
        result = runtime.run_engine_task(
            engine=selected_engine,
            input_type=input_type,
            items=list(items),
            config=config,
            event_callback=lambda event: _emit_engine_event(
                event,
                forward_event,
                prepare_project_names,
            ),
        )
    except ValueError as error:
        if selected_engine == "heavy" and _is_heavy_prepare_error(error):
            if input_type in {"arxiv", "local"}:
                emit_full_input_start()
            _emit_prepare_failure_events(input_type, items, forward_event)
        raise

    if selected_engine == "heavy" and input_type != "remote":
        _emit_prepare_skip_events(
            input_type,
            items,
            list(result.get("projects") or []),
            forward_event,
        )
    elif selected_engine == "heavy" and not remote_start_emitted:
        forward_event({"type": "run_start", "total": len(result.get("projects") or [])})
    return result


def _is_heavy_prepare_error(error: ValueError) -> bool:
    """Return whether a known heavy input-preparation failure reached the runner."""
    return str(error) in _HEAVY_PREPARE_ERROR_MESSAGES


def _emit_engine_event(
    event: dict[str, Any],
    event_callback: TuiEventCallback,
    project_names: set[str],
) -> None:
    """Preserve runtime event types while scoping preparation logs safely."""
    if event.get("type") != "task_log":
        event_callback(event)
        return
    _emit_prepare_log(event, event_callback, project_names)


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
