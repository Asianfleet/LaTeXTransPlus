"""为表格单元格提供与侧栏一致的全文悬浮提示。"""

from __future__ import annotations

from rich.text import Text
from textual import events
from textual.widgets import DataTable, Tooltip


class CellTooltipTable(DataTable):
    """根据鼠标所在单元格显示已注册的原始文本。"""

    def __init__(self, *args: object, **kwargs: object) -> None:
        """初始化单元格全文索引。"""
        super().__init__(*args, **kwargs)
        self._cell_tooltips: dict[tuple[int, int], str] = {}
        self._wide_tooltip_cells: set[tuple[int, int]] = set()

    def set_cell_tooltip(
        self, row: int, column: int, text: str, *, wide: bool = False
    ) -> None:
        """注册单元格全文，可为长段落启用宽弹层，空文本不显示提示。"""
        self._cell_tooltips[row, column] = text
        if wide:
            self._wide_tooltip_cells.add((row, column))
        else:
            self._wide_tooltip_cells.discard((row, column))

    def clear(self, columns: bool = False) -> CellTooltipTable:
        """清空表格时同步移除全文索引与当前提示。"""
        self._cell_tooltips.clear()
        self._wide_tooltip_cells.clear()
        self.tooltip = None
        super().clear(columns=columns)
        return self

    def on_mouse_move(self, event: events.MouseMove) -> None:
        """使用渲染单元格元数据定位内容，兼容滚动及列宽变化。"""
        meta = event.style.meta
        text = None
        cell = (meta.get("row", -1), meta.get("column", -1))
        if not meta.get("out_of_bounds", False):
            text = self._cell_tooltips.get(cell)
        for tooltip in self.screen.query(Tooltip):
            tooltip.styles.max_width = "80vw" if text and cell in self._wide_tooltip_cells else None
            # 长弹层被边界挤回鼠标位置会触发 Leave，预留上下边距以避免遮住鼠标。
            mouse_y = event.screen_y
            tooltip.styles.max_height = max(
                1, mouse_y - 2, self.screen.size.height - mouse_y - 3
            )
        self.tooltip = Text(text) if text else None

    def on_leave(self, event: events.Leave) -> None:
        """鼠标离开表格时移除悬浮提示。"""
        self.tooltip = None
        for tooltip in self.screen.query(Tooltip):
            tooltip.styles.max_height = None
            tooltip.styles.max_width = None
