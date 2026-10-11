"""处理 TUI 错误报告及其关联内容的纯数据逻辑。"""

from __future__ import annotations

import json
from pathlib import Path

from src.tui.state import ProjectViewState


def project_errors_report_path(project: ProjectViewState) -> Path | None:
    """解析项目错误报告路径，但不修改项目状态。"""
    if project.errors_report_path:
        report_path = Path(project.errors_report_path)
        if report_path.is_file():
            return report_path
    if project.output_dir:
        fallback_path = Path(project.output_dir) / "errors_report.json"
        if fallback_path.is_file():
            return fallback_path
    return None


def error_reports_with_status(
    project: ProjectViewState,
    report_path: Path | None,
) -> list[tuple[dict[str, object], str]]:
    """合并最终和初始错误报告并标注解决状态。"""
    final_reports = read_error_report(str(report_path) if report_path else None)
    initial_path = initial_error_report_path(str(report_path) if report_path else None)
    initial_reports = read_error_report(str(initial_path) if initial_path else None)
    if not final_reports and not initial_reports:
        if project.error:
            return [
                (
                    {"part": "project", "num_or_ph": "-", "error": project.error},
                    "unresolved",
                )
            ]
        if project.pdf_error:
            return [
                (
                    {"part": "project", "num_or_ph": "-", "error": project.pdf_error},
                    "warning",
                )
            ]
        return []

    final_by_key = {error_report_key(report): report for report in final_reports}
    initial_by_key = {error_report_key(report): report for report in initial_reports}
    rows: list[tuple[dict[str, object], str]] = []
    for key, report in final_by_key.items():
        rows.append((report, "unresolved"))
        initial_by_key.pop(key, None)
    for report in initial_by_key.values():
        rows.append((report, "resolved"))
    return rows


def read_error_report(report_path: str | None) -> list[dict[str, object]]:
    """从 JSON 错误报告读取列表格式记录。"""
    if not report_path:
        return []
    path = Path(report_path)
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict)]


def initial_error_report_path(report_path: str | None) -> Path | None:
    """返回最终错误报告同目录下的初始错误报告路径。"""
    if not report_path:
        return None
    return Path(report_path).parent / "initial_errors_report.json"


def error_report_key(report: dict[str, object]) -> tuple[str, str]:
    """返回用于判断同一错误位置是否仍未解决的稳定键。"""
    return (str(report.get("part") or ""), str(report.get("num_or_ph") or ""))


def error_report_position(report: dict[str, object]) -> str:
    """把错误记录的位置字段转换为表格显示文本。"""
    part = str(report.get("part") or "")
    identifier = str(report.get("num_or_ph") or "-")
    part_labels = {"sec": "章节", "cap": "图题", "env": "环境", "project": "项目"}
    label = part_labels.get(part, part or "项目")
    return f"{label} {identifier}".strip()


def error_report_type(report: dict[str, object]) -> str:
    """从 issue 类型和旧字段推断错误类型显示文本。"""
    issue_labels = {
        "command_mismatch": "命令",
        "placeholder_mismatch": "占位符",
        "bracket_mismatch": "括号",
    }
    labels: list[str] = []
    issues = report.get("issues")
    if isinstance(issues, list):
        for issue in issues:
            if isinstance(issue, dict):
                issue_type = str(issue.get("type") or "")
                label = issue_labels.get(issue_type, issue_type)
                if label and label not in labels:
                    labels.append(label)
    legacy_fields = [
        ("command_error", "命令"),
        ("ph_error", "占位符"),
        ("bracket_error", "括号"),
    ]
    for field, label in legacy_fields:
        if report.get(field) and label not in labels:
            labels.append(label)
    return "、".join(labels) if labels else "项目"


def error_report_problem(report: dict[str, object]) -> str:
    """从新旧错误报告字段拼接问题说明。"""
    messages: list[str] = []
    issues = report.get("issues")
    if isinstance(issues, list):
        for issue in issues:
            if isinstance(issue, dict) and issue.get("message"):
                messages.append(str(issue["message"]))
    for field in ("command_error", "ph_error", "bracket_error", "error"):
        value = report.get(field)
        if value:
            messages.append(str(value))
    return "\n".join(messages)


def error_report_content(
    report: dict[str, object],
    project: ProjectViewState,
) -> tuple[str, str]:
    """反查错误位置对应的原文和译文内容。"""
    content_root = error_content_root(project)
    if content_root is None:
        return "", ""
    part = str(report.get("part") or "")
    identifier = str(report.get("num_or_ph") or "")
    part_record = find_error_part_record(content_root, part, identifier)
    if part_record is None:
        return "", ""
    return str(part_record.get("content") or ""), str(part_record.get("trans_content") or "")


def error_content_root(project: ProjectViewState) -> Path | None:
    """确定错误报告关联的输出目录，用于读取 map JSON。"""
    if project.errors_report_path:
        return Path(project.errors_report_path).parent
    if project.output_dir:
        return Path(project.output_dir)
    return None


def find_error_part_record(
    content_root: Path,
    part: str,
    identifier: str,
) -> dict[str, object] | None:
    """在章节、图题和环境 map 中查找错误位置的内容记录。"""
    map_specs = {
        "sec": ("sections_map.json", "section"),
        "cap": ("captions_map.json", "placeholder"),
        "env": ("envs_map.json", "placeholder"),
    }
    spec = map_specs.get(part)
    if spec is None:
        return None
    filename, key = spec
    for record in read_json_list(content_root / filename):
        if str(record.get(key) or "") == identifier:
            return record
    return None


def read_json_list(path: Path) -> list[dict[str, object]]:
    """读取 JSON 列表文件，并过滤非对象元素。"""
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict)]
