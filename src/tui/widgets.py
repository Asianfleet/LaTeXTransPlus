"""TUI 可复用控件与响应式标题。"""

from __future__ import annotations

from rich.cells import cell_len
from rich.text import Text
from textual import events
from textual.binding import Binding
from textual.coordinate import Coordinate
from textual.css.query import NoMatches
from textual.message import Message
from textual.widgets import DataTable, Input, Static, TabbedContent, TextArea

from src.engines.base import normalize_engine

APP_TITLE_PLAIN = "LaTeXTransPlus"
APP_TITLE_ART = "\n".join(
    (
        "  ██╗      █████╗ ████████╗███████╗██╗  ██╗████████╗██████╗  █████╗ ███╗   ██╗███████╗      ██╗",
        "  ██║     ██╔══██╗╚══██╔══╝██╔════╝╚██╗██╔╝╚══██╔══╝██╔══██╗██╔══██╗████╗  ██║██╔════╝    ██████╗",
        "  ██║     ███████║   ██║   █████╗   ╚███╔╝    ██║   ██████╔╝███████║██╔██╗ ██║███████╗    ╚═██╔═╝",
        "  ██║     ██╔══██║   ██║   ██╔══╝   ██╔██╗    ██║   ██╔══██╗██╔══██║██║╚██╗██║╚════██║      ╚═╝",
        "  ███████╗██║  ██║   ██║   ███████╗██╔╝ ██╗   ██║   ██║  ██║██║  ██║██║ ╚████║███████║",
        "  ╚══════╝╚═╝  ╚═╝   ╚═╝   ╚══════╝╚═╝  ╚═╝   ╚═╝   ╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═══╝╚══════╝",
    )
)
APP_TITLE_ART_COMPACT = "\n".join(
    (
        "  ██╗      █████╗ ████████╗███████╗██╗  ██╗████████╗      ██╗",
        "  ██║     ██╔══██╗╚══██╔══╝██╔════╝╚██╗██╔╝╚══██╔══╝    ██████╗",
        "  ██║     ███████║   ██║   █████╗   ╚███╔╝    ██║       ╚═██╔═╝",
        "  ██║     ██╔══██║   ██║   ██╔══╝   ██╔██╗    ██║         ╚═╝",
        "  ███████╗██║  ██║   ██║   ███████╗██╔╝ ██╗   ██║",
        "  ╚══════╝╚═╝  ╚═╝   ╚═╝   ╚══════╝╚═╝  ╚═╝   ╚═╝",
    )
)
APP_TITLE_LINE_STYLES = (
    "bold bright_white",
    "bold #dbeafe",
    "bold #93c5fd",
    "bold #60a5fa",
    "bold #3b82f6",
    "bold #1d4ed8",
)
APP_TITLE_LITE_LINE_STYLES = (
    "bold bright_white",
    "bold #e5e7eb",
    "bold #d1d5db",
    "bold #9ca3af",
    "bold #6b7280",
    "bold #4b5563",
)


def app_title_art_width(art: str) -> int:
    """计算艺术字标题的最大终端显示宽度。"""
    return max(cell_len(line) for line in art.splitlines())


def build_art_title(art: str, line_styles: tuple[str, ...] = APP_TITLE_LINE_STYLES) -> Text:
    """用入口页标题样式构建指定艺术字文本。"""
    title = Text()
    for index, line in enumerate(art.splitlines()):
        if index:
            title.append("\n")
        title.append(line, style=line_styles[index])
    return title


def build_app_title(engine: str = "heavy") -> Text:
    """构建入口页宽屏蓝白色多行艺术字标题。"""
    return build_art_title(APP_TITLE_ART, _title_line_styles(engine))


def build_app_title_for_width(width: int, engine: str = "heavy") -> Text:
    """根据可用宽度构建入口页标题，避免艺术字被终端换行错位。"""
    if width >= app_title_art_width(APP_TITLE_ART):
        return build_art_title(APP_TITLE_ART, _title_line_styles(engine))
    if width >= app_title_art_width(APP_TITLE_ART_COMPACT):
        return build_art_title(APP_TITLE_ART_COMPACT, _title_line_styles(engine))
    return Text(APP_TITLE_PLAIN, style=_title_line_styles(engine)[2])


def _title_line_styles(engine: str) -> tuple[str, ...]:
    """返回已校验 TUI 引擎对应的标题色板。"""
    return APP_TITLE_LITE_LINE_STYLES if normalize_engine(engine) == "lite" else APP_TITLE_LINE_STYLES


class ResponsiveAppTitle(Static):
    """入口页标题控件，根据自身宽度切换宽版、窄版和普通标题。"""

    def __init__(self, *args: object, **kwargs: object) -> None:
        """初始化时先使用普通标题，等待布局完成后再按实际宽度刷新。"""
        super().__init__(build_app_title_for_width(0), *args, **kwargs)
        self._engine = "heavy"

    def set_engine(self, engine: str) -> None:
        """应用所选引擎的标题色板，同时保持现有布局。"""
        self._engine = normalize_engine(engine)
        self._refresh_for_width(self.size.width)

    def on_mount(self) -> None:
        """控件挂载后按当前宽度刷新标题。"""
        self._refresh_for_width(self.size.width)

    def on_resize(self, event: events.Resize) -> None:
        """控件尺寸变化时按新的可绘制宽度刷新标题。"""
        self._refresh_for_width(event.size.width)

    def _refresh_for_width(self, width: int) -> None:
        """按给定宽度更新标题内容。"""
        next_title = build_app_title_for_width(width, self._engine)
        if self.content == next_title:
            return
        self.update(next_title, layout=False)


class ErrorReportsTable(DataTable):
    """错误记录表，尺寸变化时按新的可视宽度重新生成列。"""

    class ResizeRequested(Message):
        """请求所属详情组件按当前可视宽度重新生成列。"""

        def __init__(self) -> None:
            """创建不携带额外载荷的尺寸更新请求。"""
            super().__init__()

    def on_resize(self, event: events.Resize) -> None:
        """表格尺寸变化时重新分配错误记录列宽。"""
        if self.columns:
            self.post_message(self.ResizeRequested())


class ProjectManagementTable(DataTable):
    """项目管理表，单击数据行即可切换项目选择状态。"""

    def __init__(self, *args: object, **kwargs: object) -> None:
        """初始化项目表的行选择抑制状态。"""
        super().__init__(*args, **kwargs)
        self._suppress_next_row_selected = False

    def on_resize(self, event: events.Resize) -> None:
        """尺寸变化后重新分配标题空间，保持选中状态及游标位置。"""
        if self.columns:
            self.app.call_after_refresh(self.app.refresh_task_table)

    def on_mouse_down(self, event: events.MouseDown) -> None:
        """在鼠标按下时切换项目行，并抑制后续重复行事件。"""
        if self._toggle_clicked_row(event):
            self._suppress_next_row_selected = True
            event.stop()

    def _toggle_clicked_row(self, event: events.MouseEvent) -> bool:
        """根据点击事件切换项目行，返回是否成功处理。"""
        meta = event.style.meta or {}
        has_cell_meta = "row" in meta and "column" in meta
        row_index = int(meta["row"]) if has_cell_meta else self._row_index_from_click(event)
        column_index = int(meta["column"]) if has_cell_meta else 0
        if not meta.get("out_of_bounds", False) and 0 <= row_index < self.row_count and column_index >= 0:
            self.cursor_coordinate = Coordinate(row_index, column_index)
            app = self.app
            if hasattr(app, "_toggle_project_selection"):
                app._toggle_project_selection(row_index)
            self._scroll_cursor_into_view(animate=True)
            return True
        return False

    def _row_index_from_click(self, event: events.MouseEvent) -> int:
        """从 Textual 鼠标坐标推导项目表行索引。"""
        row_index = int(event.y) - self.header_height
        if 0 <= row_index < self.row_count or event.screen_y is None:
            return row_index
        return int(event.screen_y - self.region.y) - self.header_height


class ZoteroResultsTable(DataTable):
    """Zotero 搜索结果表，单击数据行即可切换选中状态。"""

    class SelectionRequested(Message):
        """请求所属面板切换指定结果行。"""

        def __init__(self, row_index: int) -> None:
            """保存需要切换的结果行索引。"""
            super().__init__()
            self.row_index = row_index

    class ResizeRequested(Message):
        """请求所属面板按当前表格宽度重新分配列宽。"""

        def __init__(self) -> None:
            """创建不携带额外载荷的尺寸更新请求。"""
            super().__init__()

    def __init__(self, *args: object, **kwargs: object) -> None:
        """初始化 Zotero 表格的鼠标点击防抖状态。"""
        super().__init__(*args, **kwargs)
        self._ignore_next_click = False
        self._suppress_next_row_selected = False

    def on_mouse_down(self, event: events.MouseDown) -> None:
        """在鼠标按下时立即切换数据行，保证单击即可选中。"""
        if self._toggle_clicked_row(event):
            self._ignore_next_click = True
            event.stop()

    def on_resize(self, event: events.Resize) -> None:
        """表格尺寸变化时重新收紧列宽，避免出现水平滚动。"""
        if self.columns:
            self.post_message(self.ResizeRequested())

    def on_click(self, event: events.Click) -> None:
        """把数据行单击解释为 Zotero 条目选择，并保留非数据区默认行为。"""
        if self._ignore_next_click:
            self._ignore_next_click = False
            event.stop()
            return
        if self._toggle_clicked_row(event):
            event.stop()

    async def _on_click(self, event: events.Click) -> None:
        """在默认 DataTable 处理前拦截 Zotero 数据行点击。"""
        if self._ignore_next_click:
            self._ignore_next_click = False
            event.stop()
            return
        if self._toggle_clicked_row(event):
            event.stop()
            return
        await super()._on_click(event)

    def _toggle_clicked_row(self, event: events.MouseEvent) -> bool:
        """根据点击事件切换对应 Zotero 数据行，返回是否已处理。"""
        meta = event.style.meta or {}
        has_cell_meta = "row" in meta and "column" in meta
        row_index = int(meta["row"]) if has_cell_meta else self._row_index_from_click(event)
        column_index = int(meta["column"]) if has_cell_meta else 0
        if not meta.get("out_of_bounds", False):
            if 0 <= row_index < self.row_count and column_index >= 0:
                self._suppress_next_row_selected = True
                self.cursor_coordinate = Coordinate(row_index, column_index)
                self.post_message(self.SelectionRequested(row_index))
                self._scroll_cursor_into_view(animate=True)
                return True
        return False

    def _row_index_from_click(self, event: events.MouseEvent) -> int:
        """从 Textual 鼠标事件坐标推导数据行索引。"""
        row_index = int(event.y) - self.header_height
        if 0 <= row_index < self.row_count or event.screen_y is None:
            return row_index
        return int(event.screen_y - self.region.y) - self.header_height


class EntryBatchTextArea(TextArea):
    """入口页批量输入框，负责把 Enter 解释为提交任务。"""

    BINDINGS = [
        *TextArea.BINDINGS,
        Binding("enter", "submit_entry", "发送", priority=True),
    ]

    def action_submit_entry(self) -> None:
        """提交入口页表单，不在输入框中插入换行。"""
        app = self.app
        if hasattr(app, "submit_entry_form"):
            app.submit_entry_form()


class ZoteroSearchInput(Input):
    """Zotero 搜索输入框，负责把 Enter 解释为搜索。"""

    class SearchRequested(Message):
        """请求所属面板使用当前输入内容执行搜索。"""

        def __init__(self) -> None:
            """创建不携带额外载荷的搜索请求。"""
            super().__init__()

    BINDINGS = [
        *Input.BINDINGS,
        Binding("enter", "submit_search", "搜索", priority=True),
    ]

    def action_submit_search(self) -> None:
        """提交当前 Zotero 搜索词。"""
        self.post_message(self.SearchRequested())


class ConfigTabbedContent(TabbedContent):
    """设置页 tab 容器，提供只在设置上下文显示的 tab 快捷键。"""

    BINDINGS = [
        Binding("c", "show_tab('config-form-tab')", "配置"),
        Binding("p", "show_tab('config-preview-tab')", "预览"),
    ]

    def action_show_tab(self, tab_id: str) -> None:
        """切换到指定设置 tab。"""
        self.active = tab_id


class DetailTabbedContent(TabbedContent):
    """项目详情 tab 容器，提供只在详情上下文显示的 tab 快捷键。"""

    BINDINGS = [
        Binding("t", "show_tab('tex-tab')", "TeX"),
        Binding("r", "show_tab('terms-tab')", "术语"),
        Binding("e", "show_tab('errors-tab')", "错误"),
        Binding("l", "show_tab('log-tab')", "日志"),
        Binding("z", "show_tab('zotero-tab')", "Zotero"),
    ]

    def action_show_tab(self, tab_id: str) -> None:
        """切换到指定项目详情 tab。"""
        try:
            tab = self.get_tab(tab_id)
        except (NoMatches, ValueError):
            return
        if not tab.has_class("-hidden"):
            self.active = tab_id
