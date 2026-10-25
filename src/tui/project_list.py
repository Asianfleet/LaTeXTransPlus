"""侧栏项目条目的标题、排序和临时进度展示。"""

from __future__ import annotations

from datetime import datetime
import os
from pathlib import Path
import unicodedata
from typing import Literal, Sequence

from rich.text import Text
from textual import events
from textual.widgets import ListItem, Static

from src.tui.state import ProjectStatus, ProjectViewState, TaskViewState


ProjectSortMode = Literal["initial", "title", "created_at"]
ProjectStateRow = tuple[TaskViewState, ProjectViewState]
PROJECT_SORT_BY_INITIAL: ProjectSortMode = "initial"
PROJECT_SORT_BY_TITLE: ProjectSortMode = "title"
PROJECT_SORT_BY_CREATED_AT: ProjectSortMode = "created_at"
PROJECT_SORT_OPTIONS: tuple[tuple[str, ProjectSortMode], ...] = (
    ("按首字符排序", PROJECT_SORT_BY_INITIAL),
    ("按标题排序", PROJECT_SORT_BY_TITLE),
    ("按创建时间排序", PROJECT_SORT_BY_CREATED_AT),
)


def sort_project_states(
    project_states: Sequence[ProjectStateRow],
    mode: str,
) -> list[ProjectStateRow]:
    """按侧栏选择的模式稳定排序项目状态，不修改输入序列。"""
    if mode == PROJECT_SORT_BY_TITLE:
        return sorted(project_states, key=_title_sort_key)
    if mode == PROJECT_SORT_BY_CREATED_AT:
        return sorted(project_states, key=_created_at_sort_key)
    return sorted(project_states, key=_initial_sort_key)


def _initial_sort_key(row: ProjectStateRow) -> tuple[str]:
    """返回项目名首字符的规范化排序键。"""
    return (_normalized_text(row[1].project_name)[:1],)


def _title_sort_key(row: ProjectStateRow) -> tuple[str]:
    """返回项目标题的规范化排序键。"""
    return (_normalized_text(row[1].title or "未识别标题"),)


def _created_at_sort_key(row: ProjectStateRow) -> tuple[float]:
    """返回按创建时间倒序排列的数值排序键。"""
    return (-_creation_timestamp(row),)


def _normalized_text(value: str) -> str:
    """统一 Unicode 形式并忽略大小写，供文本排序使用。"""
    return unicodedata.normalize("NFKC", value).casefold()


def _stat_creation_timestamp(stat: object, platform_name: str) -> float:
    """从文件状态中读取可靠的创建时间，避免误用 POSIX 的 st_ctime。"""
    birth_time = getattr(stat, "st_birthtime", None)
    if birth_time is not None:
        return float(birth_time)
    if platform_name == "nt":
        # Python 3.11 及更早版本的 Windows st_ctime 仍表示创建时间。
        return float(getattr(stat, "st_ctime"))
    return float("-inf")


def _creation_timestamp(row: ProjectStateRow) -> float:
    """从任务时间戳或历史项目目录获取创建时间，缺失时返回负无穷。"""
    task_id = row[0].task_id
    for format_string in ("%Y%m%dT%H%M%S.%f", "%Y%m%dT%H%M%S"):
        try:
            return datetime.strptime(task_id, format_string).timestamp()
        except ValueError:
            continue

    output_dir = row[1].output_dir
    if output_dir:
        try:
            stat = Path(output_dir).stat()
            return _stat_creation_timestamp(stat, os.name)
        except (OSError, ValueError):
            pass
    return float("-inf")


class ProjectListItem(ListItem):
    """以完整项目身份标识条目，并局部更新第二行进度。"""

    def __init__(
        self, task_id: str, project: ProjectViewState, running_task: bool
    ) -> None:
        """构建单行标题和可隐藏的进度行，保留原有任务颜色。"""
        self.project_key = (task_id, project.project_name)
        self._progress_indent = min(len(project.project_name), 10) + 3
        display_title = project.title or "未识别标题"
        text = f"{project.project_name} · {display_title}"
        title = Static(Text(text, overflow="ellipsis", no_wrap=True))
        tooltip = Text(project.project_name + "\n" + display_title)
        title.tooltip = tooltip
        if running_task:
            title.add_class("running-task-project")
        self.progress_label = Static(classes="project-progress")
        self._displayed_progress: str | None = None
        super().__init__(title, self.progress_label)
        self.tooltip = tooltip
        self.update_progress(project)

    def update_progress(self, project: ProjectViewState) -> None:
        """仅在项目运行且已有阶段文本时显示第二行。"""
        visible = project.status == ProjectStatus.RUNNING and bool(project.progress_text)
        text = project.progress_text if visible else ""
        if self._displayed_progress == text:
            return
        self._displayed_progress = text
        self.progress_label.update(
            Text("⌊ " + text, overflow="ellipsis", no_wrap=True)
        )
        self.progress_label.tooltip = Text(project.progress_text) if visible else None
        self.progress_label.display = visible

    def on_resize(self, event: events.Resize) -> None:
        """缩窄条目时收缩缩进，至少留出十二列展示进度文本。"""
        indent = min(self._progress_indent, max(0, self.content_size.width - 12))
        self.progress_label.styles.padding = (0, 0, 0, indent)
