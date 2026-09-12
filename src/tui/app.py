"""Textual terminal UI entry point."""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Literal, Sequence

import toml
from rich.cells import cell_len
from rich.text import Text
from rich.syntax import Syntax
from textual import events, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.coordinate import Coordinate
from textual.css.query import NoMatches
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widget import Widget
from textual.widgets import (
    Button,
    ContentSwitcher,
    DataTable,
    Footer,
    Input,
    ListItem,
    ListView,
    RichLog,
    Rule,
    Select,
    Static,
    Switch,
    TabPane,
    TabbedContent,
    TextArea,
)

from src.tui.config import UI_CONFIG_PATH, load_ui_config, save_ui_config
from src.tui.config_schema import (
    ConfigField,
    bool_for_field,
    config_fields_for_engine,
    form_text_for_field,
    grouped_config_fields,
    normalized_config_from_form,
    parse_integer_value,
    parse_textarea_value,
    select_value_for_field,
)
from src.engines.base import normalize_engine
from src.tui.history import load_output_history, write_project_metadata
from src.tui.input_parser import (
    parse_input_items,
    validate_input_items,
    validate_lite_input,
)
from src.tui.process_runner import (
    TuiTaskProcess,
    drain_process_messages,
    start_tui_task_process,
    terminate_tui_task_process,
)
from src.tui.runner import run_tui_task as _DEFAULT_RUN_TUI_TASK
from src.tui.runner import run_tui_task
from src.tui.state import ProjectStatus, ProjectViewState, TaskViewState
from src.tui.zotero_adapter import ZoteroAdapter

PAGE_ENTRY = "entry"
PAGE_DETAIL = "detail"
PAGE_TASKS = "tasks"
PAGE_CONFIG = "config"
ZOTERO_SELECTION_COLUMN_WIDTH = 4
ZOTERO_MIN_TITLE_COLUMN_WIDTH = 20
ZOTERO_MIN_LIBRARY_COLUMN_WIDTH = 10
ZOTERO_MAX_LIBRARY_COLUMN_WIDTH = 18
ZOTERO_MIN_COLLECTION_COLUMN_WIDTH = 12
ZOTERO_MAX_COLLECTION_COLUMN_WIDTH = 24
ERROR_POSITION_COLUMN_WIDTH = 10
ERROR_TYPE_COLUMN_WIDTH = 5
ERROR_PROBLEM_COLUMN_WIDTH = 24
ERROR_STATUS_COLUMN_WIDTH = 8
ERROR_MIN_CONTENT_COLUMN_WIDTH = 6
PROGRESS_LOG_LINE_RE = re.compile(r"^\[[#-]+\]\s+\d{1,3}(?:\.\d+)?%")
APP_TITLE_PLAIN = "LaTeXTransPlus"
NOTIFY_MESSAGE_LIMIT = 400
NOTIFICATION_SEVERITY = Literal["information", "warning", "error"]


def _compact_notification(message: str, limit: int = NOTIFY_MESSAGE_LIMIT) -> str:
    """把通知文本压成单段可读文本，过长时保留开头并加省略号。"""
    collapsed = " ".join(str(message).split())
    if len(collapsed) <= limit:
        return collapsed
    return f"{collapsed[:limit]} …"


def _merge_project_log_text(file_text: str, memory_lines: list[str]) -> str:
    """合并日志文件与尚未落盘的准备阶段日志，并保持准备日志在前。"""
    file_lines = file_text.splitlines()
    file_line_set = set(file_lines)
    pending_lines = [line for line in memory_lines if line and line not in file_line_set]
    return "\n".join(pending_lines + file_lines)


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
    """Return the title palette for one validated TUI engine."""
    return APP_TITLE_LITE_LINE_STYLES if normalize_engine(engine) == "lite" else APP_TITLE_LINE_STYLES


class ResponsiveAppTitle(Static):
    """入口页标题控件，根据自身宽度切换宽版、窄版和普通标题。"""

    def __init__(self, *args: object, **kwargs: object) -> None:
        """初始化时先使用普通标题，等待布局完成后再按实际宽度刷新。"""
        super().__init__(build_app_title_for_width(0), *args, **kwargs)
        self._engine = "heavy"

    def set_engine(self, engine: str) -> None:
        """Apply the selected engine's title palette without changing layout."""
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


def compact_progress_log_for_display(log_text: str) -> str:
    """压缩连续进度日志块，展示时只保留首行、中间行和末行。"""
    displayed_lines: list[str] = []
    progress_block: list[str] = []

    def flush_progress_block() -> None:
        """将当前连续进度块按展示规则写入输出行。"""
        if not progress_block:
            return
        if len(progress_block) <= 3:
            displayed_lines.extend(progress_block)
        else:
            middle_index = len(progress_block) // 2
            displayed_lines.extend(
                [
                    progress_block[0],
                    progress_block[middle_index],
                    progress_block[-1],
                ]
            )
        progress_block.clear()

    for line in log_text.splitlines():
        stripped_line = line.rstrip()
        if PROGRESS_LOG_LINE_RE.match(stripped_line):
            progress_block.append(stripped_line)
            continue
        flush_progress_block()
        displayed_lines.append(stripped_line)

    flush_progress_block()
    return "\n".join(displayed_lines)


class ErrorReportsTable(DataTable):
    """错误记录表，尺寸变化时按新的可视宽度重新生成列。"""

    def on_resize(self, event: events.Resize) -> None:
        """表格尺寸变化时重新分配错误记录列宽。"""
        if self.columns:
            app = self.app
            if hasattr(app, "_refresh_selected_errors_table"):
                app.call_after_refresh(app._refresh_selected_errors_table)


class ProjectManagementTable(DataTable):
    """项目管理表，单击数据行即可切换项目选择状态。"""

    def __init__(self, *args: object, **kwargs: object) -> None:
        """初始化项目表的行选择抑制状态。"""
        super().__init__(*args, **kwargs)

        self._suppress_next_row_selected = False

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

    def __init__(self, *args: object, **kwargs: object) -> None:
        """初始化 Zotero 表格的鼠标点击防抖状态。"""
        super().__init__(*args, **kwargs)
        self._ignore_next_click = False

    def on_mouse_down(self, event: events.MouseDown) -> None:
        """在鼠标按下时立即切换数据行，保证单击即可选中。"""
        if self._toggle_clicked_row(event):
            self._ignore_next_click = True
            event.stop()

    def on_resize(self, event: events.Resize) -> None:
        """表格尺寸变化时重新收紧列宽，避免出现水平滚动。"""
        if self.columns:
            app = self.app
            if hasattr(app, "_fit_zotero_results_table_columns"):
                app._fit_zotero_results_table_columns()

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
        if self._toggle_clicked_row(event):
            event.stop()
            return
        await super()._on_click(event)

    def _toggle_clicked_row(self, event: events.MouseEvent) -> bool:
        """根据点击事件切换对应 Zotero 数据行，返回是否已处理。"""
        meta = event.style.meta
        has_cell_meta = "row" in meta and "column" in meta
        row_index = int(meta["row"]) if has_cell_meta else self._row_index_from_click(event)
        column_index = int(meta["column"]) if has_cell_meta else 0
        if not meta.get("out_of_bounds", False):
            if 0 <= row_index < self.row_count and column_index >= 0:
                self.cursor_coordinate = Coordinate(row_index, column_index)
                app = self.app
                if hasattr(app, "toggle_zotero_row_selection"):
                    app.toggle_zotero_row_selection(row_index)
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

    BINDINGS = [
        *Input.BINDINGS,
        Binding("enter", "submit_search", "搜索", priority=True),
    ]

    def action_submit_search(self) -> None:
        """提交当前 Zotero 搜索词。"""
        app = self.app
        if hasattr(app, "search_zotero_items"):
            app.search_zotero_items()


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


class LaTeXTransTuiApp(App[None]):
    """Main Textual application for LaTeXTransPlus."""

    DEFAULT_CSS = """

    #sidebar {
        width: 1fr;
        padding: 0 1 0 1;
    }

    #sidebar Button {
        width: 100%;
        height: auto;
    }

    #project-list {
        background: transparent;
        padding: 0;
        scrollbar-size: 1 1;
    }

    #sidebar-rule {
        margin: 0;
        padding: 0;
    }

    #project-list ListItem:hover {
        background: $surface;
    }

    .running-task-project {
        color: orange;
    }

    #main-switcher {
        width: 4fr;
    }

    #config,
    #tasks,
    #detail {
        padding-top: 1;
    }

    #config,
    #config-tabs,
    #config-form-tab,
    #config-preview-tab {
        height: 1fr;
    }

    #project-actions {
        height: auto;
        margin-bottom: 1;
    }

    #project-actions Button {
        width: auto;
        margin-right: 1;
    }

    #tex-preview-scroll {
        height: 1fr;
    }

    #source-markdown-preview-scroll,
    #translated-markdown-preview-scroll {
        height: 1fr;
    }

    #tex-preview {
        width: 100%;
    }

    #source-markdown-preview,
    #translated-markdown-preview {
        width: 100%;
    }

    #log-tab,
    #project-log {
        height: 1fr;
    }

    #terms-table,
    #errors-table {
        height: 1fr;
    }

    #entry {
        align: center top;
        padding-top: 0;
    }

    #entry-form {
        width: 100%;
        min-width: 50;
        max-width: 124;
        height: 100%;
        align-horizontal: center;
    }

    #entry-top-spacer,
    #entry-bottom-spacer {
        height: 1fr;
    }

    #entry-bottom-offset {
        height: 3;
    }

    #app-title {
        width: 100%;
        height: 6;
        content-align: center middle;
        text-style: bold;
        margin: 0 0 2 0;
    }

    #batch-input {
        width: 1fr;
        height: 3;
        margin: 0;
    }

    #entry-actions {
        width: 100%;
        height: 3;
        padding: 0 4;
    }

    #engine-mode-control {
        height: 3;
        margin-top: 1;
        padding: 0 4;
        align-horizontal: left;
    }

    #engine-mode-label {
        width: auto;
        padding: 1 0 0 1;
    }

    #input-type-select {
        width: 22;
    }

    #start-task-button {
        width: 10;
        min-width: 10;
        height: 3;
        border: tall $border-blurred;
    }

    #start-task-button:hover,
    #start-task-button:focus {
        border: tall $border;
    }

    #entry-error {
        width: 100%;
        margin: 1 0 0 0;
    }

    #config-form {
        height: 1fr;
        padding: 1 2;
    }

    #config-fields {
        height: auto;
    }

    #config-preview {
        height: 1fr;
    }

    .config-section-title {
        text-style: bold;
        margin: 1 0 0 0;
    }

    .config-field-row {
        height: auto;
        margin: 0 0 1 0;
    }

    .config-field-label {
        width: 24;
        padding: 1 1 0 0;
    }

    .config-field-row Input,
    .config-field-row Select {
        width: 1fr;
    }

    .config-field-row TextArea {
        width: 1fr;
        height: 5;
    }

    #zotero-controls {
        width: 100%;
        height: 3;
        margin-bottom: 1;
    }

    #zotero-library-select {
        width: 16;
        height: 3;
    }

    #zotero-search-input {
        width: 1fr;
        min-width: 24;
        height: 3;
    }

    #zotero-search-button,
    #import-zotero-button,
    #import-zotero-markdown-button {
        width: 8;
        min-width: 8;
        height: 3;
        border: tall $border-blurred;
    }

    #zotero-auto-match-button {
        width: 14;
        min-width: 14;
        height: 3;
        border: tall $border-blurred;
    }

    #zotero-search-button:hover,
    #zotero-search-button:focus,
    #zotero-auto-match-button:hover,
    #zotero-auto-match-button:focus,
    #import-zotero-button:hover,
    #import-zotero-button:focus,
    #import-zotero-markdown-button:hover,
    #import-zotero-markdown-button:focus {
        border: tall $border;
    }

    #import-zotero-markdown-button {
        width: 14;
        min-width: 14;
    }

    #zotero-import-rule {
        width: 1;
        height: 3;
        margin: 0 1;
    }

    #zotero-results {
        height: 1fr;
    }
    """

    current_task: TaskViewState | None = None
    tasks: list[TaskViewState]
    selected_project_name: str | None = None
    selected_task_id: str | None = None
    selected_project_keys: set[tuple[str, str]]
    zotero_adapter_factory = staticmethod(
        lambda api_key, local_api_base: ZoteroAdapter(
            api_key=api_key,
            local_api_base=local_api_base,
        )
    )

    BINDINGS = [
        ("q", "quit", "退出"),
        ("n", "new_task", "新建任务"),
        ("m", "project_manager", "项目管理"),
        ("s", "settings", "设置"),
    ]

    def __init__(self, load_history_on_mount: bool = True, initial_engine: str = "heavy") -> None:
        """Initialize in-memory task history for the terminal UI."""
        super().__init__()
        self.effective_engine = normalize_engine(initial_engine)
        self.current_task = None
        self.tasks = []
        self.selected_project_name = None
        self.selected_task_id = None
        self.selected_project_keys = set()
        self.load_history_on_mount = load_history_on_mount
        self.current_config: dict[str, object] = {}
        self.loading_config_form = True
        self.zotero_libraries: list[dict[str, object]] = []
        self.zotero_results: list[dict[str, object]] = []
        self.zotero_selected_keys: set[str] = set()
        self.task_processes: dict[str, TuiTaskProcess] = {}
        self.cancelled_task_ids: set[str] = set()

    def compose(self) -> ComposeResult:
        """Compose the persistent sidebar, content switcher, and footer."""
        with Horizontal(id="app-body"):
            with Vertical(id="sidebar"):
                yield Button("新建任务", id="new-task-button", flat=True)
                yield Button("项目管理", id="project-manager-button", flat=True)
                yield ListView(id="project-list")
                yield Button("设置", id="settings-button", flat=True)
            yield Rule(orientation="vertical", id="sidebar-rule")
            with ContentSwitcher(initial=PAGE_ENTRY, id="main-switcher"):
                with Vertical(id=PAGE_ENTRY):
                    with Vertical(id="entry-form"):
                        yield Static("", id="entry-top-spacer")
                        yield ResponsiveAppTitle(id="app-title")
                        with Horizontal(id="entry-actions"):
                            yield Select(
                                self._entry_input_options(),
                                id="input-type-select",
                                value=self._entry_input_type(),
                            )
                            yield EntryBatchTextArea(id="batch-input")
                            yield Button("发送", id="start-task-button", flat=True)
                        with Horizontal(id="engine-mode-control"):
                            yield Switch(
                                self.effective_engine == "lite",
                                id="engine-mode-switch",
                            )
                            yield Static("Lite 引擎", id="engine-mode-label")
                        yield Static("", id="entry-error")
                        yield Static("", id="entry-bottom-offset")
                        yield Static("", id="entry-bottom-spacer")
                with Vertical(id=PAGE_DETAIL):
                    with DetailTabbedContent(initial="tex-tab", id="detail-tabs"):
                        with TabPane("TeX", id="tex-tab"):
                            with VerticalScroll(id="tex-preview-scroll"):
                                yield Static("", id="tex-preview")
                        with TabPane("源 Markdown", id="source-markdown-tab"):
                            with VerticalScroll(id="source-markdown-preview-scroll"):
                                yield Static("", id="source-markdown-preview")
                        with TabPane("译文 Markdown", id="translated-markdown-tab"):
                            with VerticalScroll(id="translated-markdown-preview-scroll"):
                                yield Static("", id="translated-markdown-preview")
                        with TabPane("术语表", id="terms-tab"):
                            yield DataTable(id="terms-table")
                        with TabPane("错误记录", id="errors-tab"):
                            yield ErrorReportsTable(id="errors-table")
                        with TabPane("日志", id="log-tab"):
                            yield RichLog(id="project-log")
                        with TabPane("Zotero", id="zotero-tab"):
                            with Horizontal(id="zotero-controls"):
                                yield Select([], id="zotero-library-select")
                                yield ZoteroSearchInput(id="zotero-search-input")
                                yield Button("搜索", id="zotero-search-button", flat=True)
                                yield Button("自动匹配", id="zotero-auto-match-button", flat=True)
                                yield Rule(orientation="vertical", id="zotero-import-rule")
                                yield Button("导入 PDF", id="import-zotero-button", flat=True)
                                yield Button("导入 Markdown", id="import-zotero-markdown-button", flat=True)
                            yield ZoteroResultsTable(id="zotero-results", cursor_type="row")
                with Vertical(id=PAGE_TASKS):
                    with Horizontal(id="project-actions"):
                        yield Button("终止翻译", id="terminate-translation-button", flat=True, disabled=True)
                        yield Button("删除", id="delete-project-button", flat=True, disabled=True)
                        yield Button("重新翻译", id="retry-translation-button", flat=True, disabled=True)
                    yield ProjectManagementTable(id="task-table", cursor_type="row")
                with Vertical(id=PAGE_CONFIG):
                    with ConfigTabbedContent(initial="config-form-tab", id="config-tabs"):
                        with TabPane("配置", id="config-form-tab"):
                            with VerticalScroll(id="config-form"):
                                with Vertical(id="config-fields"):
                                    yield from self._config_form_widgets()
                                yield Static("", id="config-error")
                        with TabPane("预览", id="config-preview-tab"):
                            preview = TextArea(id="config-preview", language="toml")
                            preview.read_only = True
                            yield preview
        yield Footer()

    def on_mount(self) -> None:
        """Load existing output projects into the sidebar when the app starts."""
        self._initialize_zotero_results_table()
        self._apply_engine_view(rebuild_config_form=False)
        self.call_after_refresh(self._enable_config_persistence)
        if not self.load_history_on_mount:
            return
        self.theme = "nord"
        self.load_output_history()

    def set_engine(self, engine: str, persist: bool = False) -> None:
        """Select the engine for this UI session and optionally save a future default."""
        self.effective_engine = normalize_engine(engine)
        if not self.is_mounted:
            return
        self._apply_engine_view(rebuild_config_form=True)
        if self.load_history_on_mount:
            self.load_output_history()
        if persist:
            config = dict(self.current_config) or load_ui_config(Path.cwd())
            config["engine"] = self.effective_engine
            save_ui_config(Path.cwd(), config)
            self.current_config = config

    def _apply_engine_view(self, rebuild_config_form: bool) -> None:
        """Synchronize visible TUI controls with the current session engine."""
        title = self.query_one("#app-title", ResponsiveAppTitle)
        title.set_engine(self.effective_engine)
        mode_switch = self.query_one("#engine-mode-switch", Switch)
        with self.prevent(Switch.Changed):
            mode_switch.value = self.effective_engine == "lite"
        self.query_one("#engine-mode-label", Static).update(
            "Lite 引擎" if self.effective_engine == "lite" else "Heavy 引擎"
        )

        input_type_select = self.query_one("#input-type-select", Select)
        input_type_select.set_options(self._entry_input_options())
        input_type_select.value = self._entry_input_type()
        self._refresh_detail_tabs()
        self._clear_incompatible_selected_project()
        if rebuild_config_form:
            self._rebuild_config_fields()
        self.refresh_project_list()
        self.refresh_task_table()
        self.refresh_detail_page()

    def _entry_input_options(self) -> list[tuple[str, str]]:
        """Return mode-specific input choices for the entry form."""
        if self.effective_engine == "lite":
            return [("自动识别", "pdf")]
        return [
            ("arXiv ID / URL", "arxiv"),
            ("本地项目/压缩包", "local"),
            ("远程压缩包 URL", "remote"),
        ]

    def _entry_input_type(self) -> str:
        """Return the current mode's sole default entry type."""
        return "pdf" if self.effective_engine == "lite" else "arxiv"

    def _refresh_detail_tabs(self) -> None:
        """Show only the current engine's compatible project-detail tabs."""
        tabs = self.query_one("#detail-tabs", DetailTabbedContent)
        visible_ids = (
            {"source-markdown-tab", "translated-markdown-tab", "terms-tab", "log-tab", "zotero-tab"}
            if self.effective_engine == "lite"
            else {"tex-tab", "terms-tab", "errors-tab", "log-tab", "zotero-tab"}
        )
        all_ids = {
            "tex-tab",
            "source-markdown-tab",
            "translated-markdown-tab",
            "terms-tab",
            "errors-tab",
            "log-tab",
            "zotero-tab",
        }
        for tab_id in all_ids:
            if tab_id in visible_ids:
                tabs.show_tab(tab_id)
            else:
                tabs.hide_tab(tab_id)
        preferred_tab = "source-markdown-tab" if self.effective_engine == "lite" else "tex-tab"
        if tabs.active not in visible_ids:
            tabs.active = preferred_tab

    def _clear_incompatible_selected_project(self) -> None:
        """Clear selection when a mode switch hides its task's project details."""
        if self.selected_task_id is None:
            return
        selected_task = next(
            (task for task in self.tasks if task.task_id == self.selected_task_id),
            None,
        )
        if selected_task is not None and selected_task.engine != self.effective_engine:
            self.selected_project_name = None
            self.selected_task_id = None
            self.clear_zotero_results()

    @work(group="config-form", exclusive=True)
    async def _rebuild_config_fields(self) -> None:
        """Replace and populate settings fields after their Textual mounts complete."""
        fields = self.query_one("#config-fields", Vertical)
        self.loading_config_form = True
        try:
            await fields.remove_children()
            await fields.mount(*self._config_form_widgets())
            self._populate_config_form(dict(self.current_config))
        except Exception:
            self.loading_config_form = False
            raise
        self.call_after_refresh(self._enable_config_persistence)

    def _enable_config_persistence(self) -> None:
        """Re-enable immediate settings persistence after a mode-driven rebuild."""
        self.loading_config_form = False

    def switch_page(self, page_id: str) -> None:
        """Switch the right-side content area to the given page."""
        self.query_one("#main-switcher", ContentSwitcher).current = page_id

    def load_output_history(self) -> None:
        """Load output directory history into task state and refresh project views."""
        history_tasks = load_output_history(
            self._history_output_root(),
            engine=self.effective_engine,
        )
        if not history_tasks:
            self.refresh_project_list()
            self.refresh_task_table()
            return

        self.tasks = self._merge_history_tasks(history_tasks, self.tasks)
        self.refresh_project_list()
        self.refresh_task_table()

    def select_project(self, project_name: str, task_id: str | None = None) -> None:
        """Select a project and open its read-only detail page."""
        if task_id is None:
            project_identity = next(
                (
                    (task.task_id, project.project_name)
                    for task, project in self._iter_project_states()
                    if project.project_name == project_name
                ),
                (None, project_name),
            )
            task_id = project_identity[0]
        self.selected_project_name = project_name
        self.selected_task_id = task_id
        self.clear_zotero_results()
        self.refresh_detail_page()
        self.switch_page(PAGE_DETAIL)

    def refresh_project_list(self) -> None:
        """Refresh the left-side project list from all known task states."""
        list_view = self.query_one("#project-list", ListView)
        list_view.clear()

        for task, project in self._iter_project_states():
            label = Static(project.project_name)
            if self._task_is_running(task):
                label.add_class("running-task-project")
            list_view.append(ListItem(label))

    def refresh_detail_page(self) -> None:
        """Refresh read-only detail widgets for the selected project."""
        project = self._selected_project()
        if project is None:
            return

        if project.engine == "lite":
            self._refresh_markdown_previews(project)
        else:
            self._refresh_tex_preview(project)
            self._refresh_errors_table(project)
        task_log_lines: list[str] | None = None
        for task, candidate in self._iter_project_states():
            if candidate is project:
                task_log_lines = task.task_log_lines
                break
        self._refresh_project_log(project, task_log_lines)
        self._refresh_terms_table(project)
        self._refresh_zotero_controls()

    def refresh_task_table(self) -> None:
        """Refresh the project management table from all known task states."""
        table = self.query_one("#task-table", ProjectManagementTable)
        project_states = self._iter_project_states()
        valid_keys = {(task.task_id, project.project_name) for task, project in project_states}
        self.selected_project_keys.intersection_update(valid_keys)
        table.clear(columns=True)
        table.add_columns("选中", "项目", "状态", "任务 id")

        for task, project in project_states:
            key = (task.task_id, project.project_name)
            table.add_row(
                "[√]" if key in self.selected_project_keys else "[]",
                project.project_name,
                project.status.value,
                task.task_id,
            )
        self._refresh_project_action_buttons()

    def _selected_project_states(self) -> list[tuple[TaskViewState, ProjectViewState]]:
        """返回当前选中的任务和项目状态。"""
        return [
            (task, project)
            for task, project in self._iter_project_states()
            if (task.task_id, project.project_name) in self.selected_project_keys
        ]

    def _toggle_project_selection(self, row_index: int) -> None:
        """切换项目管理表指定行的选择状态并刷新按钮。"""
        project_states = self._iter_project_states()
        if not 0 <= row_index < len(project_states):
            return
        task, project = project_states[row_index]
        key = (task.task_id, project.project_name)
        if key in self.selected_project_keys:
            self.selected_project_keys.remove(key)
        else:
            self.selected_project_keys.add(key)
        self.refresh_task_table()

    def _refresh_project_action_buttons(self) -> None:
        """根据全选项目状态更新终止、删除和重译按钮可用性。"""
        try:
            terminate = self.query_one("#terminate-translation-button", Button)
            delete = self.query_one("#delete-project-button", Button)
            retry = self.query_one("#retry-translation-button", Button)
        except NoMatches:
            return
        selected = self._selected_project_states()
        has_selection = bool(selected)
        all_running = has_selection and all(project.status == ProjectStatus.RUNNING for _, project in selected)
        all_stopped = has_selection and all(project.status != ProjectStatus.RUNNING for _, project in selected)
        lite_batch_retry = bool(selected) and selected[0][0].engine == "lite" and len(selected) > 1
        terminate.disabled = not all_running
        delete.disabled = not all_stopped
        retry.disabled = not all_stopped or lite_batch_retry

    def _terminate_selected_projects(self) -> None:
        """强制终止所有选中项目所属的翻译任务。"""
        selected = self._selected_project_states()
        if not selected:
            return
        task_ids = {task.task_id for task, _ in selected}
        for task_id in task_ids:
            self.terminate_task_process(task_id)

    def _delete_selected_projects(self) -> None:
        """删除所有选中的非运行项目及其输出目录和历史记录。"""
        selected = list(self._selected_project_states())
        if not selected:
            return

        removed_keys: set[tuple[str, str]] = set()
        for task, project in selected:
            if project.status == ProjectStatus.RUNNING:
                continue
            output_dir = Path(project.output_dir) if project.output_dir else None
            try:
                if output_dir is not None and output_dir.exists():
                    if not output_dir.is_dir():
                        raise OSError(f"输出路径不是目录：{output_dir}")
                    shutil.rmtree(output_dir)
            except OSError as exc:
                self._notify(
                    f"删除失败：{project.project_name}，错误：{exc}",
                    title="LaTeXTransPlus",
                    severity="error",
                )
                continue

            task.projects = [item for item in task.projects if item is not project]
            removed_keys.add((task.task_id, project.project_name))
            if self.selected_project_name == project.project_name and self.selected_task_id == task.task_id:
                self.selected_project_name = None
                self.selected_task_id = None

        self.selected_project_keys.difference_update(removed_keys)
        self.tasks = [task for task in self.tasks if task.projects]
        if self.current_task is not None and not self.current_task.projects:
            self.current_task = None
        self.refresh_project_list()
        self.refresh_task_table()

    def _retry_input_for_project(
        self,
        task: TaskViewState,
        project: ProjectViewState,
    ) -> tuple[str, str]:
        """解析项目重译所需的输入类型和原始输入项。"""
        input_type = str(task.input_type or "")
        if task.engine == "lite":
            return "pdf", str(task.inputs[0]) if task.inputs else project.project_name
        for item in task.inputs:
            candidate = str(item)
            if candidate == project.project_name or Path(candidate).name == project.project_name:
                if input_type in {"arxiv", "local", "remote"}:
                    return input_type, candidate

        # 批量任务通常按项目顺序保存输入；名称无法直接匹配时使用同序输入。
        try:
            project_index = task.projects.index(project)
        except ValueError:
            project_index = -1
        if 0 <= project_index < len(task.inputs) and len(task.inputs) == len(task.projects):
            if input_type in {"arxiv", "local", "remote"}:
                return input_type, str(task.inputs[project_index])

        project_dir = Path(project.project_dir) if project.project_dir else None
        if input_type not in {"arxiv", "local", "remote"} and project_dir is not None and project_dir.exists():
            return "local", str(project_dir)
        if input_type in {"local", "remote"} and len(task.projects) == 1 and task.inputs:
            return input_type, str(task.inputs[0])
        if input_type == "arxiv":
            return input_type, project.project_name
        if project_dir is not None and project_dir.exists():
            return "local", str(project_dir)
        return (input_type or "arxiv"), project.project_name

    def _retry_selected_projects(self) -> None:
        """将所有选中的非运行项目合并为一个新的翻译任务并启动。"""
        selected = list(self._selected_project_states())
        if not selected or any(project.status == ProjectStatus.RUNNING for _, project in selected):
            return

        retry_inputs: list[str] = []
        retry_type = ""
        for task, project in selected:
            input_type, input_item = self._retry_input_for_project(task, project)
            if not retry_type:
                retry_type = input_type
            if input_item not in retry_inputs:
                retry_inputs.append(input_item)
        if not retry_inputs:
            return

        retry_task = TaskViewState(
            input_type=retry_type or "arxiv",
            inputs=retry_inputs,
            task_id=self._next_task_id(),
            total=len(retry_inputs),
            engine=selected[0][0].engine,
        )
        self.current_task = retry_task
        self.tasks.append(retry_task)
        self.selected_project_keys.clear()
        self.refresh_project_list()
        self.refresh_task_table()
        self.start_current_task()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Handle sidebar project selection from the project list."""
        if event.list_view.id != "project-list":
            return
        project_states = list(self._iter_project_states())
        if 0 <= event.index < len(project_states):
            task, project = project_states[event.index]
            self.select_project(project.project_name, task.task_id)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """切换项目管理或 Zotero 结果行的选中状态。"""
        if event.data_table.id == "task-table":
            table = event.data_table
            if getattr(table, "_suppress_next_row_selected", False):
                table._suppress_next_row_selected = False
                return
            if event.cursor_row is not None:
                self._toggle_project_selection(event.cursor_row)
            return
        if event.data_table.id != "zotero-results":
            return
        row_index = event.cursor_row
        if row_index is not None:
            self.toggle_zotero_row_selection(row_index)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """处理主导航和任务入口按钮。"""
        if event.button.id == "start-task-button":
            self.submit_entry_form()
        elif event.button.id == "new-task-button":
            self.switch_page(PAGE_ENTRY)
        elif event.button.id in {"project-manager-button", "task-manager-button"}:
            self.switch_page(PAGE_TASKS)
        elif event.button.id == "settings-button":
            self.switch_page(PAGE_CONFIG)
            self.load_config_page()
        elif event.button.id == "zotero-search-button":
            self.search_zotero_items()
        elif event.button.id == "zotero-auto-match-button":
            self.auto_match_zotero_items()
        elif event.button.id == "import-zotero-button":
            self.import_selected_project_to_zotero()
        elif event.button.id == "import-zotero-markdown-button":
            self.import_selected_project_markdown_to_zotero()
        elif event.button.id == "terminate-translation-button":
            if hasattr(self, "_terminate_selected_projects"):
                self._terminate_selected_projects()
        elif event.button.id == "delete-project-button":
            if hasattr(self, "_delete_selected_projects"):
                self._delete_selected_projects()
        elif event.button.id == "retry-translation-button":
            if hasattr(self, "_retry_selected_projects"):
                self._retry_selected_projects()

    def on_input_changed(self, event: Input.Changed) -> None:
        """配置输入框变化时立即保存并刷新预览。"""
        if self._is_config_widget(event.input.id):
            self.persist_config_form_change()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """搜索框回车时触发 Zotero 搜索。"""
        if event.input.id == "zotero-search-input":
            self.search_zotero_items()

    def on_select_changed(self, event: Select.Changed) -> None:
        """配置下拉框变化时立即保存并刷新预览。"""
        if self._is_config_widget(event.select.id):
            self.persist_config_form_change()

    def on_switch_changed(self, event: Switch.Changed) -> None:
        """配置开关变化时立即保存并刷新预览。"""
        if event.switch.id == "engine-mode-switch":
            self.set_engine("lite" if event.value else "heavy")
            return
        if self._is_config_widget(event.switch.id):
            self.persist_config_form_change()

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        """配置多行文本变化时立即保存并刷新预览。"""
        if self._is_config_widget(event.text_area.id):
            self.persist_config_form_change()

    def on_tabbed_content_tab_activated(self, event: TabbedContent.TabActivated) -> None:
        """切到配置预览页时刷新未保存表单对应的 TOML。"""
        if event.tabbed_content.id == "config-tabs" and event.pane.id == "config-preview-tab":
            self.persist_config_form_change()
        elif event.tabbed_content.id == "detail-tabs" and event.pane.id == "errors-tab":
            self.call_after_refresh(self._refresh_selected_errors_table)
        elif event.tabbed_content.id == "detail-tabs" and event.pane.id == "zotero-tab":
            self.load_zotero_libraries()

    def load_config_page(self) -> None:
        """将 UI 配置加载到结构化表单和 TOML 预览区。"""
        config = load_ui_config(Path.cwd())
        self.current_config = dict(config)
        self.loading_config_form = True
        try:
            self._populate_config_form(config)
        finally:
            self.loading_config_form = False
        self._update_config_preview(config)
        self.query_one("#config-error", Static).update("")

    def persist_config_form_change(self) -> None:
        """从当前表单刷新 TOML 预览并立即保存 UI 配置。"""
        if self.loading_config_form:
            return
        try:
            config = self._config_from_form()
        except NoMatches:
            return
        except ValueError as exc:
            self.query_one("#config-error", Static).update(str(exc))
            return
        save_ui_config(Path.cwd(), config)
        self.current_config = dict(config)
        self._update_config_preview(config)
        self.query_one("#config-error", Static).update("")

    def _is_config_widget(self, widget_id: str | None) -> bool:
        """判断事件来源是否为设置页配置控件。"""
        return bool(widget_id and widget_id.startswith("config-") and widget_id != "config-preview")

    def _config_from_form(self) -> dict[str, object]:
        """将当前表单转换为完整配置对象。"""
        values = self._collect_config_form_values()
        return normalized_config_from_form(dict(self.current_config), values)

    def _compose_config_field(self, field: ConfigField) -> ComposeResult:
        """组合单个设置项的标签和编辑控件。"""
        yield self._config_field_row(field)

    def _config_form_widgets(self) -> list[Widget]:
        """Build settings section widgets for the current session engine."""
        widgets: list[Widget] = []
        for section, fields in grouped_config_fields(self.effective_engine):
            widgets.append(Static(section, classes="config-section-title"))
            widgets.extend(self._config_field_row(field) for field in fields)
        return widgets

    def _config_field_row(self, field: ConfigField) -> Horizontal:
        """Create one labeled configuration row from a schema field."""
        return Horizontal(
            Static(field.label, classes="config-field-label"),
            self._config_field_input(field),
            classes="config-field-row",
        )

    def _config_field_input(self, field: ConfigField) -> Widget:
        """Create the Textual input widget required by one configuration field."""
        if field.kind == "select":
            return Select(field.options, id=field.widget_id)
        if field.kind == "switch":
            return Switch(id=field.widget_id)
        if field.kind == "textarea":
            return TextArea(id=field.widget_id)
        return Input(id=field.widget_id)

    def _populate_config_form(self, config: dict[str, object]) -> None:
        """把配置值填入设置页表单控件。"""
        with self.prevent(Input.Changed, Select.Changed, Switch.Changed, TextArea.Changed):
            for field in config_fields_for_engine(self.effective_engine):
                if field.kind == "select":
                    self.query_one(f"#{field.widget_id}", Select).value = select_value_for_field(field, config)
                elif field.kind == "switch":
                    self.query_one(f"#{field.widget_id}", Switch).value = bool_for_field(field, config)
                elif field.kind == "textarea":
                    self.query_one(f"#{field.widget_id}", TextArea).text = form_text_for_field(field, config)
                else:
                    self.query_one(f"#{field.widget_id}", Input).value = form_text_for_field(field, config)

    def _collect_config_form_values(self) -> dict[tuple[str, ...], object]:
        """从设置页表单控件读取并校验配置值。"""
        values: dict[tuple[str, ...], object] = {}
        for field in config_fields_for_engine(self.effective_engine):
            if field.kind == "select":
                select = self.query_one(f"#{field.widget_id}", Select)
                values[field.path] = "" if select.is_blank() else str(select.value)
            elif field.kind == "switch":
                value = self.query_one(f"#{field.widget_id}", Switch).value
                values[field.path] = "True" if field.path == ("update_term",) and value else (
                    "False" if field.path == ("update_term",) else value
                )
            elif field.kind == "textarea":
                text = self.query_one(f"#{field.widget_id}", TextArea).text
                values[field.path] = parse_textarea_value(field, text)
            elif field.kind == "integer":
                text = self.query_one(f"#{field.widget_id}", Input).value
                values[field.path] = parse_integer_value(field, text)
            else:
                values[field.path] = self.query_one(f"#{field.widget_id}", Input).value
        return values

    def _update_config_preview(self, config: dict[str, object]) -> None:
        """刷新设置页 TOML 预览。"""
        self.query_one("#config-preview", TextArea).text = toml.dumps(config)

    def submit_entry_form(self) -> None:
        """校验入口页表单并创建任务视图状态。"""
        input_type_select = self.query_one("#input-type-select", Select)
        input_type = "" if input_type_select.is_blank() else str(input_type_select.value)
        input_text = self.query_one("#batch-input", TextArea).text
        if self.effective_engine == "lite":
            input_type = "pdf"
            items = [input_text.strip()] if input_text.strip() else []
            errors = validate_lite_input(input_text)
        else:
            items = parse_input_items(input_type, input_text)
            errors = validate_input_items(input_type, items)
        error_widget = self.query_one("#entry-error", Static)

        if not input_type or not items:
            error_widget.update("请选择输入类型并输入至少一个条目。")
            return
        if errors:
            error_widget.update("\n".join(errors))
            return

        error_widget.update("")
        self.current_task = TaskViewState(
            input_type=input_type,
            inputs=items,
            task_id=self._next_task_id(),
            engine=self.effective_engine,
        )
        self.tasks.append(self.current_task)
        self.query_one("#batch-input", TextArea).text = ""
        self.switch_page(PAGE_ENTRY)
        self._notify(
            f"任务已开始：{self.current_task.task_id}（{len(items)} 个条目）",
            title="LaTeXTransPlus",
        )
        self.start_current_task()

    def handle_runtime_event(self, event: dict[str, object], task: TaskViewState | None = None) -> None:
        """应用 runtime 事件并刷新任务相关视图。"""
        target_task = task or self.current_task
        known_tasks = self.tasks or ([self.current_task] if self.current_task is not None else [])
        if target_task is None or target_task not in known_tasks:
            return

        event_payload = dict(event)
        event_type = event_payload.get("type")
        if (
            target_task.task_id in self.cancelled_task_ids
            and event_type in {"project_complete", "project_error"}
        ):
            return
        target_task.apply_event(event_payload)
        if event_payload.get("type") in {"project_log", "task_log"}:
            self._refresh_selected_project_log(event_payload, target_task)
            return

        self._replace_history_project(target_task)
        self._persist_project_event(event_payload, target_task)
        self._notify_task_event(event_payload, target_task)
        self._refresh_selected_project_log(event_payload)
        self.refresh_project_list()
        self.refresh_task_table()
        if (
            event_type == "project_complete"
            and self.selected_project_name == str(event_payload.get("project_name") or "")
            and self.selected_task_id == target_task.task_id
        ):
            self.refresh_detail_page()

    def _refresh_selected_project_log(
        self,
        event: dict[str, object],
        task: TaskViewState | None = None,
    ) -> None:
        """如果日志事件属于当前详情项目，立即刷新日志控件。"""
        if event.get("type") not in {"project_log", "task_log"}:
            return
        project = self._selected_project()
        if project is None:
            return
        if event.get("type") == "task_log":
            if task is not None:
                self._refresh_project_log(project, task.task_log_lines)
            return
        if project.project_name == str(event.get("project_name") or ""):
            self._refresh_project_log(project, task.task_log_lines if task is not None else None)
            self._refresh_terms_table(project)

    def _notify(
        self,
        message: str,
        *,
        title: str = "LaTeXTransPlus",
        severity: NOTIFICATION_SEVERITY = "information",
    ) -> None:
        """发送通知：禁用 markup 解析并压缩超长文本。

        通知文本可能包含异常消息、命令列表或文件路径，其中的方括号会被
        Textual 当作 markup 标签解析并抛出 MarkupError，因此这里统一关闭
        markup 并限制长度。
        """
        self.notify(
            _compact_notification(message),
            title=title,
            severity=severity,
            markup=False,
        )

    def _notify_task_event(self, event: dict[str, object], task: TaskViewState) -> None:
        """根据任务事件发送轻量通知，不依赖已删除的进度页。"""
        event_type = event.get("type")
        project_name = str(event.get("project_name") or "project")
        if event_type == "project_complete":
            if self._should_notify_project_event(task, project_name, "project_complete"):
                pdf_error = str(event.get("pdf_error") or "").strip()
                if pdf_error:
                    self._notify(
                        f"项目完成（PDF 生成失败）：{project_name}，任务 id：{task.task_id}，原因：{pdf_error}",
                        severity="warning",
                    )
                else:
                    self._notify(
                        f"项目完成：{project_name}，任务 id：{task.task_id}",
                        title="LaTeXTransPlus",
                    )
        elif event_type == "project_error":
            if event.get("status") == "needs_term_review":
                if self._should_notify_project_event(task, project_name, "project_terms_ready"):
                    self._notify(f"术语表已生成：{project_name}，任务 id：{task.task_id}", title="LaTeXTransPlus")
            elif self._should_notify_project_event(task, project_name, "project_error"):
                error = self._project_error_message(event)
                self._notify(
                    f"发生异常：{project_name}，任务 id：{task.task_id}，错误：{error}",
                    title="LaTeXTransPlus",
                    severity="error",
                )

        if self._task_is_finished(task) and not task.completion_notified:
            task.completion_notified = True
            self._notify(f"任务全部完成：{task.task_id}", title="LaTeXTransPlus")

    def _project_error_message(self, event: dict[str, object]) -> str:
        """Return a useful project error message, including validation details when present."""
        explicit_error = str(event.get("error") or "").strip()
        if explicit_error:
            return explicit_error

        summary = event.get("validation_summary")
        if isinstance(summary, dict) and summary.get("errors", 0):
            errors = int(summary.get("errors", 0))
            warnings = int(summary.get("warnings", 0))
            report_path = str(event.get("errors_report_path") or "未提供")
            return (
                "Validation failed after retries; "
                f"remaining validation errors: {errors}, warnings: {warnings}. "
                f"Error report: {report_path}."
            )
        return "未知异常"

    def _should_notify_project_event(self, task: TaskViewState, project_name: str, event_type: str) -> bool:
        """返回项目终态事件是否尚未发过通知，并记录本次通知键。"""
        notify_key = (event_type, project_name)
        if notify_key in task.notified_project_events:
            return False
        task.notified_project_events.add(notify_key)
        return True

    def _notify_empty_task_failure(self, task: TaskViewState, error: str) -> None:
        """在没有可映射项目的任务失败时发出任务级异常和终态通知。"""
        self._notify(
            f"发生异常：{task.task_id}，错误：{error}",
            title="LaTeXTransPlus",
            severity="error",
        )
        if not task.completion_notified:
            task.completion_notified = True
            self._notify(f"任务全部完成：{task.task_id}", title="LaTeXTransPlus")

    def _selected_project(self) -> ProjectViewState | None:
        """Return the currently selected project state."""
        if self.selected_project_name is None:
            return None
        for task, project in self._iter_project_states():
            if self.selected_task_id is not None and task.task_id != self.selected_task_id:
                continue
            if project.project_name == self.selected_project_name:
                return project
        return None

    def _iter_project_states(self) -> list[tuple[TaskViewState, ProjectViewState]]:
        """Return project states flattened across known task history."""
        tasks = self.tasks
        if not tasks and self.current_task is not None:
            tasks = [self.current_task]
        return [
            (task, project)
            for task in tasks
            if task.engine == self.effective_engine
            for project in task.projects
        ]

    def _task_is_finished(self, task: TaskViewState) -> bool:
        """返回任务是否所有已知条目都已完成或失败。"""
        return task.total > 0 and self._stopped_project_count(task) >= task.total

    def _task_is_running(self, task: TaskViewState) -> bool:
        """返回任务是否仍有条目正在处理。"""
        if any(project.status == ProjectStatus.RUNNING for project in task.projects):
            return True
        return task.total > 0 and self._stopped_project_count(task) < task.total

    def _stopped_project_count(self, task: TaskViewState) -> int:
        """返回已离开后台处理状态的项目数量。"""
        stopped_statuses = {
            ProjectStatus.COMPLETED,
            ProjectStatus.FAILED,
            ProjectStatus.TERMS_READY,
            ProjectStatus.CANCELLED,
        }
        return sum(1 for project in task.projects if project.status in stopped_statuses)

    def _next_task_id(self) -> str:
        """Return the next stable task identifier for a submitted UI task."""
        return datetime.now().strftime("%Y%m%dT%H%M%S.%f")[:-3]

    def _history_output_root(self) -> Path:
        """Return the output root used for loading historical projects."""
        config = self.current_config or load_ui_config(Path.cwd())
        engine_config = config.get(self.effective_engine, {}) if isinstance(config, dict) else {}
        configured_output = (
            engine_config.get("output_dir")
            if isinstance(engine_config, dict)
            else None
        )
        if not configured_output and isinstance(config, dict):
            configured_output = config.get("output_dir")
        if not configured_output:
            configured_output = "output-lite" if self.effective_engine == "lite" else "outputs"
        return Path(str(configured_output))

    def _merge_history_tasks(
        self,
        history_tasks: list[TaskViewState],
        current_tasks: list[TaskViewState],
    ) -> list[TaskViewState]:
        """Merge historical tasks with current in-memory tasks by output directory."""
        merged = list(history_tasks)
        for task in current_tasks:
            for project in task.projects:
                if project.output_dir:
                    merged = [
                        history_task
                        for history_task in merged
                        if not any(
                            history_project.output_dir == project.output_dir
                            for history_project in history_task.projects
                        )
                    ]
            if task not in merged:
                merged.append(task)
        return merged

    def _replace_history_project(self, task: TaskViewState) -> None:
        """Remove stale historical rows whose output directory is now owned by this task."""
        output_dirs = {
            project.output_dir
            for project in task.projects
            if project.output_dir
        }
        if not output_dirs:
            return
        retained_tasks: list[TaskViewState] = []
        for existing_task in self.tasks:
            if existing_task is task:
                retained_tasks.append(existing_task)
                continue
            existing_task.projects = [
                project
                for project in existing_task.projects
                if project.output_dir not in output_dirs
            ]
            if existing_task.projects:
                retained_tasks.append(existing_task)
        if task not in retained_tasks:
            retained_tasks.append(task)
        self.tasks = retained_tasks

    def _persist_project_event(self, event: dict[str, object], task: TaskViewState) -> None:
        """Persist metadata for project events with an output directory."""
        event_type = event.get("type")
        if event_type not in {"project_start", "project_complete", "project_error", "project_cancelled"}:
            return
        output_dir = event.get("output_dir")
        project_name = str(event.get("project_name") or "")
        if not output_dir or not project_name:
            return
        project = next(
            (item for item in task.projects if item.project_name == project_name),
            None,
        )
        status = project.status if project is not None else ProjectStatus.PENDING
        input_item = self._input_item_for_project(task, project_name)
        write_project_metadata(
            project_dir=Path(str(output_dir)),
            task_id=task.task_id,
            input_type=task.input_type,
            input_item=input_item,
            project_name=project_name,
            status=status,
            engine=task.engine,
            source_markdown_path=(
                project.source_markdown_path if project is not None else None
            ),
            translated_markdown_path=(
                project.translated_markdown_path if project is not None else None
            ),
        )

    def _input_item_for_project(self, task: TaskViewState, project_name: str) -> str:
        """Return the submitted input item that most likely produced the project."""
        for item in task.inputs:
            if Path(item).name == project_name or item == project_name:
                return item
        return task.inputs[0] if task.inputs else project_name

    def _refresh_tex_preview(self, project: ProjectViewState) -> None:
        """Load the first TeX source as a read-only preview."""
        tex_preview = self.query_one("#tex-preview", Static)
        tex_path = self._find_tex_preview_path(project)
        if tex_path is None:
            tex_preview.update("")
            return

        try:
            tex_preview.update(self._latex_syntax(tex_path.read_text(encoding="utf-8")))
        except OSError as exc:
            tex_preview.update(f"无法读取 TeX 文件：{exc}")

    def _refresh_markdown_previews(self, project: ProjectViewState) -> None:
        """Render source and translated Markdown artifacts for a lite project."""
        self._refresh_markdown_preview(
            "#source-markdown-preview",
            project.source_markdown_path,
            "源",
        )
        self._refresh_markdown_preview(
            "#translated-markdown-preview",
            project.translated_markdown_path,
            "译文",
        )

    def _refresh_markdown_preview(
        self,
        widget_id: str,
        markdown_path: str | None,
        label: str,
    ) -> None:
        """Render one Markdown artifact or a clear unavailable-artifact message."""
        preview = self.query_one(widget_id, Static)
        if not markdown_path:
            preview.update(f"没有可用的{label} Markdown 文件。")
            return
        path = Path(markdown_path)
        if not path.is_file():
            preview.update(f"Markdown 文件不存在：{path}")
            return
        try:
            preview.update(
                Syntax(
                    path.read_text(encoding="utf-8"),
                    "markdown",
                    theme="ansi_dark",
                    line_numbers=True,
                    word_wrap=True,
                )
            )
        except OSError as exc:
            preview.update(f"无法读取 Markdown 文件：{exc}")

    def _latex_syntax(self, source: str) -> Syntax:
        """把 TeX 源码转换为离线 Rich LaTeX 高亮对象。"""
        return Syntax(
            source,
            "latex",
            theme="ansi_dark",
            line_numbers=True,
            word_wrap=True,
        )

    def _find_tex_preview_path(self, project: ProjectViewState) -> Path | None:
        """Find a representative TeX file for the project preview."""
        if project.project_dir is None:
            return None

        project_dir = Path(project.project_dir)
        if not project_dir.exists():
            return None

        if project_dir.is_file() and project_dir.suffix.lower() == ".tex":
            return project_dir

        main_tex = project_dir / "main.tex"
        if main_tex.is_file():
            return main_tex

        try:
            return next(path for path in sorted(project_dir.glob("*.tex")) if path.is_file())
        except StopIteration:
            return None

    def _refresh_project_log(
        self,
        project: ProjectViewState,
        task_log_lines: list[str] | None = None,
    ) -> None:
        """Load the selected project's log file into the log panel."""
        log_widget = self.query_one("#project-log", RichLog)
        log_widget.clear()
        if project.log_path is None:
            for line in [*(task_log_lines or []), *project.log_lines]:
                log_widget.write(line)
            return

        try:
            log_text = Path(project.log_path).read_text(encoding="utf-8")
            log_text = _merge_project_log_text(log_text, [*(task_log_lines or []), *project.log_lines])
            log_text = compact_progress_log_for_display(log_text)
        except OSError as exc:
            fallback_lines = [*(task_log_lines or []), *project.log_lines]
            log_text = "\n".join(fallback_lines) if fallback_lines else f"无法读取日志文件：{exc}"
        log_widget.write(log_text)

    def _refresh_errors_table(self, project: ProjectViewState) -> None:
        """刷新选中项目的错误记录表，展示错误内容和解决状态。"""
        table = self.query_one("#errors-table", DataTable)
        table.clear(columns=True)
        widths = self._errors_column_widths(table)
        for label, width in zip(("位置", "类型", "问题", "状态", "原文", "译文"), widths):
            table.add_column(label, width=width)

        for report, status in self._error_reports_with_status(project):
            source, translation = self._error_report_content(report, project)
            table.add_row(
                self._error_report_position(report),
                self._error_report_type(report),
                self._truncated_plain_text(self._error_report_problem(report), widths[2]),
                self._error_status_text(status),
                self._truncated_plain_text(source, widths[4]),
                self._truncated_plain_text(translation, widths[5]),
                height=1,
            )

    def _refresh_selected_errors_table(self) -> None:
        """在错误 tab 可见后按真实表格宽度重绘错误表。"""
        project = self._selected_project()
        if project is not None:
            self._refresh_errors_table(project)

    def _errors_column_widths(self, table: DataTable) -> tuple[int, int, int, int, int, int]:
        """按错误表可视宽度分配固定列宽，避免长内容撑出横向滚动。"""
        visible_width = self._errors_table_available_width(table)
        padding_budget = 2 * table.cell_padding * 6
        content_budget = max(
            visible_width - padding_budget,
            (
                ERROR_POSITION_COLUMN_WIDTH
                + ERROR_TYPE_COLUMN_WIDTH
                + ERROR_PROBLEM_COLUMN_WIDTH
                + ERROR_STATUS_COLUMN_WIDTH
                + ERROR_MIN_CONTENT_COLUMN_WIDTH * 2
            ),
        )
        fixed_width = (
            ERROR_POSITION_COLUMN_WIDTH
            + ERROR_TYPE_COLUMN_WIDTH
            + ERROR_PROBLEM_COLUMN_WIDTH
            + ERROR_STATUS_COLUMN_WIDTH
        )
        content_width = max(content_budget - fixed_width, ERROR_MIN_CONTENT_COLUMN_WIDTH * 2)
        source_width = max(ERROR_MIN_CONTENT_COLUMN_WIDTH, content_width // 2)
        translation_width = max(ERROR_MIN_CONTENT_COLUMN_WIDTH, content_width - source_width)
        return (
            ERROR_POSITION_COLUMN_WIDTH,
            ERROR_TYPE_COLUMN_WIDTH,
            ERROR_PROBLEM_COLUMN_WIDTH,
            ERROR_STATUS_COLUMN_WIDTH,
            source_width,
            translation_width,
        )

    def _errors_table_available_width(self, table: DataTable) -> int:
        """返回错误表可用于分配列宽的当前宽度。"""
        if table.size.width:
            return table.size.width
        for selector in ("#detail-tabs", "#main-switcher"):
            try:
                width = self.query_one(selector).size.width
            except NoMatches:
                width = 0
            if width:
                return width
        screen_width = self.screen.size.width if self.screen else 0
        return max((screen_width * 4) // 5, 80)

    def _error_reports_with_status(self, project: ProjectViewState) -> list[tuple[dict[str, object], str]]:
        """读取最终和初始错误报告，合并为带解决状态的展示行。"""
        report_path = self._project_errors_report_path(project)
        final_reports = self._read_error_report(str(report_path) if report_path else None)
        initial_path = self._initial_error_report_path(str(report_path) if report_path else None)
        initial_reports = self._read_error_report(str(initial_path) if initial_path else None)
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

        final_by_key = {self._error_report_key(report): report for report in final_reports}
        initial_by_key = {self._error_report_key(report): report for report in initial_reports}
        rows: list[tuple[dict[str, object], str]] = []
        for key, report in final_by_key.items():
            rows.append((report, "unresolved"))
            initial_by_key.pop(key, None)
        for report in initial_by_key.values():
            rows.append((report, "resolved"))
        return rows

    def _read_error_report(self, report_path: str | None) -> list[dict[str, object]]:
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

    def _initial_error_report_path(self, report_path: str | None) -> Path | None:
        """返回最终错误报告同目录下的初始错误报告路径。"""
        if not report_path:
            return None
        return Path(report_path).parent / "initial_errors_report.json"

    def _project_errors_report_path(self, project: ProjectViewState) -> Path | None:
        """返回项目错误报告路径，必要时从输出目录发现并回填。"""
        if project.errors_report_path:
            report_path = Path(project.errors_report_path)
            if report_path.is_file():
                return report_path
        if project.output_dir:
            fallback_path = Path(project.output_dir) / "errors_report.json"
            if fallback_path.is_file():
                project.errors_report_path = str(fallback_path)
                return fallback_path
        return None

    def _error_report_key(self, report: dict[str, object]) -> tuple[str, str]:
        """返回用于判断同一错误位置是否仍未解决的稳定键。"""
        return (str(report.get("part") or ""), str(report.get("num_or_ph") or ""))

    def _error_report_position(self, report: dict[str, object]) -> str:
        """把错误记录的位置字段转换为表格显示文本。"""
        part = str(report.get("part") or "")
        identifier = str(report.get("num_or_ph") or "-")
        part_labels = {"sec": "章节", "cap": "图题", "env": "环境", "project": "项目"}
        label = part_labels.get(part, part or "项目")
        return f"{label} {identifier}".strip()

    def _error_report_type(self, report: dict[str, object]) -> str:
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

    def _error_report_problem(self, report: dict[str, object]) -> str:
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

    def _error_status_text(self, status: str) -> Text:
        """返回仅状态单元格使用的彩色 Rich 文本。"""
        if status == "resolved":
            return Text("已解决", style="green")
        if status == "warning":
            return Text("警告", style="yellow")
        return Text("未解决", style="yellow")

    def _error_report_content(self, report: dict[str, object], project: ProjectViewState) -> tuple[str, str]:
        """反查错误位置对应的原文和译文内容。"""
        content_root = self._error_content_root(project)
        if content_root is None:
            return "", ""
        part = str(report.get("part") or "")
        identifier = str(report.get("num_or_ph") or "")
        part_record = self._find_error_part_record(content_root, part, identifier)
        if part_record is None:
            return "", ""
        return str(part_record.get("content") or ""), str(part_record.get("trans_content") or "")

    def _error_content_root(self, project: ProjectViewState) -> Path | None:
        """确定错误报告关联的输出目录，用于读取 map JSON。"""
        if project.errors_report_path:
            return Path(project.errors_report_path).parent
        if project.output_dir:
            return Path(project.output_dir)
        return None

    def _find_error_part_record(
        self,
        content_root: Path,
        part: str,
        identifier: str,
    ) -> dict[str, object] | None:
        """在 sections/captions/envs map 中查找错误位置对应的内容记录。"""
        map_specs = {
            "sec": ("sections_map.json", "section"),
            "cap": ("captions_map.json", "placeholder"),
            "env": ("envs_map.json", "placeholder"),
        }
        spec = map_specs.get(part)
        if spec is None:
            return None
        filename, key = spec
        for record in self._read_json_list(content_root / filename):
            if str(record.get(key) or "") == identifier:
                return record
        return None

    def _read_json_list(self, path: Path) -> list[dict[str, object]]:
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

    def _truncated_plain_text(self, value: str, width: int) -> Text:
        """按列宽截断普通文本，不对内容本身做额外高亮。"""
        collapsed = re.sub(r"\s+", " ", value).strip()
        limit = max(width, 3)
        if len(collapsed) > limit:
            collapsed = collapsed[: max(limit - 3, 0)] + "..."
        return Text(collapsed, overflow="ellipsis", no_wrap=True)

    def _refresh_terms_table(self, project: ProjectViewState) -> None:
        """Refresh the selected project's read-only terminology table."""
        table = self.query_one("#terms-table", DataTable)
        table.clear(columns=True)
        table.add_columns("术语", "译文")
        terms_path = self._project_terms_path(project)
        if terms_path is None:
            return

        try:
            with terms_path.open("r", encoding="utf-8", newline="") as terms_file:
                rows = list(csv.reader(terms_file))
        except OSError as exc:
            table.add_row("术语表读取错误", str(exc))
            return

        for row in rows[1:]:
            if len(row) >= 2:
                table.add_row(row[0], row[1])

    def _project_terms_path(self, project: ProjectViewState) -> Path | None:
        """Return the terminology CSV path for a project, including output-dir fallback."""
        if project.project_terms_path:
            terms_path = Path(project.project_terms_path)
            if terms_path.is_file():
                return terms_path
        if project.output_dir:
            fallback_path = Path(project.output_dir) / "project_terms.csv"
            if fallback_path.is_file():
                project.project_terms_path = str(fallback_path)
                return fallback_path
        return None

    def _initialize_zotero_results_table(self) -> None:
        """初始化 Zotero 结果表的固定列。"""
        table = self.query_one("#zotero-results", DataTable)
        table.cursor_type = "row"
        table.clear(columns=True)
        selection_width, title_width, library_width, collection_width = self._zotero_column_widths(table)
        table.add_column("选中", width=selection_width)
        table.add_column("标题", width=title_width)
        table.add_column("所在库", width=library_width)
        table.add_column("所在分类", width=collection_width)

    def _zotero_column_widths(self, table: DataTable) -> tuple[int, int, int, int]:
        """按表格可视宽度分配 Zotero 结果列宽，避免触发水平滚动。"""
        visible_width = table.size.width or 100
        padding_budget = 2 * table.cell_padding * 4
        content_budget = max(
            visible_width - padding_budget,
            ZOTERO_SELECTION_COLUMN_WIDTH + ZOTERO_MIN_TITLE_COLUMN_WIDTH,
        )
        remaining = max(content_budget - ZOTERO_SELECTION_COLUMN_WIDTH, ZOTERO_MIN_TITLE_COLUMN_WIDTH)
        library_width = min(
            ZOTERO_MAX_LIBRARY_COLUMN_WIDTH,
            max(ZOTERO_MIN_LIBRARY_COLUMN_WIDTH, remaining // 5),
        )
        collection_width = min(
            ZOTERO_MAX_COLLECTION_COLUMN_WIDTH,
            max(ZOTERO_MIN_COLLECTION_COLUMN_WIDTH, remaining // 4),
        )
        title_width = remaining - library_width - collection_width

        if title_width < ZOTERO_MIN_TITLE_COLUMN_WIDTH:
            shortage = ZOTERO_MIN_TITLE_COLUMN_WIDTH - title_width
            collection_reduction = min(shortage, max(collection_width - ZOTERO_MIN_COLLECTION_COLUMN_WIDTH, 0))
            collection_width -= collection_reduction
            shortage -= collection_reduction
            library_reduction = min(shortage, max(library_width - ZOTERO_MIN_LIBRARY_COLUMN_WIDTH, 0))
            library_width -= library_reduction
            title_width = remaining - library_width - collection_width

        return (
            ZOTERO_SELECTION_COLUMN_WIDTH,
            max(title_width, ZOTERO_MIN_TITLE_COLUMN_WIDTH),
            library_width,
            collection_width,
        )

    def _fit_zotero_results_table_columns(self) -> None:
        """在布局稳定后重新收紧 Zotero 结果列宽。"""
        table = self.query_one("#zotero-results", DataTable)
        widths = self._zotero_column_widths(table)
        for column, width in zip(table.ordered_columns, widths):
            column.width = width
            column.auto_width = False
        table._require_update_dimensions = True
        table._line_cache.clear()
        table.refresh(layout=True)

    def _refresh_zotero_controls(self) -> None:
        """按当前项目及其引擎刷新 Zotero 导入控件可见性。"""
        project = self._selected_project()
        has_pdf = bool(project and project.pdf_path)
        has_markdown = bool(project and project.engine == "lite")
        self.query_one("#zotero-import-rule", Rule).display = has_pdf
        self.query_one("#import-zotero-button", Button).display = has_pdf
        self.query_one("#import-zotero-markdown-button", Button).display = has_markdown

    def load_zotero_libraries(self) -> None:
        """从本地 Zotero API 加载可选库到搜索范围下拉框。"""
        try:
            libraries = self._zotero_adapter().list_libraries()
        except Exception as exc:
            self.zotero_libraries = []
            self._set_zotero_status(f"本地 API 不可用：{exc}")
            return

        self.zotero_libraries = libraries
        options = [
            (str(item.get("name") or item.get("library_id")), self._zotero_library_value(item))
            for item in libraries
        ]
        select = self.query_one("#zotero-library-select", Select)
        select.set_options(options)
        if options:
            select.value = options[0][1]
            self._set_zotero_status("")
        else:
            self._set_zotero_status("没有可选库。")

    def search_zotero_items(self) -> None:
        """使用搜索框文本和当前库执行 Zotero 本地 API 搜索。"""
        query = self.query_one("#zotero-search-input", Input).value.strip()
        if not query:
            self._set_zotero_status("搜索框为空。")
            return
        library = self._selected_zotero_library()
        if library is None:
            self._set_zotero_status("未选择库。")
            return

        try:
            results = self._zotero_adapter().search_items(
                query,
                str(library["library_id"]),
                str(library["library_type"]),
            )
        except Exception as exc:
            self._set_zotero_status(f"搜索失败：{exc}")
            return

        self.populate_zotero_results(results)
        self._set_zotero_status("搜索无结果。" if not results else f"找到 {len(results)} 个条目。")

    def auto_match_zotero_items(self) -> None:
        """按当前 arXiv ID 匹配 Zotero 存档 id 字段。"""
        arxiv_id = self._selected_arxiv_id()
        if not arxiv_id:
            self._set_zotero_status("自动匹配缺少 arXiv ID。")
            return
        library = self._selected_zotero_library()
        if library is None:
            self._set_zotero_status("未选择库。")
            return

        try:
            results = self._zotero_adapter().match_items_by_archive_id(
                arxiv_id,
                str(library["library_id"]),
                str(library["library_type"]),
            )
        except Exception as exc:
            self._set_zotero_status(f"自动匹配失败：{exc}")
            return

        self.populate_zotero_results(results)
        self._set_zotero_status("搜索无结果。" if not results else f"找到 {len(results)} 个条目。")

    def populate_zotero_results(self, results: list[dict[str, object]]) -> None:
        """把 Zotero 搜索结果写入固定列数据表，并清空选择。"""
        self.zotero_results = list(results)
        self.zotero_selected_keys = set()
        self._initialize_zotero_results_table()
        table = self.query_one("#zotero-results", DataTable)
        for item in self.zotero_results:
            table.add_row(
                "[]",
                Text(str(item.get("title") or ""), overflow="ellipsis", no_wrap=True),
                str(item.get("library_name") or item.get("library_id") or ""),
                ", ".join(str(value) for value in item.get("collection_names", []) or []),
            )
        table.call_after_refresh(self._fit_zotero_results_table_columns)

    def clear_zotero_results(self) -> None:
        """清空当前项目的 Zotero 搜索结果和选择状态。"""
        self.zotero_results = []
        self.zotero_selected_keys = set()
        self._initialize_zotero_results_table()

    def toggle_zotero_row_selection(self, row_index: int) -> None:
        """切换指定 Zotero 结果行的多选状态。"""
        if row_index < 0 or row_index >= len(self.zotero_results):
            return
        table = self.query_one("#zotero-results", DataTable)
        item = self.zotero_results[row_index]
        item_key = str(item.get("item_key") or "")
        if item_key in self.zotero_selected_keys:
            self.zotero_selected_keys.remove(item_key)
            table.update_cell_at((row_index, 0), "[]")
        else:
            self.zotero_selected_keys.add(item_key)
            table.update_cell_at((row_index, 0), "[√]")

    def import_selected_project_to_zotero(self) -> None:
        """把当前选中项目的译文 PDF 附加到所有选中 Zotero 条目。"""
        project = self._selected_project()
        if project is None:
            self._set_zotero_status("请选择一个项目。")
            return
        if not project.pdf_path:
            project.zotero_status = "失败：当前项目没有 PDF。"
            self._set_zotero_status(project.zotero_status)
            return

        selected_items = [
            item
            for item in self.zotero_results
            if str(item.get("item_key") or "") in self.zotero_selected_keys
        ]
        if not selected_items:
            project.zotero_status = "失败：未选择任何条目。"
            self._set_zotero_status(project.zotero_status)
            return

        api_key_env = self._zotero_config().get("web_api_key_env", "ZOTERO_API_KEY")
        api_key = os.environ.get(str(api_key_env), "").strip()
        if not api_key:
            project.zotero_status = f"失败：Web API key 环境变量未设置：{api_key_env}。"
            self._set_zotero_status(project.zotero_status)
            return

        adapter = self._zotero_adapter(api_key=api_key)
        success_count = 0
        failures: list[str] = []
        for item in selected_items:
            item_key = str(item.get("item_key") or "")
            library_id = str(item.get("library_id") or "")
            library_type = str(item.get("library_type") or "")
            try:
                adapter.attach_pdf(item_key, project.pdf_path, library_id, library_type)
                success_count += 1
            except Exception as exc:
                failures.append(f"{item_key}: {exc}")

        project.zotero_status = f"导入完成：成功 {success_count}，失败 {len(failures)}。"
        if failures:
            project.zotero_status = f"{project.zotero_status} {'; '.join(failures)}"
        self._set_zotero_status(project.zotero_status)

    def import_selected_project_markdown_to_zotero(self) -> None:
        """Import the selected lite project's translated Markdown as Zotero child notes."""
        project = self._selected_project()
        if project is None:
            self._set_zotero_status("请选择一个项目。")
            return
        if project.engine != "lite":
            project.zotero_status = "失败：Markdown 导入仅支持 Lite 引擎。"
            self._set_zotero_status(project.zotero_status)
            return

        selected_items = [
            item
            for item in self.zotero_results
            if str(item.get("item_key") or "") in self.zotero_selected_keys
        ]
        if not selected_items:
            project.zotero_status = "失败：未选择任何条目。"
            self._set_zotero_status(project.zotero_status)
            return

        markdown_path = self._translated_markdown_path(project)
        if markdown_path is None or not markdown_path.is_file():
            project.zotero_status = "失败：当前项目没有译文 Markdown 文件。"
            self._set_zotero_status(project.zotero_status)
            return
        try:
            markdown = markdown_path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            project.zotero_status = f"失败：无法读取译文 Markdown 文件：{exc}"
            self._set_zotero_status(project.zotero_status)
            return

        api_key_env = self._zotero_config().get("web_api_key_env", "ZOTERO_API_KEY")
        api_key = os.environ.get(str(api_key_env), "").strip()
        if not api_key:
            project.zotero_status = f"失败：Web API key 环境变量未设置：{api_key_env}。"
            self._set_zotero_status(project.zotero_status)
            return

        adapter = self._zotero_adapter(api_key=api_key)
        success_count = 0
        failures: list[str] = []
        for item in selected_items:
            item_key = str(item.get("item_key") or "")
            library_id = str(item.get("library_id") or "")
            library_type = str(item.get("library_type") or "")
            try:
                adapter.create_note(item_key, project.project_name or markdown_path.stem, markdown, library_id, library_type)
                success_count += 1
            except Exception as exc:
                failures.append(f"{item_key}: {exc}")

        project.zotero_status = f"导入完成：成功 {success_count}，失败 {len(failures)}。"
        if failures:
            project.zotero_status = f"{project.zotero_status} {'; '.join(failures)}"
        self._set_zotero_status(project.zotero_status)

    def _translated_markdown_path(self, project: ProjectViewState) -> Path | None:
        """Return the selected project's translated Markdown artifact when known."""
        if project.translated_markdown_path:
            return Path(project.translated_markdown_path)
        if project.output_dir:
            return Path(project.output_dir) / "translated.md"
        return None

    def _set_zotero_status(self, message: str) -> None:
        """记录 Zotero 操作状态，并在可见 UI 中发出轻量提示。"""
        project = self._selected_project()
        if project is not None and message:
            project.zotero_status = message
        if message:
            self._notify(message)

    def _zotero_config(self) -> dict[str, object]:
        """返回当前 UI 配置中的 Zotero 配置段。"""
        config = self.current_config or load_ui_config(Path.cwd())
        zotero_config = config.get("zotero", {}) if isinstance(config, dict) else {}
        if not isinstance(zotero_config, dict):
            return {}
        return zotero_config

    def _zotero_adapter(self, api_key: str = "") -> ZoteroAdapter:
        """按当前配置创建 Zotero adapter。"""
        local_api_base = str(self._zotero_config().get("local_api_base", "http://127.0.0.1:23119/api"))
        try:
            return self.zotero_adapter_factory(api_key, local_api_base)
        except TypeError:
            return self.zotero_adapter_factory(api_key, "")

    def _zotero_library_value(self, library: dict[str, object]) -> str:
        """返回 Zotero 库下拉框内部值。"""
        return f"{library.get('library_type')}:{library.get('library_id')}"

    def _selected_zotero_library(self) -> dict[str, object] | None:
        """返回当前下拉框选中的 Zotero 库数据。"""
        select = self.query_one("#zotero-library-select", Select)
        if select.is_blank():
            return None
        value = str(select.value)
        return next((item for item in self.zotero_libraries if self._zotero_library_value(item) == value), None)

    def _selected_task_input_type(self) -> str:
        """返回当前选中项目所属任务的输入类型。"""
        if self.selected_project_name is None:
            return self.current_task.input_type if self.current_task is not None else ""
        for task, project in self._iter_project_states():
            if self.selected_task_id is not None and task.task_id != self.selected_task_id:
                continue
            if project.project_name == self.selected_project_name:
                return task.input_type
        return ""

    def _selected_arxiv_id(self) -> str:
        """从当前选中项目或任务输入中提取 arXiv ID。"""
        pattern = re.compile(r"\d{4}\.\d{4,5}(?:v\d+)?")
        candidates: list[str] = []
        if self.selected_project_name:
            candidates.append(self.selected_project_name)
        if self.current_task is not None:
            candidates.extend(self.current_task.inputs)
        for candidate in candidates:
            match = pattern.search(candidate)
            if match:
                return match.group(0)
        return ""

    def start_current_task(self) -> None:
        """通过 Textual worker 启动当前任务。"""
        if self.current_task is None:
            return
        task = self.current_task
        task.total = len(task.inputs)
        self.run_current_task(task)

    @work(thread=True, exclusive=True)
    def run_current_task(self, task: TaskViewState) -> None:
        """在后台线程轮询独立翻译进程，避免阻塞 Textual UI。"""
        if task not in self.tasks and task is not self.current_task:
            return

        # 保留测试和第三方调用方替换旧 runner 的兼容入口；生产路径始终使用独立进程。
        if run_tui_task is not _DEFAULT_RUN_TUI_TASK:
            def callback(event: dict[str, object]) -> None:
                """把兼容 runner 事件转回 Textual UI 线程。"""
                self.call_from_thread(self.handle_runtime_event, event, task)

            try:
                run_tui_task(
                    config_path=str(UI_CONFIG_PATH),
                    input_type=task.input_type,
                    items=task.inputs,
                    overrides={},
                    event_callback=callback,
                    engine=task.engine,
                )
            except Exception as exc:
                if task.input_type == "remote" and task.total == 0:
                    self.call_from_thread(self._notify_empty_task_failure, task, str(exc))
                else:
                    project_name = task.running_project or (task.inputs[0] if task.inputs else "task")
                    self.call_from_thread(
                        self.handle_runtime_event,
                        {"type": "project_error", "project_name": project_name, "error": str(exc)},
                        task,
                    )
            return

        task_id = task.task_id
        process_handle = start_tui_task_process(
            config_path=str(UI_CONFIG_PATH),
            input_type=task.input_type,
            items=task.inputs,
            overrides={},
            engine=task.engine,
        )
        self.task_processes[task_id] = process_handle

        try:
            while True:
                messages = drain_process_messages(process_handle)
                for message_type, payload in messages:
                    if message_type == "event" and isinstance(payload, dict):
                        self.call_from_thread(self.handle_runtime_event, payload, task)
                    elif message_type == "error":
                        error = str(payload.get("error") if isinstance(payload, dict) else payload)
                        if task.input_type == "remote" and task.total == 0:
                            self.call_from_thread(self._notify_empty_task_failure, task, error)
                        else:
                            project_name = task.running_project or (task.inputs[0] if task.inputs else "task")
                            self.call_from_thread(
                                self.handle_runtime_event,
                                {"type": "project_error", "project_name": project_name, "error": error},
                                task,
                            )
                if not process_handle.process.is_alive() and not messages:
                    break
                time.sleep(0.05)
            exit_code = getattr(process_handle.process, "exitcode", None)
            if isinstance(exit_code, int) and exit_code != 0 and task.task_id not in self.cancelled_task_ids:
                project_name = task.running_project or (task.inputs[0] if task.inputs else "task")
                self.call_from_thread(
                    self.handle_runtime_event,
                    {
                        "type": "project_error",
                        "project_name": project_name,
                        "error": f"翻译进程异常退出（退出码 {exit_code}）",
                    },
                    task,
                )
        except Exception as exc:
            if task.input_type == "remote" and task.total == 0:
                self.call_from_thread(self._notify_empty_task_failure, task, str(exc))
            else:
                project_name = task.running_project or (task.inputs[0] if task.inputs else "task")
                self.call_from_thread(
                    self.handle_runtime_event,
                    {"type": "project_error", "project_name": project_name, "error": str(exc)},
                    task,
                )
        finally:
            if self.task_processes.get(task_id) is process_handle:
                self.task_processes.pop(task_id, None)

    def terminate_task_process(self, task_id: str) -> None:
        """强制终止指定任务进程，并将其中运行项目标记为 cancelled。"""
        process_handle = self.task_processes.get(task_id)
        task = next((item for item in self.tasks if item.task_id == task_id), None)
        if task is None and self.current_task is not None and self.current_task.task_id == task_id:
            task = self.current_task
        if process_handle is None or task is None:
            return

        self.cancelled_task_ids.add(task_id)
        terminate_tui_task_process(process_handle)
        running_projects = [project for project in task.projects if project.status == ProjectStatus.RUNNING]
        if not running_projects and task.running_project:
            running_projects = [
                project
                for project in task.projects
                if project.project_name == task.running_project
            ]
        for project in running_projects:
            self.handle_runtime_event(
                {
                    "type": "project_cancelled",
                    "project_name": project.project_name,
                    "output_dir": project.output_dir,
                },
                task,
            )
        self.task_processes.pop(task_id, None)
        self.refresh_project_list()
        self.refresh_task_table()

    def action_new_task(self) -> None:
        """Open the entry page."""
        self.switch_page(PAGE_ENTRY)

    def action_project_manager(self) -> None:
        """Open the project management page."""
        self.switch_page(PAGE_TASKS)

    def action_task_manager(self) -> None:
        """Open the project management page through the legacy binding name."""
        self.action_project_manager()

    def action_settings(self) -> None:
        """Open the configuration page."""
        self.switch_page(PAGE_CONFIG)
        self.load_config_page()


def _startup_engine(cli_engine: str | None) -> str:
    """Resolve startup mode with CLI selection ahead of saved UI settings."""
    if cli_engine is not None:
        return normalize_engine(cli_engine)
    try:
        config = load_ui_config(Path.cwd())
        return normalize_engine(config.get("engine", "heavy"))
    except (OSError, ValueError):
        return "heavy"


def run(argv: Sequence[str] | None = None) -> None:
    """Run the LaTeXTransPlus terminal UI with an optional session engine override."""
    parser = argparse.ArgumentParser(prog="latextrans-tui")
    parser.add_argument("--engine", "-e", choices=("heavy", "lite"), default=None)
    args = parser.parse_args(argv)
    LaTeXTransTuiApp(initial_engine=_startup_engine(args.engine)).run()
