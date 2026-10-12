"""为表格单元格提供与侧栏一致的全文悬浮提示。"""

from __future__ import annotations

from rich.text import Text
from textual import events
from textual.widgets import DataTable


class CellTooltipTable(DataTable):
    """根据鼠标所在单元格显示已注册的原始文本。"""

    def __init__(self, *args: object, **kwargs: object) -> None:
        """初始化单元格全文索引。"""
        super().__init__(*args, **kwargs)
        self._cell_tooltips: dict[tuple[int, int], str] = {}

    def set_cell_tooltip(self, row: int, column: int, text: str) -> None:
        """注册单元格全文，空文本不显示提示。"""
        self._cell_tooltips[row, column] = text

    def clear(self, columns: bool = False) -> CellTooltipTable:
        """清空表格时同步移除全文索引与当前提示。"""
        self._cell_tooltips.clear()
        self.tooltip = None
        super().clear(columns=columns)
        return self

    def on_mouse_move(self, event: events.MouseMove) -> None:
        """使用渲染单元格元数据定位内容，兼容滚动及列宽变化。"""
        meta = event.style.meta
        text = None
        if not meta.get("out_of_bounds", False):
            text = self._cell_tooltips.get((meta.get("row", -1), meta.get("column", -1)))
        self.tooltip = Text(text) if text else None

    def on_leave(self, event: events.Leave) -> None:
        """鼠标离开表格时移除悬浮提示。"""
        self.tooltip = None
