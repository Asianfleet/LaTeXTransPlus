import os
import tarfile
import zipfile
from contextlib import nullcontext
from pathlib import Path
from typing import Any, Callable, ContextManager, Dict, Iterable, List, Optional, Sequence

import toml

from src.agents.coordinator_agent import CoordinatorAgent
from src.config import load_llm_profile, parse_custom_json, resolve_llm_api_key
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

    for key in ("source", "output", "source_language", "target_language", "user_term"):
        if overrides.get(key):
            mapped_key = {
                "source": "tex_sources_dir",
                "output": "output_dir",
                "source_language": "source_language",
                "target_language": "target_language",
                "user_term": "user_term",
            }[key]
            config[mapped_key] = overrides[key]

    if overrides.get("mode") is not None:
        config["mode"] = overrides["mode"]
    if overrides.get("update_term") is not None:
        config["update_term"] = overrides["update_term"]
    if overrides.get("retranslate_with_terms") is not None:
        config["retranslate_with_terms"] = bool(overrides["retranslate_with_terms"])

    extra_papers = overrides.get("paper_list") or []
    if extra_papers:
        config.setdefault("paper_list", [])
        config["paper_list"].extend(extra_papers)

    return config


def prepare_projects(
    config: Dict[str, Any],
    project_items: Optional[Iterable[str]] = None,
    project_url_items: Optional[Iterable[str]] = None,
    all_existing: bool = False,
) -> tuple[List[str], Dict[str, Any], str, str]:
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
            projects.extend(batch_download_arxiv_tex(paper_list, projects_dir))
            if not config.get("user_term"):
                config["category"] = get_arxiv_category(paper_list)
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
                    print(f"[SKIP] Failed to extract local archive {project_path}: {e}")
                continue
            print(f"[SKIP] Invalid local project path: {project_path}")

        for project_url in project_url_items:
            archive_path: Optional[str] = None
            try:
                archive_path = download_remote_archive(project_url, projects_dir)
                projects.append(extract_local_archive(archive_path, projects_dir))
            except RemoteArchiveDownloadError as e:
                print(f"[SKIP] Failed to download remote archive {project_url}: {e}")
            except Exception as e:
                print(f"[SKIP] Failed to extract remote archive {project_url}: {e}")
            finally:
                if archive_path:
                    try:
                        Path(archive_path).unlink(missing_ok=True)
                    except OSError:
                        pass
    elif all_existing:
        print("No explicit inputs. Processing all existing projects in the specified directory.")
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
                        latex_trans = CoordinatorAgent(
                            config=project_config,
                            project_dir=project_dir,
                            output_dir=output_dir,
                        )
                        if project_config.get("retranslate_with_terms", False):
                            workflow_result = latex_trans.workflow_latextrans_with_existing_terms()
                        else:
                            workflow_result = latex_trans.workflow_latextrans()
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
                for key in ("status", "project_terms_path", "project_terms_decisions_path"):
                    if key in project_result:
                        event_payload[key] = project_result[key]
                event_callback(event_payload)
    return {
        "completed_projects": completed_projects,
        "failed_projects": failed_projects,
    }


def run_translation(
    config_path: str = "config/default.toml",
    overrides: Optional[Dict[str, Any]] = None,
    project_items: Optional[Iterable[str]] = None,
    project_url_items: Optional[Iterable[str]] = None,
    all_existing: bool = False,
    event_callback: Optional[ProjectEventCallback] = None,
) -> Dict[str, Any]:
    config = load_runtime_config(config_path=config_path, overrides=overrides)
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
