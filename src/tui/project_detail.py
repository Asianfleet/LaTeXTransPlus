"""项目详情页及其局部展示状态。"""

from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Callable

from rich.syntax import Syntax
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.widgets import DataTable, RichLog, Static, TabPane, TabbedContent

from src.engines.base import normalize_engine
from src.tui import error_reports
from src.tui.state import ProjectViewState
from src.tui.widgets import DetailTabbedContent, ErrorReportsTable
from src.tui.zotero_adapter import ZoteroAdapter
from src.tui.zotero_panel import ZoteroPanel

ERROR_POSITION_COLUMN_WIDTH = 10
ERROR_TYPE_COLUMN_WIDTH = 5
ERROR_PROBLEM_COLUMN_WIDTH = 24
ERROR_STATUS_COLUMN_WIDTH = 8
ERROR_MIN_CONTENT_COLUMN_WIDTH = 6
PROGRESS_LOG_LINE_RE = re.compile(r"^\[[#-]+\]\s+\d{1,3}(?:\.\d+)?%")


def _merge_project_log_text(file_text: str, memory_lines: list[str]) -> str:
    """合并日志文件与尚未落盘的准备阶段日志，并保持准备日志在前。"""
    file_lines = file_text.splitlines()
    file_line_set = set(file_lines)
    pending_lines = [line for line in memory_lines if line and line not in file_line_set]
    return "\n".join(pending_lines + file_lines)


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
                [progress_block[0], progress_block[middle_index], progress_block[-1]]
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


class ProjectDetail(Vertical):
    """封装项目详情标签、产物展示和 Zotero 局部上下文。"""

    def __init__(
        self,
        engine: str,
        adapter_factory: Callable[[str, str], ZoteroAdapter],
        id: str = "detail",
    ) -> None:
        """初始化详情上下文和唯一 Zotero 面板实例。"""
        super().__init__(id=id)
        self.effective_engine = normalize_engine(engine)
        self.project: ProjectViewState | None = None
        self.task_id: str | None = None
        self.task_log_lines: list[str] = []
        self.zotero_panel = ZoteroPanel(adapter_factory=adapter_factory)

    def compose(self) -> ComposeResult:
        """构建详情标签及各类只读产物控件。"""
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
            yield self.zotero_panel

    def on_mount(self) -> None:
        """挂载后应用构造阶段记录的引擎标签状态。"""
        self.set_engine(self.effective_engine)

    def set_engine(self, engine: str) -> None:
        """记录引擎，并在挂载后更新详情标签显隐和首选标签。"""
        self.effective_engine = normalize_engine(engine)
        if not self.is_mounted:
            return
        tabs = self.query_one("#detail-tabs", DetailTabbedContent)
        visible_ids = (
            {
                "source-markdown-tab",
                "translated-markdown-tab",
                "terms-tab",
                "log-tab",
                "zotero-tab",
            }
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
        previous_active = tabs.active
        preferred_tab = (
            "source-markdown-tab" if self.effective_engine == "lite" else "tex-tab"
        )
        for tab_id in visible_ids:
            tabs.show_tab(tab_id)
        if previous_active not in visible_ids:
            tabs.active = preferred_tab
        for tab_id in all_ids - visible_ids:
            tabs.hide_tab(tab_id)

    def show_project(
        self,
        project: ProjectViewState | None,
        *,
        task_id: str | None,
        task_log_lines: list[str],
        input_type: str,
        arxiv_id: str,
        zotero_config: dict[str, object],
        reset_zotero: bool = False,
    ) -> None:
        """记录完整项目上下文并刷新当前项目的只读产物。"""
        self.project = project
        self.task_id = task_id
        self.task_log_lines = list(task_log_lines)
        self.zotero_panel.set_context(
            project=project,
            task_id=task_id,
            input_type=input_type,
            arxiv_id=arxiv_id,
            engine=self.effective_engine,
            config=zotero_config,
            reset_selection=reset_zotero,
        )
        if not self.is_mounted:
            return
        if project is None:
            self._clear_project_views()
            return
        if project.engine == "lite":
            self._refresh_markdown_previews(project)
        else:
            self._refresh_tex_preview(project)
            self._refresh_errors_table(project)
        self._refresh_project_log(project)
        self._refresh_terms_table(project)

    def refresh_log(self, task_log_lines: list[str]) -> None:
        """复制任务日志快照并只刷新当前项目日志。"""
        self.task_log_lines = list(task_log_lines)
        if self.is_mounted and self.project is not None:
            self._refresh_project_log(self.project)

    def refresh_log_and_terms(self, task_log_lines: list[str]) -> None:
        """刷新日志后额外刷新术语表，不重读其他产物。"""
        self.refresh_log(task_log_lines)
        if self.is_mounted and self.project is not None:
            self._refresh_terms_table(self.project)

    def refresh_selected_errors_table(self) -> None:
        """依据当前项目和真实可视宽度重画错误记录表。"""
        if self.project is not None:
            self._refresh_errors_table(self.project)

    def on_error_reports_table_resize_requested(
        self,
        message: ErrorReportsTable.ResizeRequested,
    ) -> None:
        """消费错误表尺寸消息并在布局刷新后重画列。"""
        message.stop()
        self.call_after_refresh(self.refresh_selected_errors_table)

    def on_tabbed_content_tab_activated(
        self,
        event: TabbedContent.TabActivated,
    ) -> None:
        """在详情内部处理错误表重画和 Zotero 库加载。"""
        if event.tabbed_content.id != "detail-tabs":
            return
        if event.pane.id == "errors-tab":
            event.stop()
            self.call_after_refresh(self.refresh_selected_errors_table)
        elif event.pane.id == "zotero-tab":
            event.stop()
            self.zotero_panel.load_zotero_libraries()

    def _clear_project_views(self) -> None:
        """清空已展示项目内容，不读取任何产物路径。"""
        self.query_one("#tex-preview", Static).update("")
        self.query_one("#source-markdown-preview", Static).update("")
        self.query_one("#translated-markdown-preview", Static).update("")
        self.query_one("#project-log", RichLog).clear()
        self.query_one("#terms-table", DataTable).clear(columns=True)
        self.query_one("#errors-table", DataTable).clear(columns=True)

    def _refresh_tex_preview(self, project: ProjectViewState) -> None:
        """加载首个 TeX 源文件作为只读预览。"""
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
        """展示 Lite 项目的源 Markdown 和译文 Markdown。"""
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
        """展示单个 Markdown 产物或清楚的不可用提示。"""
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
        """寻找适合作为项目预览的 TeX 文件。"""
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

    def _refresh_project_log(self, project: ProjectViewState) -> None:
        """把任务快照、项目内存日志和日志文件合并到日志面板。"""
        log_widget = self.query_one("#project-log", RichLog)
        log_widget.clear()
        memory_lines = [*self.task_log_lines, *project.log_lines]
        if project.log_path is None:
            for line in memory_lines:
                log_widget.write(line)
            return
        try:
            log_text = Path(project.log_path).read_text(encoding="utf-8")
            log_text = _merge_project_log_text(log_text, memory_lines)
            log_text = compact_progress_log_for_display(log_text)
        except OSError as exc:
            log_text = (
                "\n".join(memory_lines)
                if memory_lines
                else f"无法读取日志文件：{exc}"
            )
        log_widget.write(log_text)

    def _refresh_errors_table(self, project: ProjectViewState) -> None:
        """重画错误记录表并展示内容及解决状态。"""
        table = self.query_one("#errors-table", ErrorReportsTable)
        cursor = table.cursor_coordinate
        scroll_x, scroll_y = table.scroll_x, table.scroll_y
        table.clear(columns=True)
        widths = self._errors_column_widths(table)
        for label, width in zip(
            ("位置", "类型", "问题", "状态", "原文", "译文"),
            widths,
        ):
            table.add_column(label, width=width)
        for report, status in self._error_reports_with_status(project):
            source, translation = error_reports.error_report_content(report, project)
            table.add_row(
                error_reports.error_report_position(report),
                error_reports.error_report_type(report),
                self._truncated_plain_text(
                    error_reports.error_report_problem(report), widths[2]
                ),
                self._error_status_text(status),
                self._truncated_plain_text(source, widths[4]),
                self._truncated_plain_text(translation, widths[5]),
                height=1,
            )
            row = table.row_count - 1
            table.set_cell_tooltip(row, 0, error_reports.error_report_position(report))
            table.set_cell_tooltip(row, 2, error_reports.error_report_problem(report))
            table.set_cell_tooltip(row, 4, source)
            table.set_cell_tooltip(row, 5, translation)
        if table.row_count:
            table.move_cursor(
                row=min(cursor.row, table.row_count - 1),
                column=min(cursor.column, 5),
                scroll=False,
            )
        table.scroll_to(x=scroll_x, y=scroll_y, animate=False)

    def _errors_column_widths(
        self,
        table: DataTable,
    ) -> tuple[int, int, int, int, int, int]:
        """按错误表可视宽度分配固定列宽。"""
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
        content_width = max(
            content_budget - fixed_width,
            ERROR_MIN_CONTENT_COLUMN_WIDTH * 2,
        )
        source_width = max(ERROR_MIN_CONTENT_COLUMN_WIDTH, content_width // 2)
        translation_width = max(
            ERROR_MIN_CONTENT_COLUMN_WIDTH,
            content_width - source_width,
        )
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
        tabs_width = self.query_one("#detail-tabs").size.width
        if tabs_width:
            return tabs_width
        if self.size.width:
            return self.size.width
        screen_width = self.screen.size.width if self.screen else 0
        return max((screen_width * 4) // 5, 80)

    def _error_reports_with_status(
        self,
        project: ProjectViewState,
    ) -> list[tuple[dict[str, object], str]]:
        """解析报告路径并获取带解决状态的记录。"""
        path = error_reports.project_errors_report_path(project)
        if path is not None:
            project.errors_report_path = str(path)
        return error_reports.error_reports_with_status(project, path)

    def _error_status_text(self, status: str) -> Text:
        """返回仅状态单元格使用的彩色 Rich 文本。"""
        if status == "resolved":
            return Text("已解决", style="green")
        if status == "warning":
            return Text("警告", style="yellow")
        return Text("未解决", style="yellow")

    def _truncated_plain_text(self, value: str, width: int) -> Text:
        """按列宽截断普通文本，不对内容本身额外高亮。"""
        collapsed = re.sub(r"\s+", " ", value).strip()
        limit = max(width, 3)
        if len(collapsed) > limit:
            collapsed = collapsed[: max(limit - 3, 0)] + "..."
        return Text(collapsed, overflow="ellipsis", no_wrap=True)

    def _refresh_terms_table(self, project: ProjectViewState) -> None:
        """刷新选中项目的只读术语表。"""
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
        """返回项目术语 CSV 路径，并支持输出目录回填。"""
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




