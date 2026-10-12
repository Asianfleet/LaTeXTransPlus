import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from textual.widgets import DataTable, Input, Select

from src.tui.app import LaTeXTransTuiApp
from src.tui.state import ProjectViewState, TaskViewState
from src.tui.zotero_panel import ZoteroPanel


class TuiZoteroPanelTests(unittest.IsolatedAsyncioTestCase):
    """验证 Zotero 面板独立维护搜索、选择和导入状态。"""

    async def asyncSetUp(self) -> None:
        """将整个 UI 生命周期放入临时目录并拦截配置访问。"""
        self.original_cwd = Path.cwd()
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.addCleanup(os.chdir, self.original_cwd)
        os.chdir(self.temporary.name)
        self.save = Mock()
        adapter = Mock()
        adapter.list_libraries.return_value = []
        targets = {
            "src.tui.app.ZoteroAdapter": Mock(return_value=adapter),
            "src.tui.app.load_ui_config": Mock(return_value={}),
            "src.tui.config_page.load_ui_config": Mock(return_value={}),
            "src.tui.config_page.save_ui_config": self.save,
            "src.tui.config.save_ui_config": self.save,
            "src.tui.config_page.list_llm_profiles": Mock(return_value=[]),
            "src.tui.config_page.list_available_font_families": Mock(return_value=[]),
        }
        for target, replacement in targets.items():
            patcher = patch(target, replacement)
            patcher.start()
            self.addCleanup(patcher.stop)

    def _set_project_context(
        self,
        panel: ZoteroPanel,
        project: ProjectViewState,
        *,
        task_id: str = "task-1",
        input_type: str = "arxiv",
        arxiv_id: str = "2508.18791",
        engine: str = "heavy",
        config: dict[str, object] | None = None,
        reset_selection: bool = False,
    ) -> None:
        """为面板设置不依赖 App 查询的明确项目上下文。"""
        panel.set_context(
            project=project,
            task_id=task_id,
            input_type=input_type,
            arxiv_id=arxiv_id,
            engine=engine,
            config=config or {},
            reset_selection=reset_selection,
        )

    async def test_enter_search_reaches_adapter_once(self) -> None:
        """输入框提交由所属面板处理且不被 App 再次执行。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False)
        adapter = Mock()
        adapter.search_items.return_value = []
        async with app.run_test() as pilot:
            panel = app.zotero_panel
            panel.adapter_factory = Mock(return_value=adapter)
            panel.zotero_libraries = [
                {"library_type": "user", "library_id": "7", "name": "Test"}
            ]
            select = panel.query_one("#zotero-library-select", Select)
            select.set_options([("Test", "user:7")])
            select.value = "user:7"
            search = panel.query_one("#zotero-search-input", Input)
            search.value = "paper"
            app.switch_page("detail")
            app.query_one("#detail-tabs").active = "zotero-tab"
            with patch.object(panel, "load_zotero_libraries"):
                await pilot.pause()
                search.focus()
                await pilot.press("enter")
                await pilot.pause()
            adapter.search_items.assert_called_once_with("paper", "7", "user")

    async def test_context_identity_and_explicit_reset_control_results(self) -> None:
        """身份变化和显式重置清空结果，同身份普通刷新保留状态。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False)
        first = ProjectViewState(project_name="first")
        second = ProjectViewState(project_name="second")
        async with app.run_test():
            panel = app.zotero_panel
            self._set_project_context(panel, first)
            panel.populate_zotero_results([{"item_key": "ITEM1", "title": "Paper"}])
            panel.toggle_zotero_row_selection(0)

            self._set_project_context(panel, first)
            self.assertEqual(len(panel.zotero_results), 1)
            self.assertEqual(panel.zotero_selected_keys, {"ITEM1"})

            self._set_project_context(panel, first, engine="lite", config={"changed": True})
            self.assertEqual(len(panel.zotero_results), 1)
            self.assertEqual(panel.zotero_selected_keys, {"ITEM1"})

            self._set_project_context(panel, first, reset_selection=True)
            self.assertEqual(panel.zotero_results, [])
            panel.populate_zotero_results([{"item_key": "ITEM2", "title": "Other"}])
            self._set_project_context(panel, second)
            self.assertEqual(panel.zotero_results, [])

    async def test_update_config_copies_without_clearing_selection(self) -> None:
        """配置刷新保存副本且不影响当前搜索结果和选择。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False)
        config = {"local_api_base": "http://local", "nested": {"enabled": True}}
        async with app.run_test():
            panel = app.zotero_panel
            panel.populate_zotero_results([{"item_key": "ITEM1", "title": "Paper"}])
            panel.toggle_zotero_row_selection(0)
            panel.update_config(config)
            config["nested"]["enabled"] = False

            self.assertEqual(panel.config["nested"], {"enabled": True})
            self.assertEqual(panel.zotero_selected_keys, {"ITEM1"})

    async def test_clicking_row_toggles_once(self) -> None:
        """鼠标按下、点击和行选择事件组合只切换一次。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False)
        async with app.run_test(size=(80, 24)) as pilot:
            app.switch_page("detail")
            app.query_one("#detail-tabs").active = "zotero-tab"
            panel = app.zotero_panel
            panel.populate_zotero_results([{"item_key": "ITEM1", "title": "Paper"}])
            table = panel.query_one("#zotero-results", DataTable)
            await pilot.pause()

            self.assertTrue(await pilot.click(table, offset=(10, 1)))
            await pilot.pause()

            self.assertEqual(panel.zotero_selected_keys, {"ITEM1"})
            self.assertEqual(table.get_cell_at((0, 0)), "[√]")

            table.focus()
            await pilot.press("enter")
            await pilot.pause()
            self.assertEqual(panel.zotero_selected_keys, set())
            self.assertEqual(table.get_cell_at((0, 0)), "[]")

    async def test_narrow_resize_requests_column_refit(self) -> None:
        """窄终端 resize 由面板接收并重新计算固定列宽。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False)
        async with app.run_test(size=(100, 30)) as pilot:
            app.switch_page("detail")
            app.query_one("#detail-tabs").active = "zotero-tab"
            panel = app.zotero_panel
            panel.populate_zotero_results([{"item_key": "ITEM1", "title": "Paper"}])
            await pilot.pause()
            table = panel.query_one("#zotero-results", DataTable)
            panel.toggle_zotero_row_selection(0)
            table.move_cursor(row=0, column=1, scroll=False)
            before = tuple(column.width for column in table.ordered_columns)

            await pilot.resize_terminal(62, 24)
            await pilot.pause()
            after = tuple(column.width for column in table.ordered_columns)

            self.assertNotEqual(after, before)
            self.assertEqual(after[0], 4)
            self.assertGreaterEqual(after[1], 20)
            self.assertEqual(panel.zotero_selected_keys, {"ITEM1"})
            self.assertEqual(table.cursor_coordinate.row, 0)

            await pilot.resize_terminal(100, 30)
            await pilot.pause()
            await pilot.pause()
            self.assertEqual(
                tuple(column.width for column in table.ordered_columns),
                before,
            )
            self.assertEqual(panel.zotero_selected_keys, {"ITEM1"})
            self.assertEqual(table.cursor_coordinate.row, 0)

    async def test_empty_library_and_search_errors_report_status(self) -> None:
        """空库和搜索异常均更新项目状态且不会访问真实服务。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False)
        project = ProjectViewState(project_name="paper")
        adapter = Mock()
        adapter.list_libraries.return_value = []
        async with app.run_test() as pilot:
            panel = app.zotero_panel
            panel.adapter_factory = Mock(return_value=adapter)
            self._set_project_context(panel, project)
            panel.load_zotero_libraries()
            self.assertEqual(project.zotero_status, "没有可选库。")

            panel.zotero_libraries = [
                {"library_type": "user", "library_id": "7", "name": "Test"}
            ]
            select = panel.query_one("#zotero-library-select", Select)
            select.set_options([("Test", "user:7")])
            select.value = "user:7"
            panel.query_one("#zotero-search-input", Input).value = "paper"
            adapter.search_items.side_effect = RuntimeError("offline")
            panel.search_zotero_items()
            self.assertEqual(project.zotero_status, "搜索失败：offline")

    async def test_auto_match_uses_explicit_arxiv_context(self) -> None:
        """自动匹配只使用 App 提供的 arXiv 上下文。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False)
        adapter = Mock()
        adapter.match_items_by_archive_id.return_value = [
            {"item_key": "MATCH", "title": "Matched"}
        ]
        async with app.run_test():
            panel = app.zotero_panel
            panel.adapter_factory = Mock(return_value=adapter)
            self._set_project_context(panel, ProjectViewState(project_name="renamed"))
            panel.zotero_libraries = [
                {"library_type": "group", "library_id": "42", "name": "Group"}
            ]
            select = panel.query_one("#zotero-library-select", Select)
            select.set_options([("Group", "group:42")])
            select.value = "group:42"

            panel.auto_match_zotero_items()

            adapter.match_items_by_archive_id.assert_called_once_with(
                "2508.18791", "42", "group"
            )
            self.assertEqual(panel.zotero_results[0]["item_key"], "MATCH")

    async def test_missing_artifacts_and_credential_name_are_reported(self) -> None:
        """缺失 PDF、Markdown 和具名凭据时给出明确提示。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False, initial_engine="lite")
        project = ProjectViewState(project_name="paper", engine="lite")
        async with app.run_test():
            panel = app.zotero_panel
            self._set_project_context(
                panel,
                project,
                input_type="pdf",
                arxiv_id="",
                engine="lite",
                config={"web_api_key_env": "TEST_MISSING_ZOTERO_KEY"},
            )
            panel.import_selected_project_to_zotero()
            self.assertEqual(project.zotero_status, "失败：当前项目没有 PDF。")

            project.translated_markdown_path = str(Path.cwd() / "missing.md")
            panel.populate_zotero_results([{"item_key": "ITEM1"}])
            panel.toggle_zotero_row_selection(0)
            panel.import_selected_project_markdown_to_zotero()
            self.assertEqual(project.zotero_status, "失败：当前项目没有译文 Markdown 文件。")

            markdown_path = Path.cwd() / "translated.md"
            markdown_path.write_text("# content", encoding="utf-8")
            project.translated_markdown_path = str(markdown_path)
            with patch.dict(os.environ, {}, clear=True):
                panel.import_selected_project_markdown_to_zotero()
            self.assertEqual(
                project.zotero_status,
                "失败：Web API key 环境变量未设置：TEST_MISSING_ZOTERO_KEY。",
            )

    async def test_pdf_import_continues_after_one_item_fails(self) -> None:
        """PDF 单项导入失败后继续处理其余已选条目。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False)
        project = ProjectViewState(project_name="paper", pdf_path=str(Path.cwd() / "paper.pdf"))
        adapter = Mock()
        adapter.attach_pdf.side_effect = [RuntimeError("rejected"), {"status": "uploaded"}]
        async with app.run_test():
            panel = app.zotero_panel
            panel.adapter_factory = Mock(return_value=adapter)
            self._set_project_context(
                panel,
                project,
                config={"web_api_key_env": "TEST_ZOTERO_KEY"},
            )
            panel.populate_zotero_results(
                [
                    {"item_key": "ONE", "library_id": "7", "library_type": "user"},
                    {"item_key": "TWO", "library_id": "42", "library_type": "group"},
                ]
            )
            panel.toggle_zotero_row_selection(0)
            panel.toggle_zotero_row_selection(1)
            with patch.dict(os.environ, {"TEST_ZOTERO_KEY": "fake-key"}, clear=True):
                panel.import_selected_project_to_zotero()

            self.assertEqual(adapter.attach_pdf.call_count, 2)
            self.assertEqual(
                project.zotero_status,
                "导入完成：成功 1，失败 1。 ONE: rejected",
            )

    async def test_local_pdf_import_does_not_require_web_key(self) -> None:
        """本地 PDF 导入按配置分流，不读取 Web API key。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False)
        project = ProjectViewState(project_name="paper", pdf_path=str(Path.cwd() / "paper.pdf"))
        adapter = Mock()
        async with app.run_test():
            panel = app.zotero_panel
            panel.adapter_factory = Mock(return_value=adapter)
            self._set_project_context(panel, project, config={"pdf_import_api": "local"})
            panel.populate_zotero_results([
                {"item_key": "ONE", "library_id": "0", "library_type": "user"}
            ])
            panel.toggle_zotero_row_selection(0)
            with patch.dict(os.environ, {}, clear=True):
                panel.import_selected_project_to_zotero()
            adapter.attach_pdf_local.assert_called_once_with(
                "ONE", project.pdf_path, "0", "user"
            )
            self.assertEqual(project.zotero_status, "导入完成：成功 1，失败 0。")

    async def test_markdown_import_continues_after_one_item_fails(self) -> None:
        """Markdown 单项导入失败后继续创建其余子笔记。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False, initial_engine="lite")
        markdown_path = Path.cwd() / "translated.md"
        markdown_path.write_text("# Title\n\nContent\n", encoding="utf-8")
        project = ProjectViewState(
            project_name="paper",
            engine="lite",
            translated_markdown_path=str(markdown_path),
        )
        adapter = Mock()
        adapter.create_note.side_effect = [RuntimeError("rejected"), {"item_key": "NOTE"}]
        async with app.run_test():
            panel = app.zotero_panel
            panel.adapter_factory = Mock(return_value=adapter)
            self._set_project_context(
                panel,
                project,
                input_type="pdf",
                arxiv_id="",
                engine="lite",
                config={"web_api_key_env": "TEST_ZOTERO_KEY"},
            )
            panel.populate_zotero_results(
                [
                    {"item_key": "ONE", "library_id": "7", "library_type": "user"},
                    {"item_key": "TWO", "library_id": "42", "library_type": "group"},
                ]
            )
            panel.toggle_zotero_row_selection(0)
            panel.toggle_zotero_row_selection(1)
            with patch.dict(os.environ, {"TEST_ZOTERO_KEY": "fake-key"}, clear=True):
                panel.import_selected_project_markdown_to_zotero()

            self.assertEqual(adapter.create_note.call_count, 2)
            adapter.create_note.assert_any_call(
                "TWO", "paper", "# Title\n\nContent\n", "42", "group"
            )
            self.assertEqual(
                project.zotero_status,
                "导入完成：成功 1，失败 1。 ONE: rejected",
            )

    async def test_app_delegate_syncs_latest_adapter_factory(self) -> None:
        """App 公共委托在每次调用前同步最新 adapter 工厂。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False)
        first = Mock()
        second = Mock()
        first.list_libraries.return_value = []
        second.list_libraries.return_value = []
        async with app.run_test():
            app.zotero_adapter_factory = Mock(return_value=first)
            event = Mock()
            event.tabbed_content.id = "detail-tabs"
            event.pane.id = "zotero-tab"
            app.project_detail.on_tabbed_content_tab_activated(event)
            app.zotero_adapter_factory = Mock(return_value=second)
            app.load_zotero_libraries()

            first.list_libraries.assert_called_once_with()
            second.list_libraries.assert_called_once_with()
            self.assertIs(app.zotero_panel.adapter_factory, app.zotero_adapter_factory)

    async def test_app_context_sync_handles_selection_engine_and_completion(self) -> None:
        """选择、引擎切换和产物刷新向面板提供一致上下文。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False)
        project = ProjectViewState(project_name="2508.18791", engine="heavy")
        task = TaskViewState(
            task_id="task-1",
            input_type="arxiv",
            inputs=["2508.18791"],
            projects=[project],
            engine="heavy",
        )
        async with app.run_test() as pilot:
            app.tasks = [task]
            app.select_project(project.project_name, task.task_id)
            panel = app.zotero_panel
            self.assertIs(panel.project, project)
            self.assertEqual(panel.task_id, "task-1")
            self.assertEqual(panel.arxiv_id, "2508.18791")

            panel.populate_zotero_results([{"item_key": "ITEM1"}])
            app.refresh_detail_page()
            self.assertEqual(len(panel.zotero_results), 1)

            app.select_project(project.project_name, task.task_id)
            self.assertEqual(panel.zotero_results, [])
            app.set_engine("lite")
            await app.workers.wait_for_complete()
            await pilot.pause()
            self.assertIsNone(panel.project)
            self.assertEqual(panel.engine, "lite")

    async def test_panel_status_updates_project_and_app_only_notifies(self) -> None:
        """面板写项目状态，App 消费消息时只调用统一通知入口。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False)
        project = ProjectViewState(project_name="paper")
        async with app.run_test() as pilot:
            panel = app.zotero_panel
            self._set_project_context(panel, project)
            with patch.object(app, "_notify") as notify:
                panel.query_one("#zotero-search-input", Input).value = ""
                panel.search_zotero_items()
                await pilot.pause()

            self.assertEqual(project.zotero_status, "搜索框为空。")
            notify.assert_called_once_with("搜索框为空。")


if __name__ == "__main__":
    unittest.main()
