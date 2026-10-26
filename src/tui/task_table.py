"""项目管理表的列定义与稳定排序。"""

from __future__ import annotations

import unicodedata
from collections.abc import Sequence, Set

from src.tui.project_list import ProjectStateRow


TASK_TABLE_COLUMNS = ("选中", "项目", "标题", "翻译模型", "状态", "任务 id")
TASK_ID_COLUMN = 5


def sort_task_table_rows(
    rows: Sequence[ProjectStateRow],
    column: int,
    descending: bool,
    selected_keys: Set[tuple[str, str]],
) -> list[ProjectStateRow]:
    """按所选列稳定排序，直接使用完整状态值而非截断后的单元格。"""
    def sort_key(row: ProjectStateRow) -> bool | str:
        """将当前列映射为可比较值，文本统一 Unicode 并忽略大小写。"""
        task, project = row
        if column == 0:
            return (task.task_id, project.project_name) in selected_keys
        value = (
            project.project_name,
            project.title or "未识别标题",
            project.translation_model or "unknown",
            project.status_label,
            task.task_id,
        )[column - 1]
        return unicodedata.normalize("NFKC", value).casefold()

    return sorted(rows, key=sort_key, reverse=descending)
