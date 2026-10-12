"""Zotero 搜索、选择与导入面板。"""

from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import Callable

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.message import Message
from textual.widgets import Button, DataTable, Input, Rule, Select, TabPane

from src.engines.base import normalize_engine
from src.tui.state import ProjectViewState
from src.tui.widgets import ZoteroResultsTable, ZoteroSearchInput
from src.tui.zotero_adapter import ZoteroAdapter

ZOTERO_SELECTION_COLUMN_WIDTH = 4
ZOTERO_MIN_TITLE_COLUMN_WIDTH = 20
ZOTERO_MIN_LIBRARY_COLUMN_WIDTH = 10
ZOTERO_MAX_LIBRARY_COLUMN_WIDTH = 18
ZOTERO_MIN_COLLECTION_COLUMN_WIDTH = 12
ZOTERO_MAX_COLLECTION_COLUMN_WIDTH = 24


def _default_adapter_factory(api_key: str, local_api_base: str) -> ZoteroAdapter:
    """按默认参数创建 Zotero 适配器。"""
    return ZoteroAdapter(api_key=api_key, local_api_base=local_api_base)


class ZoteroPanel(TabPane):
    """封装 Zotero 标签页的上下文、交互和业务状态。"""

    class StatusChanged(Message):
        """通知 App 展示面板产生的状态消息。"""

        def __init__(self, message: str) -> None:
            """保存需要通过统一通知入口展示的消息。"""
            super().__init__()
            self.message = message

    def __init__(
        self,
        adapter_factory: Callable[[str, str], ZoteroAdapter] = _default_adapter_factory,
        *,
        id: str = "zotero-tab",
    ) -> None:
        """初始化空面板并保存可替换的适配器工厂。"""
        super().__init__("Zotero", id=id)
        self.adapter_factory = adapter_factory
        self.project: ProjectViewState | None = None
        self.task_id: str | None = None
        self.input_type = ""
        self.arxiv_id = ""
        self.engine = "heavy"
        self.config: dict[str, object] = {}
        self.zotero_libraries: list[dict[str, object]] = []
        self.zotero_results: list[dict[str, object]] = []
        self.zotero_selected_keys: set[str] = set()
        self._context_identity: tuple[str | None, str] | None = None

    def compose(self) -> ComposeResult:
        """构建 Zotero 搜索控件、导入按钮和结果表。"""
        with Horizontal(id="zotero-controls"):
            yield Select([], id="zotero-library-select")
            yield ZoteroSearchInput(id="zotero-search-input")
            yield Button("搜索", id="zotero-search-button", flat=True)
            yield Button("自动匹配", id="zotero-auto-match-button", flat=True)
            yield Rule(orientation="vertical", id="zotero-import-rule")
            yield Button("导入 PDF", id="import-zotero-button", flat=True)
            yield Button("导入 Markdown", id="import-zotero-markdown-button", flat=True)
        yield ZoteroResultsTable(id="zotero-results", cursor_type="row")

    def on_mount(self) -> None:
        """挂载后初始化固定列并同步导入按钮可见性。"""
        self._initialize_zotero_results_table()
        self._refresh_zotero_controls()

    def set_context(
        self,
        *,
        project: ProjectViewState | None,
        task_id: str | None,
        input_type: str,
        arxiv_id: str,
        engine: str,
        config: dict[str, object],
        reset_selection: bool = False,
    ) -> None:
        """更新明确上下文，并在身份变化或显式请求时清空结果。"""
        normalized_engine = normalize_engine(engine)
        identity = (task_id, project.project_name) if project is not None else None
        should_clear = reset_selection or project is None or identity != self._context_identity
        self.project = project
        self.task_id = task_id
        self.input_type = input_type
        self.arxiv_id = arxiv_id
        self.engine = normalized_engine
        self.config = copy.deepcopy(config)
        self._context_identity = identity
        if should_clear:
            self.clear_zotero_results()
        if self.is_mounted:
            self._refresh_zotero_controls()

    def update_config(self, config: dict[str, object]) -> None:
        """替换 Zotero 配置副本并保留当前结果和选择。"""
        self.config = copy.deepcopy(config)

    def _initialize_zotero_results_table(self) -> None:
        """初始化 Zotero 结果表的固定列。"""
        if not self.is_mounted:
            return
        table = self.query_one("#zotero-results", DataTable)
        table.cursor_type = "row"
        table.clear(columns=True)
        widths = self._zotero_column_widths(table)
        for label, width in zip(("选中", "标题", "所在库", "所在分类"), widths):
            table.add_column(label, width=width)

    def _zotero_column_widths(self, table: DataTable) -> tuple[int, int, int, int]:
        """按可视宽度分配结果列宽，保留原有最小宽度策略。"""
        visible_width = table.size.width or 100
        padding_budget = 2 * table.cell_padding * 4
        content_budget = max(
            visible_width - padding_budget,
            ZOTERO_SELECTION_COLUMN_WIDTH + ZOTERO_MIN_TITLE_COLUMN_WIDTH,
        )
        remaining = max(
            content_budget - ZOTERO_SELECTION_COLUMN_WIDTH,
            ZOTERO_MIN_TITLE_COLUMN_WIDTH,
        )
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
            reduction = min(
                shortage,
                max(collection_width - ZOTERO_MIN_COLLECTION_COLUMN_WIDTH, 0),
            )
            collection_width -= reduction
            shortage -= reduction
            reduction = min(
                shortage,
                max(library_width - ZOTERO_MIN_LIBRARY_COLUMN_WIDTH, 0),
            )
            library_width -= reduction
            title_width = remaining - library_width - collection_width

        return (
            ZOTERO_SELECTION_COLUMN_WIDTH,
            max(title_width, ZOTERO_MIN_TITLE_COLUMN_WIDTH),
            library_width,
            collection_width,
        )

    def _fit_zotero_results_table_columns(self) -> None:
        """在布局稳定后重新收紧结果列宽。"""
        table = self.query_one("#zotero-results", DataTable)
        widths = self._zotero_column_widths(table)
        for column, width in zip(table.ordered_columns, widths):
            column.width = width
            column.auto_width = False
        table._require_update_dimensions = True
        table._line_cache.clear()
        table.refresh(layout=True)

    def _refresh_zotero_controls(self) -> None:
        """按当前上下文刷新 PDF 与 Markdown 导入控件。"""
        has_pdf = bool(self.project and self.project.pdf_path)
        has_markdown = bool(self.project and self.engine == "lite")
        self.query_one("#zotero-import-rule", Rule).display = has_pdf
        self.query_one("#import-zotero-button", Button).display = has_pdf
        self.query_one("#import-zotero-markdown-button", Button).display = has_markdown

    def load_zotero_libraries(self) -> None:
        """从本地 Zotero API 加载可选库。"""
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
        """使用当前搜索词和选中库查询 Zotero 条目。"""
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
        """按明确提供的 arXiv ID 匹配 Zotero 存档字段。"""
        if not self.arxiv_id:
            self._set_zotero_status("自动匹配缺少 arXiv ID。")
            return
        library = self._selected_zotero_library()
        if library is None:
            self._set_zotero_status("未选择库。")
            return

        try:
            results = self._zotero_adapter().match_items_by_archive_id(
                self.arxiv_id,
                str(library["library_id"]),
                str(library["library_type"]),
            )
        except Exception as exc:
            self._set_zotero_status(f"自动匹配失败：{exc}")
            return

        self.populate_zotero_results(results)
        self._set_zotero_status("搜索无结果。" if not results else f"找到 {len(results)} 个条目。")

    def populate_zotero_results(self, results: list[dict[str, object]]) -> None:
        """写入搜索结果并清空当前条目选择。"""
        self.zotero_results = list(results)
        self.zotero_selected_keys = set()
        self._initialize_zotero_results_table()
        if not self.is_mounted:
            return
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
        """清空当前搜索结果与条目选择。"""
        self.zotero_results = []
        self.zotero_selected_keys = set()
        self._initialize_zotero_results_table()

    def toggle_zotero_row_selection(self, row_index: int) -> None:
        """切换指定结果行的多选状态。"""
        if row_index < 0 or row_index >= len(self.zotero_results):
            return
        table = self.query_one("#zotero-results", DataTable)
        item_key = str(self.zotero_results[row_index].get("item_key") or "")
        if item_key in self.zotero_selected_keys:
            self.zotero_selected_keys.remove(item_key)
            table.update_cell_at((row_index, 0), "[]")
        else:
            self.zotero_selected_keys.add(item_key)
            table.update_cell_at((row_index, 0), "[√]")

    def import_selected_project_to_zotero(self) -> None:
        """把当前项目 PDF 附加到所有选中 Zotero 条目。"""
        project = self.project
        if project is None:
            self._set_zotero_status("请选择一个项目。")
            return
        if not project.pdf_path:
            self._set_zotero_status("失败：当前项目没有 PDF。")
            return

        selected_items = self._selected_items()
        if not selected_items:
            self._set_zotero_status("失败：未选择任何条目。")
            return
        local_import = self.config.get("pdf_import_api", "web") == "local"
        if local_import:
            adapter = self._zotero_adapter()
        else:
            api_key = self._web_api_key()
            if api_key is None:
                return
            adapter = self._zotero_adapter(api_key=api_key)
        success_count = 0
        failures: list[str] = []
        for item in selected_items:
            item_key = str(item.get("item_key") or "")
            try:
                attach = adapter.attach_pdf_local if local_import else adapter.attach_pdf
                attach(
                    item_key,
                    project.pdf_path,
                    str(item.get("library_id") or ""),
                    str(item.get("library_type") or ""),
                )
                success_count += 1
            except Exception as exc:
                failures.append(f"{item_key}: {exc}")
        self._set_import_status(success_count, failures)

    def import_selected_project_markdown_to_zotero(self) -> None:
        """把当前 Lite 项目的译文 Markdown 创建为子笔记。"""
        project = self.project
        if project is None:
            self._set_zotero_status("请选择一个项目。")
            return
        if self.engine != "lite":
            self._set_zotero_status("失败：Markdown 导入仅支持 Lite 引擎。")
            return

        selected_items = self._selected_items()
        if not selected_items:
            self._set_zotero_status("失败：未选择任何条目。")
            return
        markdown_path = self._translated_markdown_path(project)
        if markdown_path is None or not markdown_path.is_file():
            self._set_zotero_status("失败：当前项目没有译文 Markdown 文件。")
            return
        try:
            markdown = markdown_path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            self._set_zotero_status(f"失败：无法读取译文 Markdown 文件：{exc}")
            return
        api_key = self._web_api_key()
        if api_key is None:
            return

        adapter = self._zotero_adapter(api_key=api_key)
        success_count = 0
        failures: list[str] = []
        for item in selected_items:
            item_key = str(item.get("item_key") or "")
            try:
                adapter.create_note(
                    item_key,
                    project.project_name or markdown_path.stem,
                    markdown,
                    str(item.get("library_id") or ""),
                    str(item.get("library_type") or ""),
                )
                success_count += 1
            except Exception as exc:
                failures.append(f"{item_key}: {exc}")
        self._set_import_status(success_count, failures)

    def _translated_markdown_path(self, project: ProjectViewState) -> Path | None:
        """返回项目已知或按输出目录推断的译文 Markdown 路径。"""
        if project.translated_markdown_path:
            return Path(project.translated_markdown_path)
        if project.output_dir:
            return Path(project.output_dir) / "translated.md"
        return None

    def _selected_items(self) -> list[dict[str, object]]:
        """返回当前结果中所有已选条目。"""
        return [
            item
            for item in self.zotero_results
            if str(item.get("item_key") or "") in self.zotero_selected_keys
        ]

    def _web_api_key(self) -> str | None:
        """从配置指定的环境变量解析 Web API key。"""
        api_key_env = self.config.get("web_api_key_env", "ZOTERO_API_KEY")
        api_key = os.environ.get(str(api_key_env), "").strip()
        if api_key:
            return api_key
        self._set_zotero_status(f"失败：Web API key 环境变量未设置：{api_key_env}。")
        return None

    def _set_import_status(self, success_count: int, failures: list[str]) -> None:
        """汇总逐项导入结果并发布状态。"""
        message = f"导入完成：成功 {success_count}，失败 {len(failures)}。"
        if failures:
            message = f"{message} {'; '.join(failures)}"
        self._set_zotero_status(message)

    def _set_zotero_status(self, message: str) -> None:
        """更新当前项目状态并把非空消息交给 App 通知。"""
        if self.project is not None and message:
            self.project.zotero_status = message
        if message:
            self.post_message(self.StatusChanged(message))

    def _zotero_adapter(self, api_key: str = "") -> ZoteroAdapter:
        """使用面板配置和可替换工厂创建 Zotero 适配器。"""
        local_api_base = str(
            self.config.get("local_api_base", "http://127.0.0.1:23119/api")
        )
        try:
            return self.adapter_factory(api_key, local_api_base)
        except TypeError:
            return self.adapter_factory(api_key, "")

    def _zotero_library_value(self, library: dict[str, object]) -> str:
        """返回 Zotero 库下拉框使用的稳定内部值。"""
        return f"{library.get('library_type')}:{library.get('library_id')}"

    def _selected_zotero_library(self) -> dict[str, object] | None:
        """返回下拉框当前选中的 Zotero 库。"""
        select = self.query_one("#zotero-library-select", Select)
        if select.is_blank():
            return None
        value = str(select.value)
        return next(
            (
                item
                for item in self.zotero_libraries
                if self._zotero_library_value(item) == value
            ),
            None,
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """处理面板所属的搜索、匹配和导入按钮。"""
        handlers = {
            "zotero-search-button": self.search_zotero_items,
            "zotero-auto-match-button": self.auto_match_zotero_items,
            "import-zotero-button": self.import_selected_project_to_zotero,
            "import-zotero-markdown-button": self.import_selected_project_markdown_to_zotero,
        }
        handler = handlers.get(event.button.id or "")
        if handler is not None:
            event.stop()
            handler()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """处理默认 Input 提交路径并阻止事件继续到 App。"""
        if event.input.id == "zotero-search-input":
            event.stop()
            self.search_zotero_items()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """处理键盘行选择，并抑制鼠标设置游标产生的重复切换。"""
        if event.data_table.id != "zotero-results":
            return
        event.stop()
        table = event.data_table
        if getattr(table, "_suppress_next_row_selected", False):
            table._suppress_next_row_selected = False
            return
        if event.cursor_row is not None:
            self.toggle_zotero_row_selection(event.cursor_row)

    def on_zotero_search_input_search_requested(
        self,
        message: ZoteroSearchInput.SearchRequested,
    ) -> None:
        """消费搜索控件请求并执行一次搜索。"""
        message.stop()
        self.search_zotero_items()

    def on_zotero_results_table_selection_requested(
        self,
        message: ZoteroResultsTable.SelectionRequested,
    ) -> None:
        """消费结果表请求并切换一次指定结果行。"""
        message.stop()
        self.toggle_zotero_row_selection(message.row_index)

    def on_zotero_results_table_resize_requested(
        self,
        message: ZoteroResultsTable.ResizeRequested,
    ) -> None:
        """消费结果表尺寸请求并在刷新后调整列宽。"""
        message.stop()
        self.call_after_refresh(self._fit_zotero_results_table_columns)
