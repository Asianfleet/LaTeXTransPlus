import hashlib
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from rich.cells import cell_len
from rich.syntax import Syntax
from rich.text import Text
from textual.css.query import NoMatches
from textual.widgets import (
    Button,
    ContentSwitcher,
    DataTable,
    Footer,
    Input,
    ListView,
    RichLog,
    Rule,
    Select,
    Static,
    Switch,
    TabbedContent,
    TextArea,
)

from setup import load_requirements
from src.tui import app as tui_app
from src.tui.app import (
    PAGE_CONFIG,
    PAGE_DETAIL,
    PAGE_ENTRY,
    PAGE_TASKS,
    LaTeXTransTuiApp,
    _merge_project_log_text,
    build_app_title,
    compact_progress_log_for_display,
    run,
)
from src.tui.history import TUI_PROJECT_METADATA_FILENAME
from src.tui.config import UI_CONFIG_PATH
from src.tui.state import ProjectStatus, ProjectViewState, TaskViewState


def _file_sha256(path: Path) -> str:
    """Return a file digest without exposing its contents in test output."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


class TuiPackagingTests(unittest.TestCase):
    """验证 Textual TUI 的打包依赖和入口。"""

    def test_textual_dependency_is_declared(self):
        """确认 requirements 声明 Textual 依赖。"""
        requirements = load_requirements("requirements.txt")
        self.assertTrue(any(item.startswith("textual") for item in requirements))

    def test_tui_run_function_is_importable(self):
        """确认 TUI run 函数可以被 console script 导入。"""
        from src.tui.app import run

        self.assertTrue(callable(run))

    def test_run_short_engine_flag_overrides_persisted_default(self):
        """The short CLI engine flag must win without persisting a configuration change."""
        with patch("src.tui.app.load_ui_config", return_value={"engine": "heavy"}), patch(
            "src.tui.app.LaTeXTransTuiApp"
        ) as app_class:
            run(["-e", "lite"])

        app_class.assert_called_once_with(initial_engine="lite")
        app_class.return_value.run.assert_called_once_with()

    def test_run_uses_persisted_engine_when_cli_does_not_override_it(self):
        """The saved UI engine is the startup default when CLI omits --engine."""
        with patch("src.tui.app.load_ui_config", return_value={"engine": "lite"}), patch(
            "src.tui.app.LaTeXTransTuiApp"
        ) as app_class:
            run([])

        app_class.assert_called_once_with(initial_engine="lite")


class TuiAppTests(unittest.IsolatedAsyncioTestCase):
    """为所有 TUI 测试隔离真实项目配置文件。"""

    async def asyncSetUp(self) -> None:
        """在整个异步测试生命周期内拦截 UI 配置保存。"""
        self._ui_config_hash = _file_sha256(Path.cwd() / UI_CONFIG_PATH)
        self.save_ui_config = Mock()
        self._save_ui_config_patchers = [
            patch("src.tui.app.save_ui_config", self.save_ui_config),
            patch("src.tui.config.save_ui_config", self.save_ui_config),
        ]
        for save_ui_config_patcher in self._save_ui_config_patchers:
            save_ui_config_patcher.start()

    async def asyncTearDown(self) -> None:
        """在异步测试完成后恢复 UI 配置保存函数。"""
        try:
            self.assertEqual(
                _file_sha256(Path.cwd() / UI_CONFIG_PATH),
                self._ui_config_hash,
                "TUI 测试不得修改真实 UI 配置文件。",
            )
        finally:
            for save_ui_config_patcher in reversed(self._save_ui_config_patchers):
                save_ui_config_patcher.stop()


class TuiEngineModeTests(TuiAppTests):
    """Verify the TUI keeps heavy and lite session state isolated."""

    async def test_initial_engine_mount_does_not_persist_configuration(self):
        """Mounting an engine-specific form must not overwrite the saved UI default."""
        app = LaTeXTransTuiApp(load_history_on_mount=False, initial_engine="lite")
        async with app.run_test() as pilot:
            await pilot.pause()

        self.save_ui_config.assert_not_called()

    async def test_settings_default_engine_persists_without_changing_active_session(self):
        """Changing the saved default engine must leave the current Heavy session intact."""
        app = LaTeXTransTuiApp(load_history_on_mount=False, initial_engine="heavy")
        with patch("src.tui.app.load_ui_config", return_value={"engine": "heavy"}):
            async with app.run_test() as pilot:
                await app.workers.wait_for_complete()
                await pilot.pause()
                app.load_config_page()
                await app.workers.wait_for_complete()
                await pilot.pause()
                self.assertFalse(app.loading_config_form)
                self.save_ui_config.reset_mock()

                app.query_one("#config-engine", Select).value = "lite"
                await pilot.pause()

                saved_config = self.save_ui_config.call_args.args[1]
                self.assertEqual(saved_config["engine"], "lite")
                self.assertEqual(app.effective_engine, "heavy")
                self.assertFalse(app.query_one("#engine-mode-switch", Switch).value)
                self.assertEqual(app.query_one("#input-type-select", Select).value, "arxiv")

    async def test_lite_mode_hides_heavy_tabs_and_shows_markdown_tabs(self):
        """Lite mode must expose Markdown details instead of TeX validation details."""
        app = LaTeXTransTuiApp(load_history_on_mount=False, initial_engine="lite")
        async with app.run_test() as pilot:
            await pilot.pause()
            self.assertFalse(app.query_one("#tex-tab").display)
            self.assertFalse(app.query_one("#errors-tab").display)
            tabs = app.query_one("#detail-tabs", TabbedContent)
            self.assertFalse(tabs.get_tab("source-markdown-tab").has_class("-hidden"))
            self.assertFalse(tabs.get_tab("translated-markdown-tab").has_class("-hidden"))

    async def test_mode_switch_is_session_only_and_preserves_existing_task_engine(self):
        """Changing the mode must not write config or alter an already-created task."""
        app = LaTeXTransTuiApp(load_history_on_mount=False, initial_engine="heavy")
        existing_task = TaskViewState(input_type="arxiv", inputs=["2508.18791"], engine="heavy")
        app.tasks = [existing_task]
        async with app.run_test() as pilot:
            await pilot.pause()
            self.save_ui_config.reset_mock()
            app.set_engine("lite")
            await app.workers.wait_for_complete()
            await pilot.pause()

            self.assertEqual(app.effective_engine, "lite")
            self.assertEqual(existing_task.engine, "heavy")
            self.save_ui_config.assert_not_called()

    async def test_lite_mode_submits_one_pdf_task_and_rejects_batch_text(self):
        """Lite entry creates a PDF task only after its single value validates."""
        app = LaTeXTransTuiApp(load_history_on_mount=False, initial_engine="lite")
        async with app.run_test():
            input_area = app.query_one("#batch-input", TextArea)
            input_area.text = "first.pdf, second.pdf"
            app.submit_entry_form()
            self.assertIsNone(app.current_task)
            self.assertIn("exactly one", str(app.query_one("#entry-error", Static).content))

            input_area.text = "paper.pdf"
            with patch.object(app, "start_current_task"), patch.object(app, "notify"):
                app.submit_entry_form()

            self.assertIsNotNone(app.current_task)
            self.assertEqual(app.current_task.engine, "lite")
            self.assertEqual(app.current_task.input_type, "pdf")
            self.assertEqual(app.current_task.inputs, ["paper.pdf"])

    async def test_lite_entry_select_is_labeled_as_auto_detection(self):
        """Lite entry uses one visible input choice labeled for automatic detection."""
        app = LaTeXTransTuiApp(load_history_on_mount=False, initial_engine="lite")
        async with app.run_test() as pilot:
            await pilot.pause()
            select = app.query_one("#input-type-select", Select)

            self.assertEqual(select._options[1], ("自动识别", "pdf"))

    async def test_engine_mode_switch_aligns_with_entry_select(self):
        """The session mode switch starts at the same x-coordinate as the input select."""
        app = LaTeXTransTuiApp(load_history_on_mount=False)
        async with app.run_test() as pilot:
            await pilot.pause()
            input_select = app.query_one("#input-type-select", Select)
            mode_switch = app.query_one("#engine-mode-switch", Switch)

            self.assertEqual(mode_switch.region.x, input_select.region.x)

    async def test_engine_mode_control_has_spacing_below_entry_actions(self):
        """模式开关行与入口操作行之间保留一个终端行的间距。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False)
        async with app.run_test() as pilot:
            await pilot.pause()
            mode_control = app.query_one("#engine-mode-control")

            self.assertEqual(mode_control.styles.margin.top, 1)

    async def test_lite_settings_only_show_shared_and_lite_fields(self):
        """The settings form must not show heavy-only runtime controls in lite mode."""
        app = LaTeXTransTuiApp(load_history_on_mount=False, initial_engine="lite")
        async with app.run_test() as pilot:
            await pilot.pause()
            self.assertIsNotNone(app.query_one("#config-engine", Select))
            self.assertIsNotNone(app.query_one("#config-lite-output_dir", Input))
            with self.assertRaises(NoMatches):
                app.query_one("#config-heavy-tex_sources_dir", Input)
            with self.assertRaises(NoMatches):
                app.query_one("#config-heavy-validation-retry-max_attempts", Input)

    async def test_switching_to_lite_rebuilds_settings_fields(self):
        """Mode changes replace heavy settings fields with lite settings fields."""
        app = LaTeXTransTuiApp(load_history_on_mount=False, initial_engine="heavy")
        async with app.run_test() as pilot:
            app.set_engine("lite")
            await app.workers.wait_for_complete()
            await pilot.pause()

            self.assertIsNotNone(app.query_one("#config-lite-output_dir", Input))
            with self.assertRaises(NoMatches):
                app.query_one("#config-heavy-tex_sources_dir", Input)

    async def test_lite_settings_expose_the_mineru_api_key_env_field(self):
        """Lite settings must let users change the MinerU token environment variable."""
        app = LaTeXTransTuiApp(load_history_on_mount=False, initial_engine="lite")
        async with app.run_test() as pilot:
            await pilot.pause()
            app.load_config_page()

            field = app.query_one("#config-lite-mineru_api_key_env", Input)

            self.assertEqual(field.value, "MINERU_TOKEN")

    async def test_heavy_settings_hide_the_lite_mineru_api_key_env_field(self):
        """The lite MinerU token env field must stay out of the heavy settings form."""
        app = LaTeXTransTuiApp(load_history_on_mount=False, initial_engine="heavy")
        async with app.run_test() as pilot:
            await pilot.pause()
            app.load_config_page()

            with self.assertRaises(NoMatches):
                app.query_one("#config-lite-mineru_api_key_env", Input)

    async def test_mode_switch_filters_project_views_by_task_engine(self):
        """Sidebar and management rows only show tasks created in the active mode."""
        app = LaTeXTransTuiApp(load_history_on_mount=False, initial_engine="heavy")
        heavy_task = TaskViewState(input_type="arxiv", inputs=["heavy"], engine="heavy")
        heavy_task.projects.append(ProjectViewState(project_name="heavy-project", engine="heavy"))
        lite_task = TaskViewState(input_type="pdf", inputs=["lite.pdf"], engine="lite")
        lite_task.projects.append(ProjectViewState(project_name="lite-project", engine="lite"))
        app.tasks = [heavy_task, lite_task]
        async with app.run_test() as pilot:
            app.refresh_project_list()
            self.assertIn(
                "heavy-project",
                str(app.query_one("#project-list", ListView).children[0].query_one(Static).content),
            )

            app.set_engine("lite")
            await app.workers.wait_for_complete()
            await pilot.pause()
            labels = [
                str(item.query_one(Static).content)
                for item in app.query_one("#project-list", ListView).children
            ]
            self.assertEqual(labels, ["lite-project"])

    async def test_lite_detail_renders_markdown_and_reports_missing_artifact(self):
        """Lite detail tabs render Markdown syntax and make a missing file explicit."""
        app = LaTeXTransTuiApp(load_history_on_mount=False, initial_engine="lite")
        with TemporaryDirectory() as temp_dir:
            source_path = Path(temp_dir) / "source.md"
            source_path.write_text("## Source\ntext", encoding="utf-8")
            async with app.run_test() as pilot:
                task = TaskViewState(input_type="pdf", inputs=["paper.pdf"], engine="lite")
                project = ProjectViewState(
                    project_name="paper",
                    engine="lite",
                    source_markdown_path=str(source_path),
                    translated_markdown_path=str(Path(temp_dir) / "translated.md"),
                )
                task.projects.append(project)
                app.tasks = [task]
                app.select_project("paper", task.task_id)
                await pilot.pause()

                source_preview = app.query_one("#source-markdown-preview", Static)
                translated_preview = app.query_one("#translated-markdown-preview", Static)
                self.assertIsInstance(source_preview.content, Syntax)
                self.assertIn("## Source", source_preview.content.code)
                self.assertIn("Markdown 文件不存在", str(translated_preview.content))


class TuiLayoutTests(TuiAppTests):
    """验证 Textual TUI 首版主布局和页面切换行为。"""

    async def test_app_composes_sidebar_switcher_and_footer(self):
        """确认应用组合侧栏、主内容切换器和底部快捷键区域。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False)
        async with app.run_test():
            self.assertIsNotNone(app.query_one("#project-list", ListView))
            self.assertIsNotNone(app.query_one("#main-switcher", ContentSwitcher))
            self.assertIsNotNone(app.query_one(Footer))

    async def test_tex_preview_uses_rich_latex_syntax_widget(self):
        """确认 TeX 预览使用离线 Rich LaTeX 高亮控件。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False)
        async with app.run_test():
            from textual.widgets import Static

            tex_preview = app.query_one("#tex-preview", Static)

            self.assertEqual(tex_preview.id, "tex-preview")

    def test_detail_page_adds_top_padding_above_tabs(self):
        """确认项目详情页顶部和 Tab 标签之间保留间距。"""
        self.assertIn("#detail {", LaTeXTransTuiApp.DEFAULT_CSS)
        self.assertIn("padding-top: 1;", LaTeXTransTuiApp.DEFAULT_CSS)

    def test_entry_form_allows_wide_art_title(self):
        """确认入口表单宽度足够容纳多行艺术字标题。"""
        self.assertIn("#entry-form {", LaTeXTransTuiApp.DEFAULT_CSS)
        self.assertIn("max-width: 124;", LaTeXTransTuiApp.DEFAULT_CSS)

    def test_app_title_keeps_art_lines_left_aligned(self):
        """确认艺术字内部不逐行居中，避免短行错位。"""
        self.assertIsNone(build_app_title().justify)
        self.assertNotIn("text-align: center;", LaTeXTransTuiApp.DEFAULT_CSS)
        self.assertIn("height: 6;", LaTeXTransTuiApp.DEFAULT_CSS)

    def test_compact_art_title_is_narrower_than_wide_title(self):
        """确认窄版艺术字存在，并且宽度小于宽屏艺术字。"""
        compact_art = getattr(tui_app, "APP_TITLE_ART_COMPACT", "")
        self.assertNotEqual("", compact_art)
        wide_width = max(cell_len(line) for line in tui_app.APP_TITLE_ART.splitlines())
        compact_width = max(cell_len(line) for line in compact_art.splitlines())
        self.assertLess(compact_width, wide_width)

    def test_app_title_selects_responsive_variant_for_width(self):
        """确认标题按可用宽度选择宽版、窄版和普通标题。"""
        title_for_width = getattr(tui_app, "build_app_title_for_width", None)
        self.assertIsNotNone(title_for_width)

        wide_width = tui_app.app_title_art_width(tui_app.APP_TITLE_ART)
        compact_width = tui_app.app_title_art_width(tui_app.APP_TITLE_ART_COMPACT)

        self.assertEqual(title_for_width(wide_width).plain, tui_app.APP_TITLE_ART)
        self.assertEqual(title_for_width(wide_width - 1).plain, tui_app.APP_TITLE_ART_COMPACT)
        self.assertEqual(title_for_width(compact_width - 1).plain, "LaTeXTransPlus")

    async def test_detail_page_applies_top_padding_above_tabs(self):
        """确认项目详情页实际应用顶部间距。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False)
        async with app.run_test():
            self.assertEqual(app.query_one("#detail").styles.padding.top, 1)

    async def test_detail_page_keeps_zotero_controls_inside_tab(self):
        """确认详情页把 Zotero 控件放进独立 tab，而不是放在 tab 下方。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False)
        async with app.run_test():
            detail = app.query_one("#detail")
            self.assertEqual([child.id for child in detail.children], ["detail-tabs"])
            zotero_tab = app.query_one("#zotero-tab")
            self.assertEqual([child.id for child in zotero_tab.children], ["zotero-controls", "zotero-results"])
            self.assertEqual(
                [child.id for child in app.query_one("#zotero-controls").children],
                [
                    "zotero-library-select",
                    "zotero-search-input",
                    "zotero-search-button",
                    "zotero-auto-match-button",
                    "zotero-import-rule",
                    "import-zotero-button",
                    "import-zotero-markdown-button",
                ],
            )
            self.assertIsNotNone(app.query_one("#zotero-library-select", Select))
            self.assertIsNotNone(app.query_one("#zotero-search-input", Input))
            self.assertIsNotNone(app.query_one("#zotero-search-button", Button))
            self.assertIsNotNone(app.query_one("#zotero-auto-match-button", Button))
            self.assertIsNotNone(app.query_one("#zotero-import-rule", Rule))
            self.assertIsNotNone(app.query_one("#import-zotero-button", Button))
            self.assertIsNotNone(app.query_one("#import-zotero-markdown-button", Button))
            self.assertIsNotNone(app.query_one("#zotero-results", DataTable))
            with self.assertRaises(NoMatches):
                app.query_one("#detail-paths")
            with self.assertRaises(NoMatches):
                app.query_one("#open-output-button")

    async def test_zotero_controls_match_select_row_height(self):
        """确认 Zotero 操作栏控件使用和入口页相同的三行高样式。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False)
        async with app.run_test() as pilot:
            app.switch_page(PAGE_DETAIL)
            app.query_one("#detail-tabs", TabbedContent).active = "zotero-tab"
            await pilot.pause()

            zotero_controls = app.query_one("#zotero-controls")
            library_select = app.query_one("#zotero-library-select", Select)
            search_input = app.query_one("#zotero-search-input", Input)
            search_button = app.query_one("#zotero-search-button", Button)
            auto_match_button = app.query_one("#zotero-auto-match-button", Button)
            import_button = app.query_one("#import-zotero-button", Button)

            self.assertEqual(zotero_controls.region.height, library_select.region.height)
            self.assertEqual(library_select.region.height, 3)
            self.assertEqual(search_input.region.y, library_select.region.y)
            self.assertEqual(search_button.region.y, library_select.region.y)
            self.assertEqual(auto_match_button.region.y, library_select.region.y)
            self.assertEqual(import_button.region.y, library_select.region.y)
            self.assertEqual(search_input.region.height, library_select.region.height)
            self.assertEqual(search_button.region.height, library_select.region.height)
            self.assertEqual(auto_match_button.region.height, library_select.region.height)
            self.assertEqual(import_button.region.height, library_select.region.height)
            self.assertLess(search_button.region.width, auto_match_button.region.width)
            self.assertLess(import_button.region.width, auto_match_button.region.width)
            self.assertTrue(search_button.flat)
            self.assertTrue(auto_match_button.flat)
            self.assertTrue(import_button.flat)
            self.assertEqual(search_button.styles.border.top[0], search_input.styles.border.top[0])
            self.assertEqual(auto_match_button.styles.border.top[0], search_input.styles.border.top[0])
            self.assertEqual(import_button.styles.border.top[0], search_input.styles.border.top[0])
            self.assertEqual(search_button.styles.border.top[0], "tall")

    async def test_empty_detail_tables_fill_available_tab_height(self):
        """确认空术语表和错误记录表仍占满详情 tab 的剩余高度。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False)
        async with app.run_test(size=(120, 40)) as pilot:
            app.current_task = TaskViewState(input_type="local", inputs=["paper"])
            app.current_task.projects.append(ProjectViewState(project_name="paper", status=ProjectStatus.COMPLETED))
            app.selected_project_name = "paper"
            app.refresh_detail_page()
            app.switch_page(PAGE_DETAIL)

            tabs = app.query_one("#detail-tabs", TabbedContent)
            for tab_id, table_id in [("terms-tab", "terms-table"), ("errors-tab", "errors-table")]:
                tabs.active = tab_id
                await pilot.pause()

                table = app.query_one(f"#{table_id}", DataTable)

                self.assertEqual(table.row_count, 0)
                self.assertGreater(table.region.height, 10)

    async def test_switch_page_updates_content_switcher(self):
        """确认 switch_page 会更新主内容切换器当前页面。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False)
        async with app.run_test():
            for page_id in [PAGE_ENTRY, PAGE_DETAIL, PAGE_TASKS, PAGE_CONFIG]:
                app.switch_page(page_id)
                self.assertEqual(
                    app.query_one("#main-switcher", ContentSwitcher).current,
                    page_id,
                )

    async def test_progress_widgets_are_not_composed(self):
        """确认进度页组件已从主布局移除。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False)
        async with app.run_test():
            with self.assertRaises(NoMatches):
                app.query_one("#progress-summary")
            with self.assertRaises(NoMatches):
                app.query_one("#task-progress")
            with self.assertRaises(NoMatches):
                app.query_one("#event-log")


class TuiEntryPageTests(TuiAppTests):
    """验证入口页提交会创建任务状态并展示校验错误。"""

    async def test_entry_page_uses_centered_initial_form_layout(self):
        """确认入口页使用居中的标题、输入框、下拉菜单和发送按钮布局。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False)
        async with app.run_test():
            title_content = app.query_one("#app-title", Static).content
            self.assertIsInstance(title_content, Text)
            title_plain = title_content.plain
            self.assertGreaterEqual(len(title_plain.splitlines()), 6)
            self.assertIn("████████", title_plain)
            self.assertIn("╚══════╝", title_plain)
            self.assertIsNotNone(app.query_one("#entry-form"))
            self.assertIsNotNone(app.query_one("#entry-actions"))

            form_children = [child.id for child in app.query_one("#entry-form").children]
            self.assertEqual(
                form_children,
                [
                    "entry-top-spacer",
                    "app-title",
                    "entry-actions",
                    "engine-mode-control",
                    "entry-error",
                    "entry-bottom-offset",
                    "entry-bottom-spacer",
                ],
            )
            action_children = [child.id for child in app.query_one("#entry-actions").children]
            self.assertEqual(action_children, ["input-type-select", "batch-input", "start-task-button"])
            self.assertEqual(str(app.query_one("#start-task-button", Button).label), "发送")

    async def test_entry_controls_match_select_row_height(self):
        """确认入口页输入控件位于同一行，并匹配 select 的真实高度。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False)
        async with app.run_test() as pilot:
            await pilot.pause()

            entry_actions = app.query_one("#entry-actions")
            input_type_select = app.query_one("#input-type-select", Select)
            batch_input = app.query_one("#batch-input", TextArea)
            start_button = app.query_one("#start-task-button", Button)

            self.assertEqual(entry_actions.region.height, input_type_select.region.height)
            self.assertEqual(input_type_select.region.height, 3)
            self.assertEqual(batch_input.region.y, input_type_select.region.y)
            self.assertEqual(start_button.region.y, input_type_select.region.y)
            self.assertEqual(batch_input.region.height, input_type_select.region.height)
            self.assertEqual(start_button.region.height, input_type_select.region.height)
            self.assertTrue(start_button.flat)
            self.assertEqual(start_button.styles.border.top[0], batch_input.styles.border.top[0])
            self.assertEqual(start_button.styles.border.top[0], "tall")

    async def test_entry_actions_are_vertically_centered_in_entry_page(self):
        """确认入口页把输入组件行作为垂直居中的布局锚点。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False)
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()

            entry = app.query_one("#entry")
            entry_actions = app.query_one("#entry-actions")

            entry_center = entry.region.y + entry.region.height / 2
            actions_center = entry_actions.region.y + entry_actions.region.height / 2

            self.assertLessEqual(abs(actions_center - entry_center), 1)

    async def test_entry_title_updates_for_terminal_width(self):
        """确认终端变窄时标题从宽版艺术字降级到窄版和普通标题。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False)
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            title = app.query_one("#app-title", Static)
            self.assertEqual(title.content.plain, tui_app.APP_TITLE_ART)

            await pilot.resize_terminal(90, 40)
            await pilot.pause()
            self.assertEqual(title.content.plain, tui_app.APP_TITLE_ART_COMPACT)

            await pilot.resize_terminal(30, 40)
            await pilot.pause()
            self.assertEqual(title.content.plain, "LaTeXTransPlus")

    async def test_submit_entry_form_creates_task_stays_on_entry_and_notifies(self):
        """确认有效入口表单会创建任务、留在入口页并发出开始通知。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False)
        async with app.run_test():
            app.query_one("#input-type-select", Select).value = "arxiv"
            app.query_one("#batch-input", TextArea).text = "2508.18791\n2407.01648"

            with patch.object(app, "start_current_task") as start_current_task:
                with patch.object(app, "notify") as notify:
                    app.submit_entry_form()

            self.assertIsInstance(app.current_task, TaskViewState)
            self.assertEqual(app.current_task.inputs, ["2508.18791", "2407.01648"])
            self.assertEqual(app.query_one("#main-switcher", ContentSwitcher).current, PAGE_ENTRY)
            self.assertIn(app.current_task.task_id, notify.call_args.args[0])
            start_current_task.assert_called_once_with()

    async def test_submit_entry_form_clears_input_after_successful_submission(self):
        """确认成功提交任务后入口输入框会自动清空。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False)
        async with app.run_test():
            app.query_one("#input-type-select", Select).value = "arxiv"
            batch_input = app.query_one("#batch-input", TextArea)
            batch_input.text = "2508.18791"

            with patch.object(app, "start_current_task"), patch.object(app, "notify"):
                app.submit_entry_form()

            self.assertEqual(batch_input.text, "")

    async def test_start_button_submits_entry_form_without_leaving_entry_page(self):
        """确认开始按钮提交入口表单后仍留在入口页。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False)
        async with app.run_test() as pilot:
            app.query_one("#input-type-select", Select).value = "arxiv"
            app.query_one("#batch-input", TextArea).text = "2508.18791"

            with patch.object(app, "start_current_task") as start_current_task:
                with patch.object(app, "notify"):
                    await pilot.click("#start-task-button")
                    await pilot.pause()

            self.assertIsInstance(app.current_task, TaskViewState)
            self.assertEqual(app.query_one("#main-switcher", ContentSwitcher).current, PAGE_ENTRY)
            start_current_task.assert_called_once_with()

    async def test_enter_submits_entry_form_while_batch_input_is_focused(self):
        """确认入口页文本框聚焦时按 Enter 会发送任务。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False)
        async with app.run_test() as pilot:
            app.query_one("#input-type-select", Select).value = "arxiv"
            batch_input = app.query_one("#batch-input", TextArea)
            batch_input.text = "2508.18791"
            batch_input.focus()

            with patch.object(app, "start_current_task") as start_current_task:
                with patch.object(app, "notify"):
                    await pilot.press("enter")
                    await pilot.pause()

            self.assertIsInstance(app.current_task, TaskViewState)
            self.assertEqual(app.current_task.inputs, ["2508.18791"])
            start_current_task.assert_called_once_with()

    async def test_entry_page_footer_does_not_show_tab_shortcuts(self):
        """确认入口页不会把设置页和详情页快捷键显示成全局 Footer 提示。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False)
        async with app.run_test() as pilot:
            await pilot.pause()

            active_shortcuts = set(app.active_bindings)

            self.assertNotIn("c", active_shortcuts)
            self.assertNotIn("p", active_shortcuts)
            self.assertNotIn("t", active_shortcuts)
            self.assertNotIn("r", active_shortcuts)
            self.assertNotIn("e", active_shortcuts)
            self.assertNotIn("l", active_shortcuts)
            self.assertNotIn("z", active_shortcuts)

    async def test_submit_entry_form_notifies_with_timestamp_task_id(self):
        """确认任务开始通知包含新建任务 id。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False)
        async with app.run_test():
            app.query_one("#input-type-select", Select).value = "arxiv"
            app.query_one("#batch-input", TextArea).text = "2508.18791"

            with patch.object(app, "start_current_task"), patch.object(app, "notify") as notify:
                app.submit_entry_form()

            self.assertIsInstance(app.current_task, TaskViewState)
            self.assertIn("任务已开始", notify.call_args.args[0])
            self.assertIn(app.current_task.task_id, notify.call_args.args[0])

    async def test_submit_entry_form_shows_validation_errors(self):
        """确认无效入口表单会在入口页展示校验错误。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False)
        async with app.run_test():
            app.query_one("#input-type-select", Select).value = "remote"
            app.query_one("#batch-input", TextArea).text = "file:///bad.zip"

            app.submit_entry_form()

            self.assertIn("remote input must be", str(app.query_one("#entry-error", Static).content))
            self.assertEqual(app.query_one("#batch-input", TextArea).text, "file:///bad.zip")
            self.assertIsNone(app.current_task)
            self.assertEqual(app.query_one("#main-switcher", ContentSwitcher).current, PAGE_ENTRY)

    async def test_submit_entry_form_requires_input_type_when_select_is_blank(self):
        """确认输入类型为空但文本非空时提示选择输入类型且不创建任务。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False)
        async with app.run_test():
            app.query_one("#input-type-select", Select).clear()
            app.query_one("#batch-input", TextArea).text = "2508.18791"

            app.submit_entry_form()

            self.assertIn("请选择输入类型", str(app.query_one("#entry-error", Static).content))
            self.assertIsNone(app.current_task)
            self.assertEqual(app.query_one("#main-switcher", ContentSwitcher).current, PAGE_ENTRY)


class TuiTaskProjectSemanticsTests(TuiAppTests):
    """验证任务历史和项目列表遵循一次提交一个任务的语义。"""

    async def test_sequential_single_id_tasks_keep_both_projects_in_sidebar(self):
        """确认连续提交两个单项目任务后，侧栏项目列表不会丢失第一个项目。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False)

        async with app.run_test() as pilot:
            for arxiv_id in ["2308.10248", "2311.06668"]:
                app.query_one("#input-type-select", Select).value = "arxiv"
                app.query_one("#batch-input", TextArea).text = arxiv_id
                with patch.object(app, "start_current_task"):
                    app.submit_entry_form()
                app.handle_runtime_event(
                    {"type": "project_complete", "project_name": arxiv_id},
                    app.current_task,
                )

            await pilot.pause()
            list_view = app.query_one("#project-list", ListView)
            labels = [str(item.query_one(Static).content) for item in list_view.children]

            self.assertEqual(len(app.tasks), 2)
            self.assertEqual(len(list_view.children), 2)
            self.assertIn("2308.10248", labels[0])
            self.assertIn("2311.06668", labels[1])

    async def test_batch_ids_are_one_task_with_multiple_project_rows(self):
        """确认一次输入多个 ID 会创建一个任务，并在项目管理中展开多个项目。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False)

        async with app.run_test():
            app.query_one("#input-type-select", Select).value = "arxiv"
            app.query_one("#batch-input", TextArea).text = "2308.10248\n2311.06668"
            with patch.object(app, "start_current_task"):
                app.submit_entry_form()

            task = app.current_task
            app.handle_runtime_event({"type": "project_start", "project_name": "2308.10248"}, task)
            app.handle_runtime_event({"type": "project_complete", "project_name": "2308.10248"}, task)
            app.handle_runtime_event({"type": "project_start", "project_name": "2311.06668"}, task)

            table = app.query_one("#task-table", DataTable)

            self.assertEqual(len(app.tasks), 1)
            self.assertEqual(str(table.ordered_columns[0].label), "选中")
            self.assertEqual(str(table.ordered_columns[1].label), "项目")
            self.assertEqual(str(table.ordered_columns[2].label), "状态")
            self.assertEqual(str(table.ordered_columns[3].label), "任务 id")
            self.assertEqual(len(table.ordered_columns), 4)
            self.assertEqual(table.row_count, 2)
            self.assertEqual(table.get_cell_at((0, 3)), task.task_id)
            self.assertEqual(table.get_cell_at((1, 3)), task.task_id)

    async def test_sidebar_marks_projects_from_running_task_orange(self):
        """确认左侧项目属于进行中任务时用橙色文字展示。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False)

        async with app.run_test() as pilot:
            running_task = TaskViewState(input_type="arxiv", inputs=["done", "running"], task_id="task-1", total=2)
            running_task.completed = 1
            running_task.projects.append(ProjectViewState(project_name="done", status=ProjectStatus.COMPLETED))
            running_task.projects.append(ProjectViewState(project_name="running", status=ProjectStatus.RUNNING))
            finished_task = TaskViewState(input_type="arxiv", inputs=["finished"], task_id="task-2", total=1)
            finished_task.completed = 1
            finished_task.projects.append(ProjectViewState(project_name="finished", status=ProjectStatus.COMPLETED))
            app.tasks = [running_task, finished_task]

            app.refresh_project_list()
            await pilot.pause()

            list_view = app.query_one("#project-list", ListView)
            running_labels = [list_view.children[index].query_one(Static) for index in (0, 1)]
            finished_label = list_view.children[2].query_one(Static)
            self.assertIn("running-task-project", running_labels[0].classes)
            self.assertIn("running-task-project", running_labels[1].classes)
            self.assertNotIn("running-task-project", finished_label.classes)

    async def test_sidebar_does_not_mark_terms_ready_task_orange(self):
        """确认等待术语确认的项目已停止，不应按进行中任务染色。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False)

        async with app.run_test() as pilot:
            task = TaskViewState(input_type="arxiv", inputs=["paper"], task_id="task-1", total=1)
            task.projects.append(ProjectViewState(project_name="paper", status=ProjectStatus.TERMS_READY))
            app.tasks = [task]

            app.refresh_project_list()
            await pilot.pause()

            list_view = app.query_one("#project-list", ListView)
            label = list_view.children[0].query_one(Static)
            self.assertNotIn("running-task-project", label.classes)

    async def test_sidebar_selection_uses_project_task_identity(self):
        """确认侧栏选择项目时按任务 id 和项目名定位详情。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False)

        async with app.run_test():
            first_task = TaskViewState(input_type="arxiv", inputs=["paper"], task_id="task-1")
            first_task.projects.append(ProjectViewState(project_name="paper", status=ProjectStatus.COMPLETED))
            second_task = TaskViewState(input_type="arxiv", inputs=["paper"], task_id="task-2")
            second_task.projects.append(ProjectViewState(project_name="paper", status=ProjectStatus.RUNNING))
            app.tasks = [first_task, second_task]
            app.current_task = second_task
            app.refresh_project_list()

            event = Mock()
            event.list_view = app.query_one("#project-list", ListView)
            event.index = 1
            app.on_list_view_selected(event)

            self.assertEqual(app.selected_task_id, "task-2")
            self.assertEqual(app.selected_project_name, "paper")
            self.assertEqual(app.query_one("#main-switcher", ContentSwitcher).current, PAGE_DETAIL)

    async def test_mount_loads_existing_outputs_into_sidebar(self):
        """确认打开 TUI 时左侧列表会包含 outputs 中已有项目。"""
        with TemporaryDirectory() as temp_dir:
            output_root = Path(temp_dir) / "outputs"
            project_dir = output_root / "ch_2308.10248"
            project_dir.mkdir(parents=True)
            (project_dir / "ch_2308.10248.pdf").write_bytes(b"%PDF")
            (project_dir / "errors_report.json").write_text("[]", encoding="utf-8")

            app = LaTeXTransTuiApp()
            with patch.object(LaTeXTransTuiApp, "_history_output_root", return_value=output_root):
                async with app.run_test() as pilot:
                    await pilot.pause()

                    list_view = app.query_one("#project-list", ListView)
                    table = app.query_one("#task-table", DataTable)

                    self.assertEqual(len(list_view.children), 1)
                    self.assertIn("2308.10248", str(list_view.children[0].query_one(Static).content))
                    self.assertEqual(table.get_cell_at((0, 0)), "[]")
                    self.assertEqual(table.get_cell_at((0, 1)), "2308.10248")
                    self.assertEqual(table.get_cell_at((0, 2)), "completed")
                    self.assertEqual(table.get_cell_at((0, 3)), "")

    async def test_selecting_history_project_loads_tex_preview(self):
        """确认点击历史项目时右侧 TeX 页能显示项目源码。"""
        with TemporaryDirectory() as temp_dir:
            output_root = Path(temp_dir) / "outputs"
            project_dir = output_root / "ch_2308.10248"
            source_dir = project_dir / "2308.10248"
            source_dir.mkdir(parents=True)
            (source_dir / "main.tex").write_text("\\documentclass{article}", encoding="utf-8")
            (project_dir / "errors_report.json").write_text("[]", encoding="utf-8")
            (project_dir / "ch_2308.10248.pdf").write_bytes(b"%PDF")

            app = LaTeXTransTuiApp()
            with patch.object(LaTeXTransTuiApp, "_history_output_root", return_value=output_root):
                async with app.run_test() as pilot:
                    await pilot.pause()
                    app.select_project("2308.10248")
                    await pilot.pause()

                    tex_preview = app.query_one("#tex-preview", Static)
                    self.assertIn("\\documentclass{article}", tex_preview.content.code)
                    self.assertEqual(app.query_one("#main-switcher", ContentSwitcher).current, PAGE_DETAIL)

    async def test_submit_entry_form_uses_timestamp_task_id(self):
        """确认新任务 id 使用时间戳格式而不是递增序号。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False)

        async with app.run_test():
            app.query_one("#input-type-select", Select).value = "arxiv"
            app.query_one("#batch-input", TextArea).text = "2308.10248"
            with patch.object(app, "start_current_task"), patch(
                "src.tui.app.datetime"
            ) as datetime_module:
                datetime_module.now.return_value.strftime.return_value = "20260701T175144.123000"
                app.submit_entry_form()

            self.assertEqual(app.current_task.task_id, "20260701T175144.123")

    async def test_project_completion_writes_tui_metadata(self):
        """确认新版项目完成事件会在输出目录写入 TUI 元数据。"""
        with TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "outputs" / "ch_2308.10248"
            output_dir.mkdir(parents=True)
            app = LaTeXTransTuiApp(load_history_on_mount=False)

            async with app.run_test():
                app.current_task = TaskViewState(
                    input_type="arxiv",
                    inputs=["2308.10248"],
                    task_id="20260701T175144.123",
                )
                app.tasks = [app.current_task]

                app.handle_runtime_event(
                    {
                        "type": "project_complete",
                        "project_name": "2308.10248",
                        "output_dir": str(output_dir),
                    },
                    app.current_task,
                )

            self.assertTrue((output_dir / TUI_PROJECT_METADATA_FILENAME).is_file())


class TuiConfigPageTests(TuiAppTests):
    """验证配置页会加载、编辑并保存 UI 配置。"""

    async def test_settings_button_loads_structured_config_tabs(self):
        """确认设置按钮会打开配置 tabs 并按字段类型填充表单。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False)
        config = {
            "sys_name": "LaTeXTransPlus",
            "version": "0.1.0",
            "engine": "heavy",
            "source_language": "en",
            "target_language": "ja",
            "category": {"cs": ["cs.LG"]},
            "update_term": "True",
            "mode": "plain",
            "user_term": "terms/user.csv",
            "terminology": {
                "enabled": True,
                "review_before_translate": False,
                "max_llm_candidates": 30,
            },
            "heavy": {
                "paper_list": ["2508.18791", "2407.01648"],
                "tex_sources_dir": "tex source",
                "output_dir": "outputs",
                "validation": {
                    "retry": {
                        "max_attempts": 3,
                        "generate_pdf_on_error": True,
                        "fail_on_error": True,
                    },
                    "issues": {
                        "command_mismatch": {"severity": "error", "retryable": True},
                        "placeholder_mismatch": {"severity": "warning", "retryable": False},
                        "bracket_mismatch": {"severity": "error", "retryable": True},
                    },
                },
            },
            "lite": {"output_dir": "output-lite"},
            "llm_config": {
                "profile": "deepseek",
            },
            "zotero": {
                "local_api_base": "http://127.0.0.1:23119/api",
                "web_api_key_env": "ZOTERO_API_KEY",
            },
        }
        async with app.run_test() as pilot:
            with patch("src.tui.app.save_ui_config"):
                with patch("src.tui.app.load_ui_config", return_value=config):
                    await pilot.click("#settings-button")
                await pilot.pause()

                self.assertEqual(app.query_one("#main-switcher", ContentSwitcher).current, PAGE_CONFIG)
                self.assertIsNotNone(app.query_one("#config-tabs", TabbedContent))
                self.assertEqual(app.query_one("#config-target_language", Select).value, "ja")
                self.assertEqual(app.query_one("#config-source_language", Select).value, "en")
                self.assertTrue(app.query_one("#config-update_term", Switch).value)
                self.assertEqual(
                    app.query_one("#config-heavy-validation-issues-placeholder_mismatch-severity", Select).value,
                    "warning",
                )
                self.assertFalse(app.query_one("#config-heavy-validation-issues-placeholder_mismatch-retryable", Switch).value)
                self.assertEqual(
                    app.query_one("#config-zotero-local_api_base", Input).value,
                    "http://127.0.0.1:23119/api",
                )
                self.assertEqual(app.query_one("#config-zotero-web_api_key_env", Input).value, "ZOTERO_API_KEY")
                self.assertIn('target_language = "ja"', app.query_one("#config-preview", TextArea).text)
                self.assertIn("[zotero]", app.query_one("#config-preview", TextArea).text)
                with self.assertRaises(NoMatches):
                    app.query_one("#config-sys_name", Input)
                with self.assertRaises(NoMatches):
                    app.query_one("#config-version", Input)
                with self.assertRaises(NoMatches):
                    app.query_one("#config-paper_list", TextArea)

    async def test_config_page_has_no_manual_save_or_reload_buttons(self):
        """确认配置页不再提供保存或重载按钮，避免手动保存语义漂移。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False)
        async with app.run_test():
            self.assertIsNotNone(app.query_one("#config-tabs", TabbedContent))
            with self.assertRaises(NoMatches):
                app.query_one("#save-config-button")
            with self.assertRaises(NoMatches):
                app.query_one("#reload-config-button")

    async def test_config_form_scrolls_in_both_engine_modes(self):
        """配置表单在 heavy 和 lite 模式的小终端中都必须提供垂直滚动。"""
        for engine in ("heavy", "lite"):
            app = LaTeXTransTuiApp(load_history_on_mount=False, initial_engine=engine)
            async with app.run_test(size=(100, 24)) as pilot:
                app.switch_page(PAGE_CONFIG)
                await pilot.pause()
                config_form = app.query_one("#config-form", tui_app.VerticalScroll)

                self.assertGreater(
                    config_form.max_scroll_y,
                    0,
                    f"{engine} 配置表单必须超过视口并可滚动",
                )
                config_form.scroll_end(animate=False)
                await pilot.pause()
                self.assertGreater(config_form.scroll_y, 0)

    async def test_config_page_shortcuts_switch_config_and_preview_tabs(self):
        """确认设置页 c/p 快捷键会切换配置和预览 tab。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False)
        async with app.run_test() as pilot:
            app.switch_page(PAGE_CONFIG)
            tabs = app.query_one("#config-tabs", TabbedContent)
            app.query_one("#config-tabs ContentTabs").focus()

            await pilot.press("p")
            await pilot.pause()
            self.assertEqual(tabs.active, "config-preview-tab")

            await pilot.press("c")
            await pilot.pause()
            self.assertEqual(tabs.active, "config-form-tab")

    async def test_config_tab_shortcuts_show_only_when_config_tabs_are_focused(self):
        """确认设置页快捷键只在设置 tab 组件上下文中显示。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False)
        async with app.run_test() as pilot:
            app.switch_page(PAGE_CONFIG)
            await pilot.pause()
            self.assertNotIn("p", set(app.active_bindings))

            app.query_one("#config-tabs ContentTabs").focus()
            await pilot.pause()

            active_shortcuts = set(app.active_bindings)
            self.assertIn("c", active_shortcuts)
            self.assertIn("p", active_shortcuts)
            self.assertNotIn("t", active_shortcuts)

    async def test_zotero_search_input_enter_triggers_search(self):
        """确认 Zotero 搜索输入框聚焦时按 Enter 会触发搜索。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False)
        async with app.run_test() as pilot:
            app.switch_page(PAGE_DETAIL)
            app.query_one("#detail-tabs ContentTabs").focus()
            app.query_one("#detail-tabs").active = "zotero-tab"
            search_input = app.query_one("#zotero-search-input", Input)
            search_input.value = "Paper"
            search_input.focus()

            with patch.object(app, "search_zotero_items") as search:
                await pilot.press("enter")
                await pilot.pause()

            search.assert_called_once_with()

    async def test_zotero_search_input_footer_shows_enter_search(self):
        """确认 Zotero 搜索输入框聚焦时 Footer 显示 Enter=搜索。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False)
        async with app.run_test() as pilot:
            app.switch_page(PAGE_DETAIL)
            app.query_one("#detail-tabs ContentTabs").focus()
            app.query_one("#detail-tabs").active = "zotero-tab"
            search_input = app.query_one("#zotero-search-input", Input)
            search_input.focus()
            await pilot.pause()

            self.assertIn("enter", set(app.active_bindings))
            self.assertEqual(app.active_bindings["enter"].binding.description, "搜索")

    async def test_config_field_change_persists_immediately_and_refreshes_preview(self):
        """确认配置字段变化后会即时保存 UI 配置并刷新 TOML 预览。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False)
        async with app.run_test() as pilot:
            with patch("src.tui.app.save_ui_config") as save_config:
                with patch("src.tui.app.load_ui_config", return_value={"target_language": "ja"}):
                    app.load_config_page()

                app.query_one("#config-target_language", Select).value = "fr"
                app.persist_config_form_change()
                await pilot.pause()

            self.assertEqual(save_config.call_args.args[1]["target_language"], "fr")
            preview = app.query_one("#config-preview", TextArea).text
            self.assertIn('target_language = "fr"', preview)

    async def test_delayed_config_change_uses_lifecycle_save_mock(self):
        """确认延迟处理的配置变更不会越过测试生命周期写入真实文件。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False)
        async with app.run_test() as pilot:
            with patch("src.tui.app.load_ui_config", return_value={"llm_config": {"profile": "profile-ja"}}):
                app.load_config_page()
            await app.workers.wait_for_complete()
            await pilot.pause()

            self.assertFalse(app.loading_config_form)
            self.save_ui_config.assert_not_called()
            app.query_one("#config-llm_config-profile", Input).value = "profile-fr"
            await pilot.pause(delay=0.1)

            self.save_ui_config.assert_called_once()
            saved_config = self.save_ui_config.call_args.args[1]
            self.assertEqual(saved_config["llm_config"]["profile"], "profile-fr")

    async def test_config_change_collects_form_fields_and_preserves_metadata(self):
        """确认即时保存会从结构化表单写回配置并保留不可编辑元数据。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False)
        config = {
            "sys_name": "LaTeXTransPlus",
            "version": "0.1.0",
            "engine": "heavy",
            "source_language": "en",
            "target_language": "ja",
            "category": {},
            "update_term": "False",
            "mode": "plain",
            "user_term": "",
            "terminology": {"enabled": True, "review_before_translate": False, "max_llm_candidates": 30},
            "heavy": {
                "paper_list": ["2508.18791"],
                "tex_sources_dir": "tex source",
                "output_dir": "outputs",
                "validation": {
                    "retry": {"max_attempts": 3, "generate_pdf_on_error": True, "fail_on_error": True},
                    "issues": {
                        "command_mismatch": {"severity": "error", "retryable": True},
                        "placeholder_mismatch": {"severity": "error", "retryable": True},
                        "bracket_mismatch": {"severity": "error", "retryable": True},
                    },
                },
            },
            "lite": {"output_dir": "output-lite"},
            "llm_config": {
                "profile": "deepseek",
            },
            "zotero": {
                "local_api_base": "http://127.0.0.1:23119/api",
                "web_api_key_env": "ZOTERO_API_KEY",
            },
        }
        async with app.run_test() as pilot:
            with patch("src.tui.app.save_ui_config") as save_config:
                with patch("src.tui.app.load_ui_config", return_value=config):
                    app.load_config_page()

                app.query_one("#config-target_language", Select).value = "fr"
                app.query_one("#config-source_language", Select).value = "de"
                app.query_one("#config-category", TextArea).text = '{"cs": ["cs.LG"]}'
                app.query_one("#config-update_term", Switch).value = True
                app.query_one("#config-terminology-max_llm_candidates", Input).value = "12"
                app.query_one("#config-heavy-validation-retry-max_attempts", Input).value = "2"
                app.query_one("#config-heavy-validation-issues-command_mismatch-severity", Select).value = "warning"
                app.query_one("#config-heavy-validation-issues-command_mismatch-retryable", Switch).value = False
                app.query_one("#config-llm_config-profile", Input).value = "profile-x"
                app.query_one("#config-zotero-local_api_base", Input).value = "http://localhost:23119/api"
                app.query_one("#config-zotero-web_api_key_env", Input).value = "MY_ZOTERO_API_KEY"
                app.persist_config_form_change()

                saved = save_config.call_args.args[1]
                await pilot.pause()
            self.assertEqual(saved["sys_name"], "LaTeXTransPlus")
            self.assertEqual(saved["version"], "0.1.0")
            self.assertEqual(saved["target_language"], "fr")
            self.assertEqual(saved["source_language"], "de")
            self.assertEqual(saved["heavy"]["paper_list"], ["2508.18791"])
            self.assertEqual(saved["category"], {"cs": ["cs.LG"]})
            self.assertEqual(saved["update_term"], "True")
            self.assertEqual(saved["terminology"]["max_llm_candidates"], 12)
            self.assertEqual(saved["heavy"]["validation"]["retry"]["max_attempts"], 2)
            self.assertEqual(saved["heavy"]["validation"]["issues"]["command_mismatch"]["severity"], "warning")
            self.assertFalse(saved["heavy"]["validation"]["issues"]["command_mismatch"]["retryable"])
            self.assertEqual(saved["llm_config"]["profile"], "profile-x")
            self.assertEqual(saved["zotero"]["local_api_base"], "http://localhost:23119/api")
            self.assertEqual(saved["zotero"]["web_api_key_env"], "MY_ZOTERO_API_KEY")
            self.assertIn('target_language = "fr"', app.query_one("#config-preview", TextArea).text)

    async def test_config_change_rejects_invalid_integer_fields(self):
        """确认非法整数配置会显示错误并阻止即时保存。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False)
        async with app.run_test():
            with patch("src.tui.app.load_ui_config", return_value={"terminology": {"max_llm_candidates": 30}}):
                app.load_config_page()

            app.query_one("#config-terminology-max_llm_candidates", Input).value = "-1"
            with patch("src.tui.app.save_ui_config") as save_config:
                app.persist_config_form_change()

            save_config.assert_not_called()
            self.assertIn("非负整数", str(app.query_one("#config-error", Static).content))


class TuiTaskEventTests(TuiAppTests):
    """验证任务 runtime 事件会刷新状态并触发通知。"""

    async def test_handle_runtime_event_updates_task_and_log(self):
        """确认 runtime 事件会更新当前任务状态。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False)
        async with app.run_test():
            app.current_task = TaskViewState(input_type="arxiv", inputs=["2508.18791"])

            app.handle_runtime_event({"type": "run_start", "total": 1})
            app.handle_runtime_event({"type": "project_start", "project_name": "2508.18791"})
            app.handle_runtime_event(
                {"type": "project_complete", "project_name": "2508.18791", "pdf_path": "paper.pdf"}
            )

            self.assertEqual(app.current_task.completed, 1)
            self.assertGreaterEqual(len(app.current_task.events), 3)

    async def test_project_complete_notifies_project_and_task_completion_once(self):
        """确认项目完成和整任务完成都会通知，整任务完成不会重复通知。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False)
        async with app.run_test():
            app.current_task = TaskViewState(
                input_type="arxiv",
                inputs=["2508.18791"],
                task_id="task-1",
                total=1,
            )
            app.tasks = [app.current_task]

            with patch.object(app, "notify") as notify:
                app.handle_runtime_event(
                    {"type": "project_complete", "project_name": "2508.18791"},
                    app.current_task,
                )
                app.handle_runtime_event(
                    {"type": "project_complete", "project_name": "2508.18791"},
                    app.current_task,
                )

            messages = [call.args[0] for call in notify.call_args_list]
            self.assertEqual(messages.count("任务全部完成：task-1"), 1)
            self.assertTrue(any("项目完成：2508.18791" in message for message in messages))

    async def test_duplicate_project_terminal_events_notify_project_once(self):
        """确认同一项目重复终态事件不会重复弹项目级通知。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False)
        async with app.run_test():
            app.current_task = TaskViewState(
                input_type="arxiv",
                inputs=["2508.18791"],
                task_id="task-1",
                total=1,
            )
            app.tasks = [app.current_task]

            with patch.object(app, "notify") as notify:
                app.handle_runtime_event(
                    {"type": "project_error", "project_name": "2508.18791", "error": "first"},
                    app.current_task,
                )
                app.handle_runtime_event(
                    {"type": "project_error", "project_name": "2508.18791", "error": "second"},
                    app.current_task,
                )

            messages = [call.args[0] for call in notify.call_args_list]
            self.assertEqual(
                len([message for message in messages if "发生异常：2508.18791" in message]),
                1,
            )

    async def test_project_error_notifies_exception_and_task_completion(self):
        """确认项目异常会发出异常通知，并在任务结束时通知全部完成。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False)
        async with app.run_test():
            app.current_task = TaskViewState(
                input_type="arxiv",
                inputs=["2508.18791"],
                task_id="task-1",
                total=1,
            )
            app.tasks = [app.current_task]

            with patch.object(app, "notify") as notify:
                app.handle_runtime_event(
                    {"type": "project_error", "project_name": "2508.18791", "error": "runner failed"},
                    app.current_task,
                )

            messages = [call.args[0] for call in notify.call_args_list]
            self.assertTrue(any("发生异常：2508.18791" in message for message in messages))
            self.assertTrue(any("runner failed" in message for message in messages))
            self.assertIn("任务全部完成：task-1", messages)

    async def test_validation_project_error_notification_includes_summary(self):
        """校验失败事件缺少 error 时也应展示剩余错误数和报告路径。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False)
        async with app.run_test():
            app.current_task = TaskViewState(
                input_type="arxiv",
                inputs=["2508.18791"],
                task_id="task-validation-error",
                total=1,
            )
            app.tasks = [app.current_task]

            with patch.object(app, "notify") as notify:
                app.handle_runtime_event(
                    {
                        "type": "project_error",
                        "project_name": "2508.18791",
                        "validation_summary": {"warnings": 1, "errors": 2, "total": 3},
                        "errors_report_path": r"D:\out\errors_report.json",
                    },
                    app.current_task,
                )

            messages = [call.args[0] for call in notify.call_args_list]
            self.assertTrue(any("remaining validation errors: 2" in message for message in messages))
            self.assertTrue(any(r"D:\out\errors_report.json" in message for message in messages))

    async def test_review_required_event_notifies_terms_ready_and_task_completion(self):
        """确认等待术语确认不会弹异常通知，且会结束当前任务。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False)
        async with app.run_test():
            app.current_task = TaskViewState(
                input_type="arxiv",
                inputs=["2508.18791"],
                task_id="task-1",
                total=1,
            )
            app.tasks = [app.current_task]

            with patch.object(app, "notify") as notify:
                app.handle_runtime_event(
                    {
                        "type": "project_error",
                        "project_name": "2508.18791",
                        "status": "needs_term_review",
                        "project_terms_path": r"D:\out\project_terms.csv",
                    },
                    app.current_task,
                )

            messages = [call.args[0] for call in notify.call_args_list]
            self.assertTrue(any("术语表已生成：2508.18791" in message for message in messages))
            self.assertFalse(any("发生异常：2508.18791" in message for message in messages))
            self.assertIn("任务全部完成：task-1", messages)

    async def test_project_log_event_updates_selected_detail_log(self):
        """确认项目日志事件会实时写入当前详情页日志控件。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False)
        async with app.run_test() as pilot:
            app.current_task = TaskViewState(input_type="arxiv", inputs=["2508.18791"])
            app.tasks = [app.current_task]
            app.handle_runtime_event({"type": "project_start", "project_name": "2508.18791"})
            app.select_project("2508.18791")

            app.handle_runtime_event(
                {
                    "type": "project_log",
                    "project_name": "2508.18791",
                    "line": "[ParserAgent] [INFO] parsed",
                }
            )
            await pilot.pause()

            project = app.current_task.projects[0]
            self.assertEqual(project.log_lines, ["[ParserAgent] [INFO] parsed"])

    async def test_project_log_event_does_not_rebuild_project_list(self):
        """确认高频项目日志事件不会重建左侧项目列表。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False)
        async with app.run_test():
            app.current_task = TaskViewState(input_type="arxiv", inputs=["2508.18791"])
            app.tasks = [app.current_task]
            app.handle_runtime_event({"type": "project_start", "project_name": "2508.18791"})
            app.select_project("2508.18791")

            with patch.object(app, "refresh_project_list") as refresh_project_list:
                with patch.object(app, "refresh_task_table") as refresh_task_table:
                    app.handle_runtime_event(
                        {
                            "type": "project_log",
                            "project_name": "2508.18791",
                            "line": "[ParserAgent] [INFO] parsed",
                        }
                    )

            refresh_project_list.assert_not_called()
            refresh_task_table.assert_not_called()

    async def test_task_log_event_refreshes_selected_project_detail_log(self):
        """任务级准备日志到达后应刷新当前项目详情日志区域。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False)
        async with app.run_test():
            app.current_task = TaskViewState(input_type="arxiv", inputs=["2508.18791"], task_id="task-1")
            app.tasks = [app.current_task]
            app.handle_runtime_event({"type": "project_start", "project_name": "2508.18791"})
            app.select_project("2508.18791")

            with patch.object(app, "_refresh_project_log") as refresh_log:
                app.handle_runtime_event({"type": "task_log", "line": "Downloading metadata"})

            refresh_log.assert_called_once()
            self.assertIn("Downloading metadata", refresh_log.call_args.args[1])

    def test_project_log_refresh_preserves_prepare_lines_missing_from_file(self):
        """项目日志文件刷新时不应覆盖尚未落盘的准备阶段日志。"""
        merged = _merge_project_log_text("[ParserAgent] parsed\n", ["Downloading paper", "[ParserAgent] parsed"])

        self.assertEqual(merged.splitlines(), ["Downloading paper", "[ParserAgent] parsed"])

    def test_project_log_refresh_fallback_keeps_task_log_lines(self):
        """日志文件不可读时，任务级准备日志仍应显示在详情区域。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False)
        project = ProjectViewState(project_name="paper", log_path=r"D:\\missing\\latextrans.log")
        log_widget = Mock()

        with patch.object(app, "query_one", return_value=log_widget):
            app._refresh_project_log(project, ["Downloading paper"])

        rendered = str(log_widget.write.call_args.args[0])
        self.assertIn("Downloading paper", rendered)

    async def test_start_current_task_initializes_total_without_run_start(self):
        """确认真实启动路径不依赖 runner 发送 run_start 也会初始化总数。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False)

        def fake_runner(**kwargs):
            """模拟 runner 只发送项目完成事件，避免真实下载或翻译。"""
            kwargs["event_callback"](
                {"type": "project_complete", "project_name": "2508.18791", "pdf_path": "paper.pdf"}
            )
            return {"completed_projects": ["2508.18791"], "failed_projects": []}

        async with app.run_test() as pilot:
            app.current_task = TaskViewState(input_type="arxiv", inputs=["2508.18791"])

            with patch("src.tui.app.run_tui_task", side_effect=fake_runner) as runner:
                app.start_current_task()
                await app.workers.wait_for_complete()
                await pilot.pause()

            runner.assert_called_once()
            call_kwargs = runner.call_args.kwargs
            self.assertEqual(call_kwargs["input_type"], "arxiv")
            self.assertEqual(call_kwargs["items"], ["2508.18791"])
            self.assertEqual(app.current_task.completed, 1)
            self.assertEqual(app.current_task.total, 1)

    async def test_process_task_events_update_state(self):
        """确认进程队列事件会更新任务状态并注册进程句柄。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False)
        handle = Mock()
        handle.process.is_alive.return_value = False
        with patch("src.tui.app.start_tui_task_process", return_value=handle) as start_process, \
            patch("src.tui.app.drain_process_messages", side_effect=[
                [("event", {"type": "project_start", "project_name": "2508.18791"})],
                [("event", {"type": "project_complete", "project_name": "2508.18791"})],
                [],
            ]):
            async with app.run_test() as pilot:
                task = TaskViewState(input_type="arxiv", inputs=["2508.18791"], task_id="task-process")
                app.current_task = task
                app.tasks = [task]
                app.start_current_task()
                await app.workers.wait_for_complete()
                await pilot.pause()

        start_process.assert_called_once()
        self.assertEqual(task.projects[0].status, ProjectStatus.COMPLETED)
        self.assertNotIn(task.task_id, app.task_processes)

    async def test_process_error_marks_running_project_failed_and_refreshes(self):
        """确认子进程异常会将运行项目标记失败并刷新任务表。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False)
        handle = Mock()
        handle.process.is_alive.return_value = False
        with patch("src.tui.app.start_tui_task_process", return_value=handle), \
            patch("src.tui.app.drain_process_messages", side_effect=[
                [("event", {"type": "project_start", "project_name": "2508.18791"})],
                [("error", {"error": "child failed"})],
                [],
            ]), patch.object(app, "refresh_task_table") as refresh_table:
            async with app.run_test() as pilot:
                task = TaskViewState(input_type="arxiv", inputs=["2508.18791"], task_id="task-error")
                app.current_task = task
                app.tasks = [task]
                app.start_current_task()
                await app.workers.wait_for_complete()
                await pilot.pause()

        self.assertEqual(task.projects[0].status, ProjectStatus.FAILED)
        self.assertEqual(task.failed, 1)
        refresh_table.assert_called()

    async def test_terminate_task_marks_cancelled_and_ignores_late_completion(self):
        """确认强制终止调用 terminate，且迟到完成事件不会覆盖 cancelled。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False)
        handle = Mock()
        handle.process.is_alive.return_value = True
        async with app.run_test():
            task = TaskViewState(input_type="arxiv", inputs=["2508.18791"], task_id="task-cancel", total=1)
            task.projects.append(ProjectViewState(project_name="2508.18791", status=ProjectStatus.RUNNING))
            app.current_task = task
            app.tasks = [task]
            app.task_processes[task.task_id] = handle

            with patch("src.tui.app.terminate_tui_task_process") as terminate_process:
                app.terminate_task_process(task.task_id)
            app.handle_runtime_event(
                {"type": "project_complete", "project_name": "2508.18791"},
                task,
            )

        terminate_process.assert_called_once_with(handle)
        self.assertEqual(task.projects[0].status, ProjectStatus.CANCELLED)

    async def test_stale_worker_events_do_not_update_new_current_task(self):
        """确认旧任务 worker 回调不会污染新的 current_task。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False)
        async with app.run_test():
            old_task = TaskViewState(input_type="arxiv", inputs=["2508.18791"], total=1)
            new_task = TaskViewState(input_type="arxiv", inputs=["2407.01648"], total=1)
            app.current_task = old_task
            app.current_task = new_task

            app.handle_runtime_event(
                {"type": "project_complete", "project_name": "2508.18791", "pdf_path": "old.pdf"},
                old_task,
            )

            self.assertEqual(old_task.completed, 0)
            self.assertEqual(new_task.completed, 0)
            self.assertEqual(new_task.events, [])

    async def test_worker_exception_is_reported_in_current_task(self):
        """确认 runner 异常会转成当前任务的可见失败事件。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False)

        def failing_runner(**kwargs):
            """模拟 runner 抛出异常，避免真实下载或翻译。"""
            raise RuntimeError("runner failed")

        async with app.run_test() as pilot:
            app.current_task = TaskViewState(input_type="arxiv", inputs=["2508.18791"])

            with patch("src.tui.app.run_tui_task", side_effect=failing_runner):
                with patch.object(app, "notify") as notify:
                    app.start_current_task()
                    await app.workers.wait_for_complete()
                    await pilot.pause()

            self.assertEqual(app.current_task.failed, 1)
            self.assertEqual(app.current_task.total, 1)
            self.assertTrue(any("runner failed" in str(event) for event in app.current_task.events))
            self.assertTrue(any("发生异常" in call.args[0] for call in notify.call_args_list))

    async def test_remote_prepare_failure_does_not_remap_error_to_input_url(self):
        """确认 remote prepare 全失败后不会再补发绑定到输入 URL 的 project_error。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False)
        remote_inputs = [
            "https://example.test/first.zip",
            "https://example.test/second.zip",
        ]

        def failing_remote_runner(**kwargs):
            """模拟 remote prepare 全失败时 runner 先发 run_start total=0 再抛错。"""
            kwargs["event_callback"]({"type": "run_start", "total": 0})
            raise RuntimeError("No valid TeX projects available for processing.")

        async with app.run_test() as pilot:
            app.current_task = TaskViewState(input_type="remote", inputs=remote_inputs)

            with patch("src.tui.app.run_tui_task", side_effect=failing_remote_runner):
                app.start_current_task()
                await app.workers.wait_for_complete()
                await pilot.pause()

            self.assertEqual(app.current_task.total, 0)
            self.assertEqual(app.current_task.failed, 0)
            self.assertEqual(app.current_task.projects, [])
            self.assertEqual(app.current_task.events, [{"type": "run_start", "total": 0}])
            self.assertFalse(
                any(project.project_name in remote_inputs for project in app.current_task.projects)
            )

    async def test_remote_prepare_failure_notifies_exception_and_task_completion(self):
        """确认 remote prepare 全失败时不会静默结束。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False)
        remote_inputs = ["https://example.test/first.zip"]

        def failing_remote_runner(**kwargs):
            """模拟 remote prepare 全失败时 runner 先发 run_start total=0 再抛错。"""
            kwargs["event_callback"]({"type": "run_start", "total": 0})
            raise RuntimeError("No valid TeX projects available for processing.")

        async with app.run_test() as pilot:
            app.current_task = TaskViewState(input_type="remote", inputs=remote_inputs, task_id="task-1")

            with patch("src.tui.app.run_tui_task", side_effect=failing_remote_runner):
                with patch.object(app, "notify") as notify:
                    app.start_current_task()
                    await app.workers.wait_for_complete()
                    await pilot.pause()

            messages = [call.args[0] for call in notify.call_args_list]
            self.assertTrue(any("发生异常：task-1" in message for message in messages))
            self.assertIn("任务全部完成：task-1", messages)


class TuiResultViewsTests(TuiAppTests):
    """验证任务结果列表、表格和项目详情页会读取项目状态。"""

    async def test_select_project_updates_detail_page(self):
        """确认选择项目会记录名称并切换到详情页。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False)
        async with app.run_test():
            app.current_task = TaskViewState(input_type="arxiv", inputs=["2508.18791"])
            app.current_task.projects.append(
                ProjectViewState(
                    project_name="paper",
                    status=ProjectStatus.COMPLETED,
                    output_dir="outputs/ch_paper",
                    pdf_path="paper.pdf",
                )
            )

            app.select_project("paper")

            self.assertEqual(app.selected_project_name, "paper")
            self.assertEqual(app.query_one("#main-switcher", ContentSwitcher).current, PAGE_DETAIL)
            with self.assertRaises(NoMatches):
                app.query_one("#detail-paths", Static)

    async def test_refresh_task_table_adds_project_rows(self):
        """确认任务管理表会展示当前任务下的项目行。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False)
        async with app.run_test():
            app.current_task = TaskViewState(input_type="arxiv", inputs=["2508.18791"])
            app.current_task.projects.append(ProjectViewState(project_name="paper", status=ProjectStatus.COMPLETED))

            app.refresh_task_table()

            table = app.query_one("#task-table", DataTable)
            self.assertEqual(table.row_count, 1)
            self.assertEqual(table.get_cell_at((0, 1)), "paper")
            self.assertEqual(table.get_cell_at((0, 2)), "completed")

    async def test_refresh_project_list_adds_selectable_items(self):
        """确认侧栏项目列表会展示当前任务下的项目。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False)
        async with app.run_test() as pilot:
            app.current_task = TaskViewState(input_type="arxiv", inputs=["2508.18791"])
            app.current_task.projects.append(ProjectViewState(project_name="paper", status=ProjectStatus.RUNNING))

            app.refresh_project_list()
            await pilot.pause()

            list_view = app.query_one("#project-list", ListView)
            self.assertEqual(len(list_view.children), 1)
            self.assertIn("paper", str(list_view.children[0].query_one(Static).content))

    async def test_refresh_detail_page_populates_project_artifacts(self):
        """确认详情页会展示 TeX、错误表和日志，不再展示底部路径摘要。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False)
        with TemporaryDirectory() as temp_dir:
            project_dir = Path(temp_dir)
            tex_file = project_dir / "main.tex"
            log_file = project_dir / "paper.log"
            tex_file.write_text("\\section{Result}", encoding="utf-8")
            log_file.write_text("compile ok", encoding="utf-8")

            async with app.run_test() as pilot:
                app.current_task = TaskViewState(input_type="local", inputs=[str(project_dir)])
                app.current_task.projects.append(
                    ProjectViewState(
                        project_name="paper",
                        status=ProjectStatus.FAILED,
                        project_dir=str(project_dir),
                        output_dir=str(project_dir / "out"),
                        pdf_path=str(project_dir / "paper.pdf"),
                        errors_report_path=str(project_dir / "errors.md"),
                        log_path=str(log_file),
                        error="compile failed",
                    )
                )
                app.selected_project_name = "paper"

                app.refresh_detail_page()
                await pilot.pause()

                with self.assertRaises(NoMatches):
                    app.query_one("#detail-paths", Static)
                tex_preview = app.query_one("#tex-preview", Static)
                self.assertIn("\\section{Result}", tex_preview.content.code)
                with self.assertRaises(NoMatches):
                    app.query_one("#project-log-summary", Static)
                self.assertIsNotNone(app.query_one("#project-log", RichLog))
                errors_table = app.query_one("#errors-table", DataTable)
                self.assertEqual(errors_table.row_count, 1)
                self.assertEqual(
                    [str(column.label) for column in errors_table.ordered_columns],
                    ["位置", "类型", "问题", "状态", "原文", "译文"],
                )
                self.assertEqual(errors_table.get_cell_at((0, 0)), "项目 -")
                self.assertEqual(errors_table.get_cell_at((0, 1)), "项目")
                self.assertEqual(errors_table.get_cell_at((0, 2)).plain, "compile failed")
                self.assertEqual(errors_table.get_cell_at((0, 3)).plain, "未解决")

    def test_compact_progress_log_for_display_keeps_first_middle_and_last_progress(self):
        """确认日志展示压缩连续进度块，只保留首行、中间行和末行。"""
        log_text = "\n".join(
            [
                "before",
                "[##----------------------]  10.0% step 1",
                "[####--------------------]  20.0% step 2",
                "[######------------------]  30.0% step 3",
                "[########----------------]  40.0% step 4",
                "[##########--------------]  50.0% step 5",
                "after",
                "[##----------------------]  10.0% second 1",
                "[####--------------------]  20.0% second 2",
                "[######------------------]  30.0% second 3",
            ]
        )

        compacted = compact_progress_log_for_display(log_text)

        self.assertEqual(
            compacted.splitlines(),
            [
                "before",
                "[##----------------------]  10.0% step 1",
                "[######------------------]  30.0% step 3",
                "[##########--------------]  50.0% step 5",
                "after",
                "[##----------------------]  10.0% second 1",
                "[####--------------------]  20.0% second 2",
                "[######------------------]  30.0% second 3",
            ],
        )

    async def test_refresh_detail_page_populates_error_report_content_status_and_truncates_text(self):
        """确认错误记录 tab 展示内容、状态颜色，并截断原文和译文。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False)
        with TemporaryDirectory() as temp_dir:
            project_dir = Path(temp_dir)
            source = "Original source " + ("A" * 160)
            translation = "Translated content " + ("B" * 160)
            (project_dir / "sections_map.json").write_text(
                json.dumps(
                    [
                        {"section": "1", "content": source, "trans_content": translation},
                        {"section": "2", "content": "Fixed source", "trans_content": "Fixed translation"},
                    ],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (project_dir / "captions_map.json").write_text("[]", encoding="utf-8")
            (project_dir / "envs_map.json").write_text("[]", encoding="utf-8")
            initial_report = [
                {
                    "part": "sec",
                    "num_or_ph": "1",
                    "severity": "error",
                    "issues": [{"type": "placeholder_mismatch", "message": "Missing placeholder"}],
                },
                {
                    "part": "sec",
                    "num_or_ph": "2",
                    "severity": "error",
                    "issues": [{"type": "command_mismatch", "message": "Missing command"}],
                },
            ]
            final_report = [initial_report[0]]
            (project_dir / "initial_errors_report.json").write_text(
                json.dumps(initial_report, ensure_ascii=False),
                encoding="utf-8",
            )
            errors_path = project_dir / "errors_report.json"
            errors_path.write_text(json.dumps(final_report, ensure_ascii=False), encoding="utf-8")

            async with app.run_test() as pilot:
                app.current_task = TaskViewState(input_type="local", inputs=[str(project_dir)])
                app.current_task.projects.append(
                    ProjectViewState(
                        project_name="paper",
                        status=ProjectStatus.FAILED,
                        project_dir=str(project_dir),
                        output_dir=str(project_dir),
                        errors_report_path=str(errors_path),
                    )
                )
                app.selected_project_name = "paper"
                app.switch_page(PAGE_DETAIL)

                app.refresh_detail_page()
                await pilot.pause()

                errors_table = app.query_one("#errors-table", DataTable)
                self.assertEqual(
                    [str(column.label) for column in errors_table.ordered_columns],
                    ["位置", "类型", "问题", "状态", "原文", "译文"],
                )
                self.assertEqual(errors_table.row_count, 2)
                unresolved_status = errors_table.get_cell_at((0, 3))
                resolved_status = errors_table.get_cell_at((1, 3))
                self.assertIsInstance(unresolved_status, Text)
                self.assertIsInstance(resolved_status, Text)
                self.assertEqual(unresolved_status.plain, "未解决")
                self.assertEqual(resolved_status.plain, "已解决")
                self.assertEqual(str(unresolved_status.style), "yellow")
                self.assertEqual(str(resolved_status.style), "green")
                self.assertTrue(errors_table.get_cell_at((0, 4)).plain.endswith("..."))
                self.assertTrue(errors_table.get_cell_at((0, 5)).plain.endswith("..."))
                self.assertNotIn("A" * 80, errors_table.get_cell_at((0, 4)).plain)
                self.assertNotIn("B" * 80, errors_table.get_cell_at((0, 5)).plain)
                render_width = sum(column.get_render_width(errors_table) for column in errors_table.ordered_columns)
                self.assertLessEqual(render_width, errors_table.size.width or 80)

    async def test_refresh_detail_page_discovers_error_report_from_output_dir(self):
        """确认运行中项目即使未收到错误报告路径事件，也会从输出目录读取错误报告。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False)
        with TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            (output_dir / "errors_report.json").write_text(
                json.dumps(
                    [
                        {
                            "part": "sec",
                            "num_or_ph": "1",
                            "issues": [{"type": "command_mismatch", "message": "Missing command"}],
                        }
                    ],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            async with app.run_test():
                app.current_task = TaskViewState(input_type="local", inputs=["paper"])
                app.current_task.projects.append(
                    ProjectViewState(
                        project_name="paper",
                        status=ProjectStatus.RUNNING,
                        output_dir=str(output_dir),
                    )
                )
                app.selected_project_name = "paper"

                app.refresh_detail_page()

                errors_table = app.query_one("#errors-table", DataTable)
                self.assertEqual(errors_table.row_count, 1)
                self.assertEqual(errors_table.get_cell_at((0, 0)), "章节 1")
                self.assertEqual(errors_table.get_cell_at((0, 1)), "命令")
                self.assertEqual(errors_table.get_cell_at((0, 2)).plain, "Missing command")
                self.assertEqual(errors_table.get_cell_at((0, 3)).plain, "未解决")

    async def test_errors_table_uses_available_detail_width_when_hidden(self):
        """确认错误记录 tab 隐藏刷新时仍按详情页可用宽度分配列宽。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False)
        with TemporaryDirectory() as temp_dir:
            project_dir = Path(temp_dir)
            (project_dir / "sections_map.json").write_text(
                json.dumps(
                    [
                        {
                            "section": "1",
                            "content": "Original source " + ("A" * 160),
                            "trans_content": "Translated content " + ("B" * 160),
                        }
                    ],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (project_dir / "captions_map.json").write_text("[]", encoding="utf-8")
            (project_dir / "envs_map.json").write_text("[]", encoding="utf-8")
            errors_path = project_dir / "errors_report.json"
            errors_path.write_text(
                json.dumps(
                    [
                        {
                            "part": "sec",
                            "num_or_ph": "1",
                            "issues": [{"type": "command_mismatch", "message": "Missing command"}],
                        }
                    ],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            async with app.run_test(size=(140, 40)) as pilot:
                app.current_task = TaskViewState(input_type="local", inputs=[str(project_dir)])
                app.current_task.projects.append(
                    ProjectViewState(
                        project_name="paper",
                        status=ProjectStatus.FAILED,
                        project_dir=str(project_dir),
                        output_dir=str(project_dir),
                        errors_report_path=str(errors_path),
                    )
                )
                app.selected_project_name = "paper"

                app.refresh_detail_page()
                await pilot.pause()
                errors_table = app.query_one("#errors-table", DataTable)
                hidden_width = sum(column.get_render_width(errors_table) for column in errors_table.ordered_columns)
                self.assertGreater(hidden_width, 80)

                app.query_one("#detail-tabs", TabbedContent).active = "errors-tab"
                await pilot.pause()
                event = Mock()
                event.tabbed_content.id = "detail-tabs"
                event.pane.id = "errors-tab"
                app.on_tabbed_content_tab_activated(event)
                await pilot.pause()

                visible_width = sum(column.get_render_width(errors_table) for column in errors_table.ordered_columns)
                self.assertLessEqual(visible_width, app._errors_table_available_width(errors_table))

    async def test_errors_table_recomputes_columns_after_terminal_resize(self):
        """确认终端宽度变化时错误记录表会按新宽度重新分配列宽。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False)
        with TemporaryDirectory() as temp_dir:
            project_dir = Path(temp_dir)
            (project_dir / "sections_map.json").write_text(
                json.dumps(
                    [
                        {
                            "section": "1",
                            "content": "Original source " + ("A" * 160),
                            "trans_content": "Translated content " + ("B" * 160),
                        }
                    ],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (project_dir / "captions_map.json").write_text("[]", encoding="utf-8")
            (project_dir / "envs_map.json").write_text("[]", encoding="utf-8")
            errors_path = project_dir / "errors_report.json"
            errors_path.write_text(
                json.dumps(
                    [
                        {
                            "part": "sec",
                            "num_or_ph": "1",
                            "issues": [{"type": "command_mismatch", "message": "Missing command"}],
                        }
                    ],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            async with app.run_test(size=(80, 40)) as pilot:
                app.current_task = TaskViewState(input_type="local", inputs=[str(project_dir)])
                app.current_task.projects.append(
                    ProjectViewState(
                        project_name="paper",
                        status=ProjectStatus.FAILED,
                        project_dir=str(project_dir),
                        output_dir=str(project_dir),
                        errors_report_path=str(errors_path),
                    )
                )
                app.selected_project_name = "paper"
                app.switch_page(PAGE_DETAIL)
                app.query_one("#detail-tabs", TabbedContent).active = "errors-tab"

                app.refresh_detail_page()
                await pilot.pause()
                errors_table = app.query_one("#errors-table", DataTable)
                narrow_source_width = errors_table.ordered_columns[4].width

                await pilot.resize_terminal(140, 40)
                await pilot.pause()

                wide_source_width = errors_table.ordered_columns[4].width
                self.assertGreater(wide_source_width, narrow_source_width)

    async def test_detail_page_shortcuts_switch_detail_tabs(self):
        """确认详情页 t/r/e/l/z 快捷键会切换对应项目 tab。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False)
        async with app.run_test() as pilot:
            app.switch_page(PAGE_DETAIL)
            tabs = app.query_one("#detail-tabs", TabbedContent)
            app.query_one("#detail-tabs ContentTabs").focus()

            shortcut_tabs = [
                ("r", "terms-tab"),
                ("e", "errors-tab"),
                ("l", "log-tab"),
                ("z", "zotero-tab"),
                ("t", "tex-tab"),
            ]
            for key, tab_id in shortcut_tabs:
                await pilot.press(key)
                await pilot.pause()
                self.assertEqual(tabs.active, tab_id)

    async def test_detail_tab_shortcuts_show_only_when_detail_tabs_are_focused(self):
        """确认详情页快捷键只在详情 tab 组件上下文中显示。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False)
        async with app.run_test() as pilot:
            app.switch_page(PAGE_DETAIL)
            await pilot.pause()
            self.assertNotIn("r", set(app.active_bindings))

            app.query_one("#detail-tabs ContentTabs").focus()
            await pilot.pause()

            active_shortcuts = set(app.active_bindings)
            self.assertIn("t", active_shortcuts)
            self.assertIn("r", active_shortcuts)
            self.assertIn("z", active_shortcuts)
            self.assertNotIn("p", active_shortcuts)

    async def test_refresh_detail_page_populates_terms_table(self):
        """确认详情页术语表只渲染 CSV 中的术语行。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False)
        with TemporaryDirectory() as temp_dir:
            project_dir = Path(temp_dir)
            terms_path = project_dir / "project_terms.csv"
            decisions_path = project_dir / "project_terms_decisions.json"
            terms_path.write_text(
                "Source Term,Target Translation\nGraph,图\nModel,模型\n",
                encoding="utf-8",
            )
            decisions_path.write_text('{"decisions": []}', encoding="utf-8")

            async with app.run_test():
                app.current_task = TaskViewState(input_type="local", inputs=[str(project_dir)])
                app.current_task.projects.append(
                    ProjectViewState(
                        project_name="paper",
                        status=ProjectStatus.COMPLETED,
                        project_terms_path=str(terms_path),
                        project_terms_decisions_path=str(decisions_path),
                    )
                )
                app.selected_project_name = "paper"

                app.refresh_detail_page()

                terms_table = app.query_one("#terms-table", DataTable)
                self.assertEqual(terms_table.row_count, 2)
                self.assertEqual(terms_table.get_cell_at((0, 0)), "Graph")
                self.assertEqual(terms_table.get_cell_at((0, 1)), "图")
                self.assertEqual(terms_table.get_cell_at((1, 0)), "Model")
                self.assertEqual(terms_table.get_cell_at((1, 1)), "模型")

    async def test_refresh_detail_page_discovers_terms_table_from_output_dir(self):
        """确认运行中项目即使未收到术语路径事件，也会从输出目录读取术语表。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False)
        with TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            terms_path = output_dir / "project_terms.csv"
            terms_path.write_text(
                "Source Term,Target Translation\nGraph,图\n",
                encoding="utf-8",
            )

            async with app.run_test():
                app.current_task = TaskViewState(input_type="local", inputs=["paper"])
                app.current_task.projects.append(
                    ProjectViewState(
                        project_name="paper",
                        status=ProjectStatus.RUNNING,
                        output_dir=str(output_dir),
                    )
                )
                app.selected_project_name = "paper"

                app.refresh_detail_page()

                terms_table = app.query_one("#terms-table", DataTable)
                self.assertEqual(terms_table.row_count, 1)
                self.assertEqual(terms_table.get_cell_at((0, 0)), "Graph")
                self.assertEqual(terms_table.get_cell_at((0, 1)), "图")


class TuiProjectManagerTests(TuiAppTests):
    """验证项目管理表的多选和批量操作按钮状态。"""

    def _task_with_projects(self) -> tuple[TaskViewState, TaskViewState]:
        """构造一个包含运行项目和已完成项目的任务集合。"""
        running = TaskViewState(input_type="arxiv", inputs=["running"], task_id="task-running", total=1)
        running.projects.append(ProjectViewState(project_name="running", status=ProjectStatus.RUNNING))
        completed = TaskViewState(input_type="arxiv", inputs=["done"], task_id="task-done", total=1)
        completed.projects.append(ProjectViewState(project_name="done", status=ProjectStatus.COMPLETED))
        return running, completed

    async def test_project_table_has_selection_column_and_toggles_rows(self):
        """确认项目表首列为选择标记，点击同一行可切换选中状态。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False)
        async with app.run_test():
            running, completed = self._task_with_projects()
            app.tasks = [running, completed]
            app.refresh_task_table()

            table = app.query_one("#task-table", DataTable)
            self.assertEqual([str(column.label) for column in table.ordered_columns], ["选中", "项目", "状态", "任务 id"])
            self.assertEqual(table.get_cell_at((0, 0)), "[]")

            app._toggle_project_selection(0)
            self.assertEqual(table.get_cell_at((0, 0)), "[√]")
            app._toggle_project_selection(0)
            self.assertEqual(table.get_cell_at((0, 0)), "[]")

    async def test_project_table_mouse_click_selects_row_once(self):
        """确认真实鼠标点击只切换一次，并将首行变为选中标记。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False)
        async with app.run_test() as pilot:
            task = TaskViewState(input_type="arxiv", inputs=["paper"], task_id="task-1", total=1)
            task.projects.append(ProjectViewState(project_name="paper", status=ProjectStatus.COMPLETED))
            app.tasks = [task]
            app.refresh_task_table()
            app.action_project_manager()
            await pilot.pause()

            table = app.query_one("#task-table", DataTable)
            self.assertGreater(table.region.width, 0)
            self.assertGreater(table.region.height, 0)
            self.assertEqual(table.get_cell_at((0, 0)), "[]")
            await pilot.click("#task-table", offset=(1, 1))
            await pilot.pause()
            self.assertEqual(table.get_cell_at((0, 0)), "[√]")

    async def test_project_action_buttons_require_all_selected_projects_to_match(self):
        """确认终止、删除、重译按钮遵循所有选中项目的状态约束。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False)
        async with app.run_test():
            running, completed = self._task_with_projects()
            app.tasks = [running, completed]
            app.refresh_task_table()
            terminate = app.query_one("#terminate-translation-button", Button)
            delete = app.query_one("#delete-project-button", Button)
            retry = app.query_one("#retry-translation-button", Button)

            self.assertTrue(terminate.disabled)
            self.assertTrue(delete.disabled)
            self.assertTrue(retry.disabled)

            app._toggle_project_selection(0)
            self.assertFalse(terminate.disabled)
            self.assertTrue(delete.disabled)
            self.assertTrue(retry.disabled)

            app._toggle_project_selection(0)
            app._toggle_project_selection(1)
            self.assertTrue(terminate.disabled)
            self.assertFalse(delete.disabled)
            self.assertFalse(retry.disabled)

            app._toggle_project_selection(0)
            self.assertTrue(terminate.disabled)
            self.assertTrue(delete.disabled)
            self.assertTrue(retry.disabled)

    async def test_refresh_task_table_preserves_existing_project_selection(self):
        """确认刷新表格后保留仍存在项目的选择身份并清理失效身份。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False)
        async with app.run_test():
            running, completed = self._task_with_projects()
            app.tasks = [running, completed]
            app.selected_project_keys = {(running.task_id, "running"), ("missing", "gone")}
            app.refresh_task_table()

            self.assertEqual(app.selected_project_keys, {(running.task_id, "running")})
            table = app.query_one("#task-table", DataTable)
            self.assertEqual(table.get_cell_at((0, 0)), "[√]")

    async def test_delete_selected_projects_removes_output_and_history_but_keeps_source(self):
        """确认删除会清理输出目录和内存历史，但不会删除源项目目录。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False)
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source"
            output = root / "output"
            source.mkdir()
            output.mkdir()
            (output / "artifact.txt").write_text("x", encoding="utf-8")
            task = TaskViewState(input_type="local", inputs=[str(source)], task_id="task-1", total=1)
            task.projects.append(
                ProjectViewState(
                    project_name="paper",
                    status=ProjectStatus.COMPLETED,
                    project_dir=str(source),
                    output_dir=str(output),
                )
            )
            async with app.run_test():
                app.tasks = [task]
                app.selected_project_keys = {(task.task_id, "paper")}
                app.refresh_task_table()

                app._delete_selected_projects()

                self.assertTrue(source.is_dir())
                self.assertFalse(output.exists())
                self.assertEqual(app.tasks, [])
                self.assertEqual(app.selected_project_keys, set())

    async def test_delete_selected_projects_continues_after_one_failure(self):
        """确认单个输出目录删除失败时，其他项目仍会继续删除。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False)
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first, second = root / "first", root / "second"
            first.mkdir()
            second.mkdir()
            task = TaskViewState(input_type="local", inputs=["first", "second"], task_id="task-1", total=2)
            task.projects.extend(
                [
                    ProjectViewState(project_name="first", status=ProjectStatus.COMPLETED, output_dir=str(first)),
                    ProjectViewState(project_name="second", status=ProjectStatus.COMPLETED, output_dir=str(second)),
                ]
            )
            async with app.run_test():
                app.tasks = [task]
                app.selected_project_keys = {(task.task_id, "first"), (task.task_id, "second")}
                app.refresh_task_table()
                real_rmtree = tui_app.shutil.rmtree

                def fail_first(path):
                    """仅让第一个目录删除失败，第二个使用真实递归删除。"""
                    if Path(path) == first:
                        raise OSError("locked")
                    return real_rmtree(path)

                with patch.object(tui_app.shutil, "rmtree", side_effect=fail_first):
                    app._delete_selected_projects()

                self.assertTrue(first.exists())
                self.assertFalse(second.exists())
                self.assertEqual([project.project_name for project in task.projects], ["first"])

    async def test_retry_selected_projects_reuses_inputs_and_starts_one_task(self):
        """确认批量重译复用原始输入，并只创建和启动一个新任务。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False)
        task = TaskViewState(input_type="arxiv", inputs=["2508.18791", "2508.18792"], task_id="old", total=2)
        task.projects.extend(
            [
                ProjectViewState(project_name="2508.18791", status=ProjectStatus.FAILED),
                ProjectViewState(project_name="2508.18792", status=ProjectStatus.COMPLETED),
            ]
        )
        async with app.run_test():
            app.tasks = [task]
            app.selected_project_keys = {(task.task_id, "2508.18791"), (task.task_id, "2508.18792")}
            app.refresh_task_table()
            with patch.object(app, "start_current_task") as start:
                app._retry_selected_projects()

            self.assertIs(app.current_task, app.tasks[-1])
            self.assertEqual(app.current_task.input_type, "arxiv")
            self.assertEqual(app.current_task.inputs, ["2508.18791", "2508.18792"])
            self.assertEqual(len(app.tasks), 2)
            start.assert_called_once_with()

    async def test_terminate_button_terminates_selected_task(self):
        """确认点击终止按钮会强制终止选中项目所属任务。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False)
        task = TaskViewState(input_type="arxiv", inputs=["2508.18791"], task_id="running", total=1)
        task.projects.append(ProjectViewState(project_name="2508.18791", status=ProjectStatus.RUNNING))
        async with app.run_test():
            app.tasks = [task]
            app.selected_project_keys = {(task.task_id, "2508.18791")}
            app.refresh_task_table()
            with patch.object(app, "terminate_task_process") as terminate:
                app.on_button_pressed(Button.Pressed(app.query_one("#terminate-translation-button", Button)))
            terminate.assert_called_once_with(task.task_id)


class TuiZoteroImportTests(TuiAppTests):
    """验证 Zotero tab 能对选中项目的 PDF 调用 adapter 并反馈状态。"""

    async def test_project_completion_shows_import_controls_on_first_zotero_tab_activation(self):
        """确认项目完成后首次打开 Zotero 页会显示新生成 PDF 的导入控件。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False)
        task = TaskViewState(input_type="arxiv", inputs=["2508.18791"], task_id="task-1", total=1)
        task.projects.append(ProjectViewState(project_name="2508.18791", status=ProjectStatus.RUNNING))

        async with app.run_test() as pilot:
            app.current_task = task
            app.tasks = [task]
            app.select_project("2508.18791", task.task_id)
            self.assertFalse(app.query_one("#import-zotero-button", Button).display)

            app.handle_runtime_event(
                {
                    "type": "project_complete",
                    "project_name": "2508.18791",
                    "pdf_path": "paper.pdf",
                },
                task,
            )
            with patch.object(app, "load_zotero_libraries"):
                app.query_one("#detail-tabs", TabbedContent).active = "zotero-tab"
                await pilot.pause()

            self.assertTrue(app.query_one("#zotero-import-rule", Rule).display)
            self.assertTrue(app.query_one("#import-zotero-button", Button).display)

    async def test_other_project_completion_does_not_refresh_selected_detail(self):
        """确认其他项目完成时不会重绘当前选中的项目详情。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False)
        task = TaskViewState(input_type="arxiv", inputs=["selected", "other"], task_id="task-1", total=2)
        task.projects.extend(
            [
                ProjectViewState(project_name="selected", status=ProjectStatus.RUNNING),
                ProjectViewState(project_name="other", status=ProjectStatus.RUNNING),
            ]
        )

        async with app.run_test():
            app.current_task = task
            app.tasks = [task]
            app.select_project("selected", task.task_id)

            with patch.object(app, "refresh_detail_page") as refresh_detail:
                app.handle_runtime_event(
                    {"type": "project_complete", "project_name": "other", "pdf_path": "other.pdf"},
                    task,
                )

            refresh_detail.assert_not_called()

    async def test_refresh_detail_page_hides_import_controls_without_pdf(self):
        """确认没有 PDF 的项目不显示竖向 Rule 和导入按钮。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False)

        async with app.run_test():
            app.current_task = TaskViewState(input_type="local", inputs=["paper"])
            app.current_task.projects.append(ProjectViewState(project_name="paper", status=ProjectStatus.COMPLETED))
            app.selected_project_name = "paper"

            app.refresh_detail_page()

            self.assertFalse(app.query_one("#zotero-import-rule", Rule).display)
            self.assertFalse(app.query_one("#import-zotero-button", Button).display)

    async def test_refresh_detail_page_shows_import_controls_for_any_project_with_pdf(self):
        """确认只要选中项目包含 PDF，就显示 Zotero 导入控件。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False)

        async with app.run_test():
            app.current_task = TaskViewState(input_type="history", inputs=["paper"])
            app.current_task.projects.append(
                ProjectViewState(
                    project_name="paper",
                    status=ProjectStatus.COMPLETED,
                    pdf_path="D:/outputs/ch_paper/ch_paper.pdf",
                )
            )
            app.selected_project_name = "paper"

            app.refresh_detail_page()

            self.assertTrue(app.query_one("#zotero-import-rule", Rule).display)
            self.assertTrue(app.query_one("#import-zotero-button", Button).display)

    async def test_zotero_results_table_uses_fixed_columns(self):
        """确认 Zotero 结果表固定展示四列。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False)

        async with app.run_test():
            table = app.query_one("#zotero-results", DataTable)

            self.assertEqual([str(column.label) for column in table.ordered_columns], ["选中", "标题", "所在库", "所在分类"])

    async def test_zotero_results_table_uses_row_cursor_for_click_selection(self):
        """确认 Zotero 结果表使用行级光标，让点击行触发行选中事件。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False)

        async with app.run_test():
            table = app.query_one("#zotero-results", DataTable)

            self.assertEqual(table.cursor_type, "row")

    async def test_zotero_results_table_truncates_long_titles(self):
        """确认 Zotero 结果表标题列固定宽度，并用省略渲染长标题。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False)

        async with app.run_test() as pilot:
            app.populate_zotero_results(
                [
                    {
                        "item_key": "ITEM1",
                        "title": "A Very Long Zotero Paper Title " * 6,
                        "library_id": "7",
                        "library_type": "user",
                        "library_name": "Ada",
                        "collection_names": [],
                    }
                ]
            )
            table = app.query_one("#zotero-results", DataTable)
            await pilot.pause()
            title_column = table.ordered_columns[1]
            library_column = table.ordered_columns[2]
            collection_column = table.ordered_columns[3]
            title_cell = table.get_cell_at((0, 1))

            self.assertGreater(title_column.width, library_column.width)
            self.assertGreater(title_column.width, collection_column.width)
            self.assertIsInstance(title_cell, Text)
            self.assertEqual(title_cell.overflow, "ellipsis")
            self.assertTrue(title_cell.no_wrap)

    async def test_zotero_results_columns_fit_visible_width_without_horizontal_scroll(self):
        """确认 Zotero 结果列宽不会超过表格可视宽度。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False)

        async with app.run_test(size=(100, 30)) as pilot:
            app.switch_page(PAGE_DETAIL)
            app.query_one("#detail-tabs", TabbedContent).active = "zotero-tab"
            app.populate_zotero_results(
                [
                    {
                        "item_key": "ITEM1",
                        "title": "A Very Long Zotero Paper Title " * 6,
                        "library_id": "7",
                        "library_type": "user",
                        "library_name": "Ada",
                        "collection_names": ["LLM Steering", "Long Collection"],
                    }
                ]
            )
            table = app.query_one("#zotero-results", DataTable)
            await pilot.pause()
            render_width = sum(column.get_render_width(table) for column in table.ordered_columns)

            self.assertLessEqual(render_width, table.size.width)

    async def test_load_zotero_libraries_populates_search_scope_select(self):
        """确认 Zotero 库 select 来自 adapter 的本地 API 库列表。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False)
        adapter = Mock()
        adapter.list_libraries.return_value = [
            {"library_id": "7", "library_type": "user", "name": "Ada"},
            {"library_id": "42", "library_type": "group", "name": "Reading Group"},
        ]

        async with app.run_test():
            app.zotero_adapter_factory = lambda api_key, local_api_base: adapter
            app.current_config = {
                "zotero": {
                    "local_api_base": "http://127.0.0.1:23119/api",
                    "web_api_key_env": "ZOTERO_API_KEY",
                }
            }

            app.load_zotero_libraries()

            select = app.query_one("#zotero-library-select", Select)
            self.assertEqual(select.value, "user:7")
            self.assertEqual(app.zotero_libraries[1]["library_type"], "group")

    async def test_activating_zotero_tab_loads_libraries(self):
        """确认打开 Zotero tab 时会自动加载可选库。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False)
        event = Mock()
        event.tabbed_content.id = "detail-tabs"
        event.pane.id = "zotero-tab"

        async with app.run_test():
            with patch.object(app, "load_zotero_libraries") as load_libraries:
                app.on_tabbed_content_tab_activated(event)

        load_libraries.assert_called_once_with()

    async def test_search_zotero_items_populates_unselected_rows(self):
        """确认搜索按钮使用当前库和搜索框，并把结果默认设为未选中。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False)
        adapter = Mock()
        adapter.search_items.return_value = [
            {
                "item_key": "ITEM1",
                "title": "Paper",
                "library_id": "42",
                "library_type": "group",
                "library_name": "Reading Group",
                "collection_names": ["Inbox"],
            }
        ]

        async with app.run_test():
            app.zotero_adapter_factory = lambda api_key, local_api_base: adapter
            app.zotero_libraries = [{"library_id": "42", "library_type": "group", "name": "Reading Group"}]
            app.query_one("#zotero-library-select", Select).set_options([("Reading Group", "group:42")])
            app.query_one("#zotero-library-select", Select).value = "group:42"
            app.query_one("#zotero-search-input", Input).value = "Paper"

            app.search_zotero_items()

            adapter.search_items.assert_called_once_with("Paper", "42", "group")
            table = app.query_one("#zotero-results", DataTable)
            self.assertEqual(table.row_count, 1)
            self.assertEqual(table.get_cell_at((0, 0)), "[]")
            self.assertEqual(table.get_cell_at((0, 1)).plain, "Paper")

    async def test_search_input_enter_triggers_search(self):
        """确认搜索框回车触发搜索。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False)
        event = Mock()
        event.input.id = "zotero-search-input"

        async with app.run_test():
            with patch.object(app, "search_zotero_items") as search:
                app.on_input_submitted(event)

        search.assert_called_once_with()

    async def test_auto_match_uses_archive_id_from_arxiv_task(self):
        """确认自动匹配使用当前任务 arXiv ID 搜索存档 id。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False)
        adapter = Mock()
        adapter.match_items_by_archive_id.return_value = [
            {
                "item_key": "ITEM1",
                "title": "Matched",
                "library_id": "7",
                "library_type": "user",
                "library_name": "Ada",
                "collection_names": [],
            }
        ]

        async with app.run_test():
            app.zotero_adapter_factory = lambda api_key, local_api_base: adapter
            app.current_task = TaskViewState(input_type="arxiv", inputs=["2508.18791"])
            app.current_task.projects.append(ProjectViewState(project_name="2508.18791", status=ProjectStatus.COMPLETED))
            app.selected_project_name = "2508.18791"
            app.zotero_libraries = [{"library_id": "7", "library_type": "user", "name": "Ada"}]
            app.query_one("#zotero-library-select", Select).set_options([("Ada", "user:7")])
            app.query_one("#zotero-library-select", Select).value = "user:7"

            app.auto_match_zotero_items()

            adapter.match_items_by_archive_id.assert_called_once_with("2508.18791", "7", "user")
            self.assertEqual(app.query_one("#zotero-results", DataTable).get_cell_at((0, 1)).plain, "Matched")

    async def test_toggle_zotero_row_selection_switches_marker(self):
        """确认点击结果行会在 [] 和 [√] 间切换。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False)

        async with app.run_test():
            app.populate_zotero_results(
                [
                    {
                        "item_key": "ITEM1",
                        "title": "Paper",
                        "library_id": "7",
                        "library_type": "user",
                        "library_name": "Ada",
                        "collection_names": [],
                    }
                ]
            )

            app.toggle_zotero_row_selection(0)
            self.assertEqual(app.query_one("#zotero-results", DataTable).get_cell_at((0, 0)), "[√]")
            app.toggle_zotero_row_selection(0)
            self.assertEqual(app.query_one("#zotero-results", DataTable).get_cell_at((0, 0)), "[]")

    async def test_clicking_zotero_result_row_toggles_marker(self):
        """确认真实点击 Zotero 结果行会切换选中标记。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False)

        async with app.run_test() as pilot:
            app.switch_page(PAGE_DETAIL)
            app.query_one("#detail-tabs", TabbedContent).active = "zotero-tab"
            app.populate_zotero_results(
                [
                    {
                        "item_key": "ITEM1",
                        "title": "Paper",
                        "library_id": "7",
                        "library_type": "user",
                        "library_name": "Ada",
                        "collection_names": [],
                    }
                ]
            )
            table = app.query_one("#zotero-results", DataTable)
            await pilot.pause()

            clicked = await pilot.click(table, offset=(10, 1))
            await pilot.pause()

            self.assertTrue(clicked)
            self.assertEqual(table.get_cell_at((0, 0)), "[√]")

    async def test_select_project_clears_zotero_rows_and_selection(self):
        """确认切换项目时清空旧项目的 Zotero 搜索结果和勾选状态。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False)

        async with app.run_test():
            task = TaskViewState(input_type="arxiv", inputs=["2508.18791", "2407.01648"], task_id="task")
            task.projects.append(ProjectViewState(project_name="2508.18791", status=ProjectStatus.COMPLETED))
            task.projects.append(ProjectViewState(project_name="2407.01648", status=ProjectStatus.COMPLETED))
            app.current_task = task
            app.tasks = [task]
            app.selected_project_name = "2508.18791"
            app.populate_zotero_results(
                [
                    {
                        "item_key": "ITEM1",
                        "title": "Paper",
                        "library_id": "7",
                        "library_type": "user",
                        "library_name": "用户库",
                        "collection_names": [],
                    }
                ]
            )
            app.toggle_zotero_row_selection(0)

            app.select_project("2407.01648", "task")

            self.assertEqual(app.zotero_results, [])
            self.assertEqual(app.zotero_selected_keys, set())
            self.assertEqual(app.query_one("#zotero-results", DataTable).row_count, 0)

    async def test_import_zotero_button_attaches_selected_project_pdf(self):
        """确认导入按钮对每个选中条目附加当前项目 PDF。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False)
        adapter = Mock()
        adapter.attach_pdf.side_effect = [
            {"attachment_key": "ATTACH1", "status": "uploaded"},
            {"attachment_key": "ATTACH2", "status": "uploaded"},
        ]

        async with app.run_test():
            app.zotero_adapter_factory = lambda api_key, local_api_base: adapter
            app.current_config = {
                "zotero": {
                    "local_api_base": "http://127.0.0.1:23119/api",
                    "web_api_key_env": "ZOTERO_API_KEY",
                }
            }
            app.current_task = TaskViewState(input_type="arxiv", inputs=["2508.18791"])
            app.current_task.projects.append(
                ProjectViewState(
                    project_name="2508.18791",
                    status=ProjectStatus.COMPLETED,
                    pdf_path=r"D:\out\paper.pdf",
                )
            )
            app.selected_project_name = "2508.18791"
            app.switch_page(PAGE_DETAIL)
            with patch.dict("os.environ", {"ZOTERO_API_KEY": "ui-key"}):
                app.populate_zotero_results(
                    [
                        {
                            "item_key": "ITEM123",
                            "title": "Paper 1",
                            "library_id": "42",
                            "library_type": "group",
                            "library_name": "Reading Group",
                            "collection_names": ["Inbox"],
                        },
                        {
                            "item_key": "ITEM456",
                            "title": "Paper 2",
                            "library_id": "7",
                            "library_type": "user",
                            "library_name": "Ada",
                            "collection_names": [],
                        },
                    ]
                )
                app.toggle_zotero_row_selection(0)
                app.toggle_zotero_row_selection(1)

                app.import_selected_project_to_zotero()

            self.assertEqual(adapter.attach_pdf.call_count, 2)
            adapter.attach_pdf.assert_any_call("ITEM123", r"D:\out\paper.pdf", "42", "group")
            adapter.attach_pdf.assert_any_call("ITEM456", r"D:\out\paper.pdf", "7", "user")
            project = app.current_task.projects[0]
            self.assertEqual(project.zotero_status, "导入完成：成功 2，失败 0。")

    async def test_import_zotero_button_reports_failure_without_changing_task_result(self):
        """确认 Zotero 导入失败会展示错误，但不改变翻译完成状态。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False)
        adapter = Mock()
        adapter.attach_pdf.side_effect = RuntimeError("zotero failed")

        async with app.run_test():
            app.zotero_adapter_factory = lambda api_key, local_api_base: adapter
            app.current_config = {
                "zotero": {
                    "local_api_base": "http://127.0.0.1:23119/api",
                    "web_api_key_env": "ZOTERO_API_KEY",
                }
            }
            app.current_task = TaskViewState(input_type="arxiv", inputs=["2508.18791"])
            app.current_task.projects.append(
                ProjectViewState(
                    project_name="2508.18791",
                    status=ProjectStatus.COMPLETED,
                    pdf_path=r"D:\out\paper.pdf",
                )
            )
            app.current_task.completed = 1
            app.selected_project_name = "2508.18791"
            app.switch_page(PAGE_DETAIL)
            app.populate_zotero_results(
                [
                    {
                        "item_key": "ITEM123",
                        "title": "Paper",
                        "library_id": "42",
                        "library_type": "group",
                        "library_name": "Reading Group",
                        "collection_names": [],
                    }
                ]
            )
            app.toggle_zotero_row_selection(0)

            with patch.dict("os.environ", {"ZOTERO_API_KEY": "ui-key"}):
                app.import_selected_project_to_zotero()

            project = app.current_task.projects[0]
            self.assertEqual(project.status, ProjectStatus.COMPLETED)
            self.assertEqual(app.current_task.completed, 1)
            self.assertIn("失败 1", project.zotero_status)

    async def test_import_zotero_button_branch_calls_import_method(self):
        """确认 Zotero tab 按钮分支会同步调用导入方法。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False)
        event = Mock()
        event.button.id = "import-zotero-button"

        async with app.run_test():
            with patch.object(app, "import_selected_project_to_zotero") as import_method:
                app.on_button_pressed(event)

        import_method.assert_called_once_with()

    async def test_lite_shows_markdown_import_button_and_heavy_hides_it(self):
        """确认 lite 显示 PDF 与 Markdown 导入，heavy 只显示 PDF 导入。"""
        lite = LaTeXTransTuiApp(load_history_on_mount=False, initial_engine="lite")
        heavy = LaTeXTransTuiApp(load_history_on_mount=False, initial_engine="heavy")

        async with lite.run_test():
            lite.current_task = TaskViewState(input_type="pdf", inputs=["paper.pdf"], engine="lite")
            lite.current_task.projects.append(
                ProjectViewState(
                    project_name="paper",
                    engine="lite",
                    pdf_path=r"D:\out\paper.pdf",
                    translated_markdown_path=r"D:\out\translated.md",
                )
            )
            lite.selected_project_name = "paper"
            lite.refresh_detail_page()

            self.assertTrue(lite.query_one("#import-zotero-button", Button).display)
            self.assertTrue(lite.query_one("#import-zotero-markdown-button", Button).display)

        async with heavy.run_test():
            heavy.current_task = TaskViewState(input_type="arxiv", inputs=["2508.18791"], engine="heavy")
            heavy.current_task.projects.append(
                ProjectViewState(
                    project_name="paper",
                    engine="heavy",
                    pdf_path=r"D:\out\paper.pdf",
                    translated_markdown_path=r"D:\out\translated.md",
                )
            )
            heavy.selected_project_name = "paper"
            heavy.refresh_detail_page()

            self.assertTrue(heavy.query_one("#import-zotero-button", Button).display)
            self.assertFalse(heavy.query_one("#import-zotero-markdown-button", Button).display)

    async def test_import_markdown_creates_note_for_each_selected_zotero_item(self):
        """确认 lite 会把完整译文 Markdown 作为每个选中条目的子笔记。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False, initial_engine="lite")
        adapter = Mock()
        adapter.create_note.side_effect = [{"item_key": "NOTE1"}, {"item_key": "NOTE2"}]

        with TemporaryDirectory() as temp_dir:
            translated_path = Path(temp_dir) / "translated.md"
            markdown = "# Title\n\n完整译文内容\n"
            translated_path.write_text(markdown, encoding="utf-8")

            async with app.run_test():
                app.zotero_adapter_factory = lambda api_key, local_api_base: adapter
                app.current_config = {
                    "zotero": {
                        "local_api_base": "http://127.0.0.1:23119/api",
                        "web_api_key_env": "ZOTERO_API_KEY",
                    }
                }
                app.current_task = TaskViewState(input_type="pdf", inputs=["paper.pdf"], engine="lite")
                app.current_task.projects.append(
                    ProjectViewState(
                        project_name="paper",
                        engine="lite",
                        status=ProjectStatus.COMPLETED,
                        translated_markdown_path=str(translated_path),
                    )
                )
                app.selected_project_name = "paper"
                app.populate_zotero_results(
                    [
                        {
                            "item_key": "ITEM123",
                            "title": "Paper 1",
                            "library_id": "42",
                            "library_type": "group",
                            "library_name": "Reading Group",
                            "collection_names": [],
                        },
                        {
                            "item_key": "ITEM456",
                            "title": "Paper 2",
                            "library_id": "7",
                            "library_type": "user",
                            "library_name": "Ada",
                            "collection_names": [],
                        },
                    ]
                )
                app.toggle_zotero_row_selection(0)
                app.toggle_zotero_row_selection(1)

                with patch.dict("os.environ", {"ZOTERO_API_KEY": "ui-key"}):
                    app.import_selected_project_markdown_to_zotero()

        self.assertEqual(adapter.create_note.call_count, 2)
        adapter.create_note.assert_any_call("ITEM123", "paper", markdown, "42", "group")
        adapter.create_note.assert_any_call("ITEM456", "paper", markdown, "7", "user")
        self.assertEqual(app.current_task.projects[0].zotero_status, "导入完成：成功 2，失败 0。")

    async def test_import_markdown_continues_after_one_selected_item_fails(self):
        """确认首个子笔记失败不会阻止后续选中条目的导入。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False, initial_engine="lite")
        adapter = Mock()
        adapter.create_note.side_effect = [RuntimeError("first note rejected"), {"item_key": "NOTE2"}]

        with TemporaryDirectory() as temp_dir:
            translated_path = Path(temp_dir) / "translated.md"
            translated_path.write_text("# Title\n\n完整译文内容\n", encoding="utf-8")

            async with app.run_test():
                app.zotero_adapter_factory = lambda api_key, local_api_base: adapter
                app.current_config = {
                    "zotero": {
                        "local_api_base": "http://127.0.0.1:23119/api",
                        "web_api_key_env": "ZOTERO_API_KEY",
                    }
                }
                app.current_task = TaskViewState(input_type="pdf", inputs=["paper.pdf"], engine="lite")
                app.current_task.projects.append(
                    ProjectViewState(
                        project_name="paper",
                        engine="lite",
                        status=ProjectStatus.COMPLETED,
                        translated_markdown_path=str(translated_path),
                    )
                )
                app.selected_project_name = "paper"
                app.populate_zotero_results(
                    [
                        {
                            "item_key": "ITEM123",
                            "title": "Paper 1",
                            "library_id": "42",
                            "library_type": "group",
                            "library_name": "Reading Group",
                            "collection_names": [],
                        },
                        {
                            "item_key": "ITEM456",
                            "title": "Paper 2",
                            "library_id": "7",
                            "library_type": "user",
                            "library_name": "Ada",
                            "collection_names": [],
                        },
                    ]
                )
                app.toggle_zotero_row_selection(0)
                app.toggle_zotero_row_selection(1)

                with patch.dict("os.environ", {"ZOTERO_API_KEY": "ui-key"}):
                    app.import_selected_project_markdown_to_zotero()

        self.assertEqual(adapter.create_note.call_count, 2)
        adapter.create_note.assert_any_call("ITEM123", "paper", "# Title\n\n完整译文内容\n", "42", "group")
        adapter.create_note.assert_any_call("ITEM456", "paper", "# Title\n\n完整译文内容\n", "7", "user")
        self.assertEqual(
            app.current_task.projects[0].zotero_status,
            "导入完成：成功 1，失败 1。 ITEM123: first note rejected",
        )

    async def test_import_markdown_reports_missing_translated_file(self):
        """确认 Markdown 导入会明确报告缺失的译文文件。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False, initial_engine="lite")

        async with app.run_test():
            app.current_task = TaskViewState(input_type="pdf", inputs=["paper.pdf"], engine="lite")
            app.current_task.projects.append(
                ProjectViewState(
                    project_name="paper",
                    engine="lite",
                    status=ProjectStatus.COMPLETED,
                    translated_markdown_path=r"D:\out\missing-translated.md",
                )
            )
            app.selected_project_name = "paper"
            app.populate_zotero_results(
                [
                    {
                        "item_key": "ITEM123",
                        "title": "Paper",
                        "library_id": "42",
                        "library_type": "group",
                        "library_name": "Reading Group",
                        "collection_names": [],
                    }
                ]
            )
            app.toggle_zotero_row_selection(0)

            app.import_selected_project_markdown_to_zotero()

        self.assertEqual(app.current_task.projects[0].zotero_status, "失败：当前项目没有译文 Markdown 文件。")

    async def test_import_markdown_reports_missing_api_key(self):
        """确认 Markdown 导入在 API key 缺失时不创建笔记。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False, initial_engine="lite")

        with TemporaryDirectory() as temp_dir:
            translated_path = Path(temp_dir) / "translated.md"
            translated_path.write_text("# content", encoding="utf-8")

            async with app.run_test():
                app.current_config = {
                    "zotero": {
                        "local_api_base": "http://127.0.0.1:23119/api",
                        "web_api_key_env": "MISSING_ZOTERO_API_KEY",
                    }
                }
                app.current_task = TaskViewState(input_type="pdf", inputs=["paper.pdf"], engine="lite")
                app.current_task.projects.append(
                    ProjectViewState(
                        project_name="paper",
                        engine="lite",
                        status=ProjectStatus.COMPLETED,
                        translated_markdown_path=str(translated_path),
                    )
                )
                app.selected_project_name = "paper"
                app.populate_zotero_results(
                    [
                        {
                            "item_key": "ITEM123",
                            "title": "Paper",
                            "library_id": "42",
                            "library_type": "group",
                            "library_name": "Reading Group",
                            "collection_names": [],
                        }
                    ]
                )
                app.toggle_zotero_row_selection(0)

                with patch.dict("os.environ", {}, clear=True):
                    app.import_selected_project_markdown_to_zotero()

        self.assertEqual(
            app.current_task.projects[0].zotero_status,
            "失败：Web API key 环境变量未设置：MISSING_ZOTERO_API_KEY。",
        )

    async def test_markdown_import_button_branch_calls_markdown_import_method(self):
        """确认 Zotero Markdown 导入按钮会调用对应动作。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False, initial_engine="lite")
        event = Mock()
        event.button.id = "import-zotero-markdown-button"

        async with app.run_test():
            with patch.object(app, "import_selected_project_markdown_to_zotero") as import_method:
                app.on_button_pressed(event)

        import_method.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
