"""Textual terminal UI entry point."""

from __future__ import annotations

import argparse
import re
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Literal, Sequence

from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.css.query import NoMatches
from textual.containers import Horizontal, Vertical
from textual.widgets import (
    Button,
    ContentSwitcher,
    DataTable,
    Footer,
    ListItem,
    ListView,
    Rule,
    Select,
    Static,
    Switch,
    TextArea,
)

from src.tui.config import UI_CONFIG_PATH, load_ui_config
from src.tui.config_page import ConfigPage
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
from src.tui.project_detail import (
    ProjectDetail,
    _merge_project_log_text,
    compact_progress_log_for_display,
)
from src.tui.runner import run_tui_task as _DEFAULT_RUN_TUI_TASK
from src.tui.runner import run_tui_task
from src.tui.state import ProjectStatus, ProjectViewState, TaskViewState
from src.tui.widgets import (
    APP_TITLE_ART,
    APP_TITLE_ART_COMPACT,
    APP_TITLE_LINE_STYLES,
    APP_TITLE_LITE_LINE_STYLES,
    APP_TITLE_PLAIN,
    ConfigTabbedContent,
    DetailTabbedContent,
    EntryBatchTextArea,
    ErrorReportsTable,
    ProjectManagementTable,
    ResponsiveAppTitle,
    ZoteroResultsTable,
    ZoteroSearchInput,
    app_title_art_width,
    build_app_title,
    build_app_title_for_width,
    build_art_title,
)
from src.tui.zotero_adapter import ZoteroAdapter
from src.tui.zotero_panel import ZoteroPanel

PAGE_ENTRY = "entry"
PAGE_DETAIL = "detail"
PAGE_TASKS = "tasks"
PAGE_CONFIG = "config"
NOTIFY_MESSAGE_LIMIT = 400
NOTIFICATION_SEVERITY = Literal["information", "warning", "error"]


def _compact_notification(message: str, limit: int = NOTIFY_MESSAGE_LIMIT) -> str:
    """把通知文本压成单段可读文本，过长时保留开头并加省略号。"""
    collapsed = " ".join(str(message).split())
    if len(collapsed) <= limit:
        return collapsed
    return f"{collapsed[:limit]} …"


class LaTeXTransTuiApp(App[None]):
    """Main Textual application for LaTeXTransPlus."""

    CSS_PATH = "app.tcss"

    current_task: TaskViewState | None = None
    tasks: list[TaskViewState]
    selected_project_name: str | None = None
    selected_task_id: str | None = None
    selected_project_keys: set[tuple[str, str]]
    _default_zotero_adapter_factory = staticmethod(
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
        self.config_page = ConfigPage(self.effective_engine)
        self.project_detail = ProjectDetail(
            self.effective_engine,
            adapter_factory=self._default_zotero_adapter_factory,
        )
        self.current_task = None
        self.tasks = []
        self.selected_project_name = None
        self.selected_task_id = None
        self.selected_project_keys = set()
        self.load_history_on_mount = load_history_on_mount
        self.task_processes: dict[str, TuiTaskProcess] = {}
        self.cancelled_task_ids: set[str] = set()

    @property
    def current_config(self) -> dict[str, object]:
        """提供当前配置快照的兼容读取入口。"""
        return self.config_page.get_config()

    @current_config.setter
    def current_config(self, config: dict[str, object]) -> None:
        """把兼容赋值转交配置页的唯一状态。"""
        self.config_page.set_config(config)

    @property
    def zotero_adapter_factory(self) -> Callable[[str, str], ZoteroAdapter]:
        """提供直接代理面板 adapter 工厂的兼容入口。"""
        project_detail = self.__dict__.get("project_detail")
        if isinstance(project_detail, ProjectDetail):
            return project_detail.zotero_panel.adapter_factory
        return self._default_zotero_adapter_factory

    @zotero_adapter_factory.setter
    def zotero_adapter_factory(
        self,
        factory: Callable[[str, str], ZoteroAdapter],
    ) -> None:
        """把运行时注入的 adapter 工厂直接写入面板。"""
        project_detail = self.__dict__.get("project_detail")
        if isinstance(project_detail, ProjectDetail):
            project_detail.zotero_panel.adapter_factory = factory

    @property
    def zotero_panel(self) -> ZoteroPanel:
        """提供详情组件唯一 Zotero 面板的兼容入口。"""
        return self.project_detail.zotero_panel

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
                yield self.project_detail
                with Vertical(id=PAGE_TASKS):
                    with Horizontal(id="project-actions"):
                        yield Button("终止翻译", id="terminate-translation-button", flat=True, disabled=True)
                        yield Button("删除", id="delete-project-button", flat=True, disabled=True)
                        yield Button("重新翻译", id="retry-translation-button", flat=True, disabled=True)
                    yield ProjectManagementTable(id="task-table", cursor_type="row")
                yield self.config_page
        yield Footer()

    def on_mount(self) -> None:
        """Load existing output projects into the sidebar when the app starts."""
        self._apply_engine_view(rebuild_config_form=False)
        if not self.load_history_on_mount:
            return
        self.theme = "nord"
        self.load_output_history()

    def set_engine(self, engine: str, persist: bool = False) -> None:
        """Select the engine for this UI session and optionally save a future default."""
        self.effective_engine = normalize_engine(engine)
        self.config_page.set_engine(self.effective_engine, rebuild=False)
        self.project_detail.set_engine(self.effective_engine)
        if not self.is_running:
            return
        self._apply_engine_view(rebuild_config_form=True)
        if self.load_history_on_mount:
            self.load_output_history()
        if persist:
            self.config_page.save_default_engine(self.effective_engine)

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
        self.project_detail.set_engine(self.effective_engine)
        self._clear_incompatible_selected_project()
        self.config_page.set_engine(
            self.effective_engine,
            rebuild=rebuild_config_form,
        )
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
        self.refresh_detail_page(reset_zotero=True)
        self.switch_page(PAGE_DETAIL)

    def refresh_project_list(self) -> None:
        """Refresh the left-side project list from all known task states."""
        list_view = self.query_one("#project-list", ListView)
        list_view.clear()

        for task, project in self._iter_project_states():
            text = project.project_name + (f" · {project.title}" if project.title else "")
            label = Static(Text(text, overflow="ellipsis", no_wrap=True))
            tooltip = Text(project.project_name + "\n" + (project.title or "未识别标题"))
            label.tooltip = tooltip
            if self._task_is_running(task):
                label.add_class("running-task-project")
            item = ListItem(label)
            item.tooltip = tooltip
            list_view.append(item)

    def refresh_detail_page(self, *, reset_zotero: bool = False) -> None:
        """解析完整项目身份并把展示上下文交给详情组件。"""
        project = self._selected_project()
        selected_task: TaskViewState | None = None
        if project is not None:
            selected_task = next(
                (
                    task
                    for task, candidate in self._iter_project_states()
                    if candidate is project
                    and (
                        self.selected_task_id is None
                        or task.task_id == self.selected_task_id
                    )
                ),
                None,
            )
        config = self.current_config
        zotero_config = config.get("zotero", {}) if isinstance(config, dict) else {}
        self.project_detail.show_project(
            project,
            task_id=selected_task.task_id if selected_task is not None else None,
            task_log_lines=(
                selected_task.task_log_lines if selected_task is not None else []
            ),
            input_type=selected_task.input_type if selected_task is not None else "",
            arxiv_id=self._arxiv_id_for_project(project, selected_task),
            zotero_config=zotero_config if isinstance(zotero_config, dict) else {},
            reset_zotero=reset_zotero,
        )

    def refresh_task_table(self) -> None:
        """Refresh the project management table from all known task states."""
        table = self.query_one("#task-table", ProjectManagementTable)
        project_states = self._iter_project_states()
        valid_keys = {(task.task_id, project.project_name) for task, project in project_states}
        self.selected_project_keys.intersection_update(valid_keys)
        cursor = table.cursor_coordinate
        scroll_x, scroll_y = table.scroll_x, table.scroll_y
        table.clear(columns=True)
        for label, width in zip(
            ("选中", "项目", "标题", "翻译模型", "状态", "任务 id"),
            self._project_column_widths(table),
        ):
            table.add_column(label, width=width)

        for task, project in project_states:
            key = (task.task_id, project.project_name)
            table.add_row(
                "[√]" if key in self.selected_project_keys else "[]",
                Text(project.project_name, overflow="ellipsis", no_wrap=True),
                Text(project.title or "未识别标题", overflow="ellipsis", no_wrap=True),
                Text(project.translation_model or "unknown", overflow="ellipsis", no_wrap=True),
                project.status.value,
                task.task_id,
            )
        if table.row_count:
            table.move_cursor(row=min(cursor.row, table.row_count - 1), column=min(cursor.column, 5), scroll=False)
        table.scroll_to(x=scroll_x, y=scroll_y, animate=False)
        self._refresh_project_action_buttons()

    def _project_column_widths(self, table: DataTable) -> tuple[int, int, int, int, int, int]:
        """将剩余可视宽度分配给标题；窄屏保留最小宽度并允许横向滚动。"""
        available = table.size.width or self.query_one("#main-switcher").size.width
        fixed = (4, 18, 20, 17, 23)
        title_width = max(18, available - sum(fixed) - 12 * table.cell_padding - 2)
        return fixed[0], fixed[1], title_width, fixed[2], fixed[3], fixed[4]

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
        """切换项目管理表结果行的选中状态。"""
        if event.data_table.id == "task-table":
            table = event.data_table
            if getattr(table, "_suppress_next_row_selected", False):
                table._suppress_next_row_selected = False
                return
            if event.cursor_row is not None:
                self._toggle_project_selection(event.cursor_row)

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
        elif event.button.id == "terminate-translation-button":
            if hasattr(self, "_terminate_selected_projects"):
                self._terminate_selected_projects()
        elif event.button.id == "delete-project-button":
            if hasattr(self, "_delete_selected_projects"):
                self._delete_selected_projects()
        elif event.button.id == "retry-translation-button":
            if hasattr(self, "_retry_selected_projects"):
                self._retry_selected_projects()

    def on_switch_changed(self, event: Switch.Changed) -> None:
        """入口引擎开关变化时切换当前会话。"""
        if event.switch.id == "engine-mode-switch":
            self.set_engine("lite" if event.value else "heavy")

    def on_config_page_config_changed(self, message: ConfigPage.ConfigChanged) -> None:
        """接收配置变化通知，不在 App 中缓存第二份配置。"""
        message.stop()
        zotero_config = message.config.get("zotero", {})
        self.zotero_panel.update_config(
            zotero_config if isinstance(zotero_config, dict) else {}
        )

    def on_zotero_panel_status_changed(
        self,
        message: ZoteroPanel.StatusChanged,
    ) -> None:
        """将 Zotero 面板状态转交统一通知入口。"""
        message.stop()
        self._notify(message.message)

    def load_config_page(self) -> None:
        """委托配置页加载配置和填充表单。"""
        self.config_page.load_config()

    def persist_config_form_change(self) -> None:
        """委托配置页保存当前表单。"""
        self.config_page.persist_form()

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
        """仅将当前任务项目的日志事件交给详情组件。"""
        event_type = event.get("type")
        if event_type not in {"project_log", "task_log"}:
            return
        project = self._selected_project()
        target_task = task or self.current_task
        if project is None or target_task is None:
            return
        if target_task.task_id != self.selected_task_id:
            return
        if event_type == "project_log" and project.project_name != str(
            event.get("project_name") or ""
        ):
            return
        if event_type == "task_log":
            self.project_detail.refresh_log(target_task.task_log_lines)
        else:
            self.project_detail.refresh_log_and_terms(target_task.task_log_lines)

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
                    # 历史配置可能使用相对路径，运行事件则使用绝对路径。
                    output_dir = Path(project.output_dir).resolve()
                    merged = [
                        history_task
                        for history_task in merged
                        if not any(
                            history_project.output_dir
                            and Path(history_project.output_dir).resolve() == output_dir
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
        if event_type not in {"project_start", "project_metadata", "project_complete", "project_error", "project_cancelled"}:
            return
        project_name = str(event.get("project_name") or "")
        project = next(
            (item for item in task.projects if item.project_name == project_name),
            None,
        )
        output_dir = event.get("output_dir") or (project.output_dir if project else None)
        if not output_dir or not project_name:
            return
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
            title=project.title if project else None,
            translation_model=project.translation_model if project else None,
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

    def load_zotero_libraries(self) -> None:
        """同步可替换工厂并委托面板加载 Zotero 库。"""
        self._sync_zotero_adapter_factory()
        self.zotero_panel.load_zotero_libraries()

    def search_zotero_items(self) -> None:
        """同步可替换工厂并委托面板搜索条目。"""
        self._sync_zotero_adapter_factory()
        self.zotero_panel.search_zotero_items()

    def auto_match_zotero_items(self) -> None:
        """同步可替换工厂并委托面板自动匹配。"""
        self._sync_zotero_adapter_factory()
        self.zotero_panel.auto_match_zotero_items()

    def populate_zotero_results(self, results: list[dict[str, object]]) -> None:
        """委托面板写入 Zotero 搜索结果。"""
        self.zotero_panel.populate_zotero_results(results)

    def clear_zotero_results(self) -> None:
        """委托面板清空 Zotero 搜索结果和选择状态。"""
        self.zotero_panel.clear_zotero_results()

    def toggle_zotero_row_selection(self, row_index: int) -> None:
        """委托面板切换指定 Zotero 结果行。"""
        self.zotero_panel.toggle_zotero_row_selection(row_index)

    def import_selected_project_to_zotero(self) -> None:
        """同步可替换工厂并委托面板导入 PDF。"""
        self._sync_zotero_adapter_factory()
        self.zotero_panel.import_selected_project_to_zotero()

    def import_selected_project_markdown_to_zotero(self) -> None:
        """同步可替换工厂并委托面板导入 Markdown。"""
        self._sync_zotero_adapter_factory()
        self.zotero_panel.import_selected_project_markdown_to_zotero()

    def _sync_zotero_adapter_factory(self) -> None:
        """把调用方最新注入的 Zotero 工厂同步给面板。"""
        self.zotero_panel.adapter_factory = self.zotero_adapter_factory

    def _arxiv_id_for_project(
        self,
        project: ProjectViewState | None,
        task: TaskViewState | None,
    ) -> str:
        """按项目名优先、所属任务输入其次提取 arXiv ID。"""
        pattern = re.compile(r"\d{4}\.\d{4,5}(?:v\d+)?")
        candidates: list[str] = []
        if project is not None:
            candidates.append(project.project_name)
        if task is not None:
            candidates.extend(task.inputs)
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
