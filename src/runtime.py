import os
import tarfile
import zipfile
from copy import deepcopy
from contextlib import nullcontext
from pathlib import Path
from typing import Any, Callable, ContextManager, Dict, Iterable, List, Optional, Sequence

import toml

from src.agents.coordinator_agent import CoordinatorAgent
from src.config import load_llm_profile, parse_custom_json, resolve_llm_api_key
from src.engines.base import engine_config, engine_runtime_fields, normalize_engine
from src.engines.heavy import HeavyEngine
from src.engines.lite import LiteEngine
from src.formats.latex.utils import (
    batch_download_arxiv_tex,
    extract_arxiv_ids,
    extract_compressed_files,
    get_arxiv_category,
    get_profect_dirs,
)
from src.project_sources import RemoteArchiveDownloadError, download_remote_archive
from src.utils.progress import progress_log_context

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ProjectEventCallback = Callable[[Dict[str, Any]], None]
ProjectContextCallback = Callable[[int, int, str], ContextManager[None]]
ProjectLogCallback = Callable[[Dict[str, Any]], None]


def effective_engine_config(config: Dict[str, Any], engine: str) -> Dict[str, Any]:
    """Build an engine view while retaining explicit legacy runtime overrides."""
    if "heavy" not in config and "lite" not in config:
        return config
    effective = engine_config(config, engine)
    for key in engine_runtime_fields(engine):
        if key in config:
            effective[key] = deepcopy(config[key])
    return effective


def project_output_dir(output_dir: str, target_language: str, project_dir: str) -> Path:
    """返回单个项目的翻译输出目录。"""
    return Path(output_dir) / f"{target_language}_{Path(project_dir).name}"


def project_log_path(output_dir: str, target_language: str, project_dir: str) -> Path:
    """返回单个项目的 CLI 日志路径。"""
    return project_output_dir(output_dir, target_language, project_dir) / "latextrans.log"


def resolve_path(path_value: str) -> Path:
    p = Path(path_value)
    if p.is_absolute():
        return p
    return (PROJECT_ROOT / p).resolve()


def is_local_archive(path: str) -> bool:
    p = Path(path)
    if not path or not p.is_file():
        return False
    lower = p.name.lower()
    return lower.endswith((".zip", ".tar", ".tar.gz", ".tgz"))


def archive_project_dir(archive_path: str, projects_dir: str) -> str:
    name = os.path.basename(archive_path)
    lower = name.lower()
    if lower.endswith(".tar.gz"):
        stem = name[:-7]
    elif lower.endswith(".tgz"):
        stem = name[:-4]
    elif lower.endswith(".tar"):
        stem = name[:-4]
    elif lower.endswith(".zip"):
        stem = name[:-4]
    else:
        stem = os.path.splitext(name)[0]
    return os.path.join(projects_dir, stem)


def ensure_unique_dir(base_dir: Path) -> Path:
    if not base_dir.exists():
        return base_dir
    index = 1
    while True:
        candidate = base_dir.parent / f"{base_dir.name}_{index}"
        if not candidate.exists():
            return candidate
        index += 1


def is_within_dir(base_dir: Path, target_path: Path) -> bool:
    try:
        target_path.resolve().relative_to(base_dir.resolve())
        return True
    except ValueError:
        return False


def safe_extract_zip(zip_ref: zipfile.ZipFile, target_dir: Path) -> None:
    for member in zip_ref.infolist():
        member_path = target_dir / member.filename
        if not is_within_dir(target_dir, member_path):
            raise ValueError(f"Unsafe zip member path: {member.filename}")
    zip_ref.extractall(target_dir)


def safe_extract_tar(tar_ref: tarfile.TarFile, target_dir: Path) -> None:
    for member in tar_ref.getmembers():
        member_path = target_dir / member.name
        if not is_within_dir(target_dir, member_path):
            raise ValueError(f"Unsafe tar member path: {member.name}")
    tar_ref.extractall(target_dir)


def extract_local_archive(archive_path: str, projects_dir: str) -> str:
    target_dir = ensure_unique_dir(Path(archive_project_dir(archive_path, projects_dir)))
    target_dir.mkdir(parents=True, exist_ok=True)

    if zipfile.is_zipfile(archive_path):
        with zipfile.ZipFile(archive_path, "r") as zip_ref:
            safe_extract_zip(zip_ref, target_dir)
        return str(target_dir)

    if tarfile.is_tarfile(archive_path):
        with tarfile.open(archive_path, "r:*") as tar_ref:
            safe_extract_tar(tar_ref, target_dir)
        return str(target_dir)

    raise ValueError(f"Unsupported archive format: {archive_path}")


def split_cli_items(values: Sequence[str]) -> List[str]:
    raw = " ".join(values)
    return [item.strip() for item in raw.split(",") if item.strip()]


def split_multivalue_text(value: str) -> List[str]:
    if not value:
        return []
    normalized = value.replace("\n", ",")
    return [item.strip() for item in normalized.split(",") if item.strip()]


def load_runtime_config(
    config_path: str = "config/default.toml",
    overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    config = toml.load(config_path)
    overrides = overrides or {}

    load_llm_profile(config, config_path)
    llm_config = config["llm_config"]
    if "custom_json" in llm_config:
        llm_config["custom_json"] = parse_custom_json(llm_config["custom_json"])
    if overrides.get("url"):
        llm_config["base_url"] = overrides["url"]
    if overrides.get("model"):
        llm_config["model"] = overrides["model"]
    if overrides.get("key"):
        llm_config["api_key"] = overrides["key"]
    resolve_llm_api_key(config)

    heavy_config = config.get("heavy")
    heavy_overrides = heavy_config if isinstance(heavy_config, dict) else config

    for key in ("source", "output", "source_language", "target_language", "user_term"):
        if overrides.get(key):
            mapped_key = {
                "source": "tex_sources_dir",
                "output": "output_dir",
                "source_language": "source_language",
                "target_language": "target_language",
                "user_term": "user_term",
            }[key]
            target_config = heavy_overrides if key in {"source", "output"} else config
            target_config[mapped_key] = overrides[key]

    if overrides.get("mode") is not None:
        config["mode"] = overrides["mode"]
    if overrides.get("update_term") is not None:
        config["update_term"] = overrides["update_term"]
    if overrides.get("retranslate_with_terms") is not None:
        heavy_overrides["retranslate_with_terms"] = bool(overrides["retranslate_with_terms"])

    extra_papers = overrides.get("paper_list") or []
    if extra_papers:
        heavy_overrides.setdefault("paper_list", [])
        heavy_overrides["paper_list"].extend(extra_papers)

    return config


def prepare_projects(
    config: Dict[str, Any],
    project_items: Optional[Iterable[str]] = None,
    project_url_items: Optional[Iterable[str]] = None,
    all_existing: bool = False,
    prepare_log_callback: Optional[ProjectLogCallback] = None,
) -> tuple[List[str], Dict[str, Any], str, str]:
    """准备输入项目；可选回调用于将准备阶段日志转发给 TUI。"""
    def emit_prepare(message: str, level: str = "info", project_name: str | None = None) -> None:
        if prepare_log_callback:
            payload: Dict[str, Any] = {"level": level, "message": message, "line": message}
            if project_name:
                payload["project_name"] = project_name
            prepare_log_callback(payload)
        else:
            print(message)

    input_items = config.get("paper_list", [])
    projects_dir = str(resolve_path(config.get("tex_sources_dir", "tex source")))
    output_dir = str(resolve_path(config.get("output_dir", "outputs")))

    os.makedirs(projects_dir, exist_ok=True)
    os.makedirs(output_dir, exist_ok=True)

    paper_list = extract_arxiv_ids(input_items)
    project_items = [item for item in (project_items or []) if item]
    project_url_items = [item for item in (project_url_items or []) if item]

    if paper_list or project_items or project_url_items:
        projects: List[str] = []

        if paper_list:
            if prepare_log_callback:
                projects.extend(
                    batch_download_arxiv_tex(
                        paper_list,
                        projects_dir,
                        log_callback=prepare_log_callback,
                    )
                )
            else:
                projects.extend(batch_download_arxiv_tex(paper_list, projects_dir))
            if not config.get("user_term"):
                if prepare_log_callback:
                    config["category"] = get_arxiv_category(
                        paper_list,
                        log_callback=prepare_log_callback,
                    )
                else:
                    config["category"] = get_arxiv_category(paper_list)
            if prepare_log_callback:
                extract_compressed_files(projects_dir, log_callback=prepare_log_callback)
            else:
                extract_compressed_files(projects_dir)

        for project_path in project_items:
            resolved_project_path = str(resolve_path(project_path))
            if os.path.isdir(resolved_project_path):
                projects.append(os.path.abspath(resolved_project_path))
                continue
            if is_local_archive(resolved_project_path):
                try:
                    projects.append(extract_local_archive(resolved_project_path, projects_dir))
                except Exception as e:
                    emit_prepare(f"[SKIP] Failed to extract local archive {project_path}: {e}", "error")
                continue
            emit_prepare(f"[SKIP] Invalid local project path: {project_path}", "error")

        for project_url in project_url_items:
            archive_path: Optional[str] = None
            try:
                archive_path = download_remote_archive(project_url, projects_dir)
                projects.append(extract_local_archive(archive_path, projects_dir))
            except RemoteArchiveDownloadError as e:
                emit_prepare(f"[SKIP] Failed to download remote archive {project_url}: {e}", "error")
            except Exception as e:
                emit_prepare(f"[SKIP] Failed to extract remote archive {project_url}: {e}", "error")
            finally:
                if archive_path:
                    try:
                        Path(archive_path).unlink(missing_ok=True)
                    except OSError:
                        pass
    elif all_existing:
        emit_prepare("No explicit inputs. Processing all existing projects in the specified directory.")
        if prepare_log_callback:
            extract_compressed_files(projects_dir, log_callback=prepare_log_callback)
        else:
            extract_compressed_files(projects_dir)
        projects = get_profect_dirs(projects_dir)
        if not projects:
            raise ValueError("No projects found. Check 'tex_sources_dir' and 'paper_list' in config.")
    else:
        raise ValueError(
            "No input provided. Use --arxiv, --project, or --project-url. "
            "To process existing projects, pass --all-existing."
        )

    projects = [os.path.abspath(p) for p in projects if isinstance(p, (str, os.PathLike))]
    projects = list(dict.fromkeys(projects))
    if not projects:
        raise ValueError("No valid TeX projects available for processing.")

    return projects, config, projects_dir, output_dir


def classify_project_result(
    index: int,
    total: int,
    project_name: str,
    project_dir: str,
    workflow_result: Dict[str, Any],
    output_dir: Optional[str] = None,
    log_path: Optional[str] = None,
) -> Dict[str, Any]:
    ok = workflow_result.get("ok", False)
    result = {
        "type": "completed" if ok else "failed",
        "ok": ok,
        "engine": workflow_result.get("engine", "heavy"),
        "index": index,
        "total": total,
        "project_name": project_name,
        "project_dir": project_dir,
        "pdf_path": workflow_result.get("pdf_path"),
        "errors_report_path": workflow_result.get("errors_report_path"),
        "validation_summary": workflow_result.get(
            "validation_summary",
            {"warnings": 0, "errors": 0, "total": 0},
        ),
        "error": workflow_result.get("error"),
        "pdf_error": workflow_result.get("pdf_error"),
    }
    if output_dir is not None:
        result["output_dir"] = output_dir
    if log_path is not None:
        result["log_path"] = log_path
    for key in ("status", "project_terms_path", "project_terms_decisions_path"):
        if key in workflow_result:
            result[key] = workflow_result[key]
    return result


def should_exit_with_failure(project_status: Dict[str, List[Dict[str, Any]]]) -> bool:
    return bool(project_status.get("failed_projects"))


def _build_project_log_callback(
    event_callback: Optional[ProjectEventCallback],
    log_file: Any,
    engine: str,
    project_name: str,
    project_dir: str,
    project_output_path: str,
    log_path: str,
    write_file: bool = True,
) -> ProjectLogCallback:
    """创建写入项目日志文件并转发 runtime 日志事件的回调。"""

    def project_log_callback(payload: Dict[str, Any]) -> None:
        """写入单条 agent 日志，并向上层发出 project_log 事件。"""
        line = str(payload.get("line") or payload.get("message") or "")
        if line and write_file:
            log_file.write(f"{line}\n")
            log_file.flush()
        if event_callback:
            event_payload = {
                "type": "project_log",
                "engine": engine,
                "project_name": project_name,
                "project_dir": project_dir,
                "output_dir": project_output_path,
                "log_path": log_path,
                "agent_name": payload.get("agent_name"),
                "level": payload.get("level", "info"),
                "message": payload.get("message"),
                "line": line,
            }
            event_callback(event_payload)

    return project_log_callback


def run_projects(
    config: Dict[str, Any],
    projects: Sequence[str],
    output_dir: str,
    event_callback: Optional[ProjectEventCallback] = None,
    project_context: Optional[ProjectContextCallback] = None,
) -> Dict[str, List[Dict[str, Any]]]:
    """Run prepared heavy projects while preserving the legacy result contract."""
    completed_projects: List[Dict[str, Any]] = []
    failed_projects: List[Dict[str, Any]] = []
    total_projects = len(projects)
    for idx, project_dir in enumerate(projects, start=1):
        context = project_context(idx, total_projects, project_dir) if project_context else nullcontext()
        with context:
            project_name = os.path.basename(project_dir)
            target_language = config.get("target_language", "ch")
            project_output_path = str(project_output_dir(output_dir, target_language, project_dir))
            log_path = str(project_log_path(output_dir, target_language, project_dir))
            Path(log_path).parent.mkdir(parents=True, exist_ok=True)
            if project_context is None:
                Path(log_path).write_text("", encoding="utf-8")
            if event_callback:
                event_callback(
                    {
                        "type": "project_start",
                        "engine": "heavy",
                        "index": idx,
                        "total": total_projects,
                        "project_name": project_name,
                        "project_dir": project_dir,
                        "output_dir": project_output_path,
                        "log_path": log_path,
                    }
                )

            with Path(log_path).open("a", encoding="utf-8", buffering=1) as log_file:
                processing_line = f"[{idx}/{total_projects}] Processing {project_name}"
                if project_context is not None:
                    print(processing_line)
                else:
                    log_file.write(f"{processing_line}\n")
                project_config = dict(config)
                project_config["_project_log_callback"] = _build_project_log_callback(
                    event_callback=event_callback,
                    log_file=log_file,
                    engine="heavy",
                    project_name=project_name,
                    project_dir=project_dir,
                    project_output_path=project_output_path,
                    log_path=log_path,
                    write_file=project_context is None,
                )
                project_config["_project_log_print_console"] = project_context is not None

                with progress_log_context(
                    project_config["_project_log_callback"],
                    emit_console=project_context is not None,
                ):
                    try:
                        heavy_engine = HeavyEngine(coordinator_factory=CoordinatorAgent)
                        workflow_result = heavy_engine.run(
                            project_dir,
                            project_config,
                            Path(output_dir),
                            project_config["_project_log_callback"],
                        )
                        project_result = classify_project_result(
                            index=idx,
                            total=total_projects,
                            project_name=project_name,
                            project_dir=project_dir,
                            workflow_result=workflow_result,
                            output_dir=project_output_path,
                            log_path=log_path,
                        )
                    except Exception as e:
                        error_line = f"Error processing project {project_name}: {e}"
                        if project_context is not None:
                            print(error_line)
                        else:
                            log_file.write(f"{error_line}\n")
                        failure_result = {
                            "type": "failed",
                            "ok": False,
                            "engine": "heavy",
                            "index": idx,
                            "total": total_projects,
                            "project_name": project_name,
                            "project_dir": project_dir,
                            "output_dir": project_output_path,
                            "pdf_path": None,
                            "errors_report_path": None,
                            "validation_summary": None,
                            "error": str(e),
                            "log_path": log_path,
                        }
                        failed_projects.append(failure_result)
                        if event_callback:
                            event_payload = dict(failure_result)
                            event_payload["type"] = "project_error"
                            event_callback(event_payload)
                        continue

            if project_result["ok"]:
                completed_projects.append(project_result)
                event_type = "project_complete"
            else:
                failed_projects.append(project_result)
                event_type = "project_error"

            if event_callback:
                event_payload = {
                    "type": event_type,
                    "engine": "heavy",
                    "index": idx,
                    "total": total_projects,
                    "project_name": project_name,
                    "project_dir": project_dir,
                    "output_dir": project_output_path,
                    "pdf_path": project_result.get("pdf_path"),
                    "errors_report_path": project_result.get("errors_report_path"),
                    "validation_summary": project_result.get("validation_summary"),
                    "error": project_result.get("error"),
                    "log_path": log_path,
                }
                for key in ("status", "pdf_error", "project_terms_path", "project_terms_decisions_path"):
                    if key in project_result:
                        event_payload[key] = project_result[key]
                event_callback(event_payload)
    return {
        "completed_projects": completed_projects,
        "failed_projects": failed_projects,
    }


_LITE_ARTIFACT_FIELDS = (
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


def _lite_artifact_payload(source: Dict[str, Any]) -> Dict[str, Any]:
    """Return the lite engine identity and artifact fields for runtime events."""
    payload = {key: source.get(key) for key in _LITE_ARTIFACT_FIELDS}
    payload["engine"] = "lite"
    return payload


def _merge_lite_artifacts(
    primary: Dict[str, Any],
    fallback: Dict[str, Any],
) -> Dict[str, Any]:
    """Merge observed lite paths without replacing known values with nulls."""
    merged = _lite_artifact_payload(fallback)
    for key in _LITE_ARTIFACT_FIELDS:
        if primary.get(key) is not None:
            merged[key] = primary[key]
    return merged


def _lite_log_path(source: Dict[str, Any]) -> Optional[str]:
    """Return the project-local lite log path when a project directory exists."""
    output_dir = source.get("output_dir") or source.get("project_dir")
    if not output_dir:
        return None
    return str(Path(str(output_dir)) / "latextrans.log")


def _append_lite_log(log_path: Optional[str], line: str) -> None:
    """Append one UTF-8 line to a lite project log when its path is known."""
    if not log_path or not line:
        return
    path = Path(log_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", buffering=1) as log_file:
        log_file.write(f"{line}\n")


def _run_lite_engine_task(
    item: str,
    config: Dict[str, Any],
    output_root: Path,
    event_callback: ProjectEventCallback,
) -> Dict[str, Any]:
    """Run one lite item and translate its logs into ordered project events."""
    buffered_logs: List[Dict[str, Any]] = []
    observed_artifacts: Dict[str, Any] = {}
    start_emitted = False

    def emit_start(source: Dict[str, Any]) -> None:
        """Emit one lite project_start event with all engine-specific fields."""
        nonlocal start_emitted
        if start_emitted:
            return
        payload = _lite_artifact_payload(source)
        payload.update(
            {
                "type": "project_start",
                "index": 1,
                "total": 1,
                "log_path": _lite_log_path(payload),
            }
        )
        event_callback(payload)
        start_emitted = True

    def emit_log(payload: Dict[str, Any], fallback: Dict[str, Any]) -> None:
        """Write and forward one project-scoped lite log event."""
        artifacts = _merge_lite_artifacts(payload, fallback)
        log_path = _lite_log_path(artifacts)
        line = str(payload.get("line") or payload.get("message") or "")
        _append_lite_log(log_path, line)
        event = dict(artifacts)
        event.update(
            {
                "type": "project_log",
                "index": 1,
                "total": 1,
                "log_path": log_path,
                "agent_name": payload.get("agent_name"),
                "level": payload.get("level", "info"),
                "message": payload.get("message"),
                "line": line,
            }
        )
        event_callback(event)

    def log_callback(payload: Dict[str, Any]) -> None:
        """Buffer pre-project logs and stream later logs after project_start."""
        nonlocal start_emitted
        for key in _LITE_ARTIFACT_FIELDS:
            if payload.get(key) is not None:
                observed_artifacts[key] = payload[key]
        if not start_emitted and payload.get("project_dir"):
            emit_start(payload)
            for buffered in buffered_logs:
                emit_log(buffered, payload)
            buffered_logs.clear()
        if start_emitted:
            emit_log(payload, observed_artifacts)
        else:
            buffered_logs.append(dict(payload))

    try:
        workflow_result = LiteEngine().run(item, config, output_root, log_callback)
    except Exception as exc:
        workflow_result = {
            "ok": False,
            "engine": "lite",
            "project_name": Path(item).stem or item,
            "project_dir": None,
            "output_dir": None,
            "source_markdown_path": None,
            "translated_markdown_path": None,
            "pdf_path": None,
            "project_terms_path": None,
            "project_terms_decisions_path": None,
            "error": str(exc),
        }

    workflow_result = _merge_lite_artifacts(workflow_result, observed_artifacts) | {
        "ok": bool(workflow_result.get("ok", False)),
        "error": workflow_result.get("error"),
    }
    if not start_emitted:
        emit_start(workflow_result)
        for buffered in buffered_logs:
            emit_log(buffered, workflow_result)

    project_result = dict(_lite_artifact_payload(workflow_result))
    project_result.update(
        {
            "type": "completed" if workflow_result["ok"] else "failed",
            "ok": workflow_result["ok"],
            "index": 1,
            "total": 1,
            "error": workflow_result.get("error"),
            "log_path": _lite_log_path(workflow_result),
        }
    )
    event_payload = dict(project_result)
    event_payload["type"] = (
        "project_complete" if workflow_result["ok"] else "project_error"
    )
    event_callback(event_payload)

    completed_projects = [project_result] if workflow_result["ok"] else []
    failed_projects = [] if workflow_result["ok"] else [project_result]
    project_dir = workflow_result.get("project_dir")
    return {
        "config": config,
        "projects": [project_dir] if project_dir else [],
        "projects_dir": str(output_root),
        "output_dir": str(output_root),
        "completed_projects": completed_projects,
        "failed_projects": failed_projects,
    }


def _emit_heavy_prepare_log(
    payload: Dict[str, Any],
    event_callback: ProjectEventCallback,
) -> None:
    """Forward a heavy input-preparation message as an engine-aware task log."""
    event = dict(payload)
    event["type"] = "task_log"
    event["engine"] = "heavy"
    event_callback(event)


def run_engine_task(
    engine: str,
    input_type: str,
    items: List[str],
    config: Dict[str, Any],
    event_callback: ProjectEventCallback,
) -> Dict[str, Any]:
    """Dispatch one TUI task through an isolated effective engine config."""
    selected_engine = normalize_engine(engine or config.get("engine"))
    effective_config = deepcopy(effective_engine_config(config, selected_engine))
    effective_config["engine"] = selected_engine

    if selected_engine == "lite":
        if len(items) != 1:
            raise ValueError("Lite engine accepts exactly one input item per task.")
        output_root = resolve_path(str(effective_config.get("output_dir", "output-lite")))
        return _run_lite_engine_task(
            items[0],
            effective_config,
            output_root,
            event_callback,
        )

    project_items: List[str] = []
    project_url_items: List[str] = []
    if input_type == "arxiv":
        effective_config["paper_list"] = list(items)
    elif input_type == "local":
        effective_config["paper_list"] = []
        project_items = list(items)
    elif input_type == "remote":
        effective_config["paper_list"] = []
        project_url_items = list(items)
    else:
        raise ValueError(f"Unsupported heavy input type: {input_type}")

    projects, effective_config, projects_dir, output_dir = prepare_projects(
        config=effective_config,
        project_items=project_items,
        project_url_items=project_url_items,
        all_existing=False,
        prepare_log_callback=lambda payload: _emit_heavy_prepare_log(
            payload,
            event_callback,
        ),
    )
    project_status = run_projects(
        config=effective_config,
        projects=projects,
        output_dir=output_dir,
        event_callback=event_callback,
    )
    return {
        "config": effective_config,
        "projects": projects,
        "projects_dir": projects_dir,
        "output_dir": output_dir,
        "completed_projects": project_status["completed_projects"],
        "failed_projects": project_status["failed_projects"],
    }


def run_translation(
    config_path: str = "config/default.toml",
    overrides: Optional[Dict[str, Any]] = None,
    project_items: Optional[Iterable[str]] = None,
    project_url_items: Optional[Iterable[str]] = None,
    all_existing: bool = False,
    event_callback: Optional[ProjectEventCallback] = None,
) -> Dict[str, Any]:
    """Run the legacy CLI through the effective heavy-engine configuration."""
    loaded_config = load_runtime_config(config_path=config_path, overrides=overrides)
    config = effective_engine_config(loaded_config, "heavy")
    projects, config, projects_dir, output_dir = prepare_projects(
        config=config,
        project_items=project_items,
        project_url_items=project_url_items,
        all_existing=all_existing,
    )
    project_status = run_projects(
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
