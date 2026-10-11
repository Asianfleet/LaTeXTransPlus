import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from textual.widgets import DataTable, TextArea

from src.tui.app import LaTeXTransTuiApp
from src.tui.project_detail import ProjectDetail
from src.tui.state import ProjectStatus, ProjectViewState, TaskViewState


class TuiAppSplitTests(unittest.IsolatedAsyncioTestCase):
    """验证 App 拆分后只协调项目身份和任务生命周期。"""

    async def asyncSetUp(self) -> None:
        """将整个 UI 生命周期放入临时目录并拦截配置访问。"""
        self.original_cwd = Path.cwd()
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.addCleanup(os.chdir, self.original_cwd)
        os.chdir(self.temporary.name)
        self.save = Mock()
        self.adapter = Mock()
        self.adapter.list_libraries.return_value = []
        targets = {
            "src.tui.app.load_ui_config": Mock(return_value={}),
            "src.tui.app.ZoteroAdapter": Mock(return_value=self.adapter),
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

    async def test_project_detail_is_direct_root_and_owns_single_zotero_panel(self) -> None:
        """详情组件直接占据 detail 页面且 App 代理同一个 Zotero 面板。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False)
        self.assertIsInstance(app.project_detail, ProjectDetail)
        self.assertIs(app.zotero_panel, app.project_detail.zotero_panel)
        async with app.run_test():
            self.assertIs(app.query_one("#detail"), app.project_detail)
            self.assertIs(app.query_one("#zotero-tab"), app.zotero_panel)
            self.assertIs(app.project_detail.parent, app.query_one("#main-switcher"))

    async def test_same_name_project_log_routes_by_task_identity(self) -> None:
        """同名项目的日志只刷新当前选中的任务。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False)
        first = TaskViewState(input_type="arxiv", inputs=["same"], task_id="first")
        second = TaskViewState(input_type="arxiv", inputs=["same"], task_id="second")
        first.projects = [ProjectViewState(project_name="same")]
        second.projects = [ProjectViewState(project_name="same")]
        app.tasks = [first, second]
        async with app.run_test() as pilot:
            app.select_project("same", task_id="first")
            await pilot.pause()
            with patch.object(app.project_detail, "refresh_log_and_terms") as refresh:
                app.handle_runtime_event(
                    {"type": "project_log", "project_name": "same", "line": "other"},
                    second,
                )
                refresh.assert_not_called()
                app.handle_runtime_event(
                    {"type": "project_log", "project_name": "same", "line": "selected"},
                    first,
                )
                refresh.assert_called_once_with(first.task_log_lines)

    async def test_log_events_skip_project_lists_and_metadata_writes(self) -> None:
        """日志事件只交给详情组件，不重建列表或写项目元数据。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False)
        task = TaskViewState(input_type="arxiv", inputs=["paper"], task_id="task")
        task.projects = [ProjectViewState(project_name="paper")]
        app.current_task = task
        app.tasks = [task]
        async with app.run_test():
            app.select_project("paper", task_id="task")
            with patch.object(app, "refresh_project_list") as refresh_list, patch.object(
                app, "refresh_task_table"
            ) as refresh_table, patch.object(app, "_persist_project_event") as persist, patch.object(
                app.project_detail, "refresh_log"
            ) as refresh_log:
                app.handle_runtime_event({"type": "task_log", "line": "prepare"}, task)
            refresh_log.assert_called_once_with(task.task_log_lines)
            refresh_list.assert_not_called()
            refresh_table.assert_not_called()
            persist.assert_not_called()

    async def test_engine_switch_preserves_task_engine_and_syncs_detail(self) -> None:
        """会话切引擎只更新视图，不改写已经创建的任务引擎。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False)
        task = TaskViewState(input_type="arxiv", inputs=["paper"], task_id="task", engine="heavy")
        app.current_task = task
        app.tasks = [task]
        app.set_engine("lite")
        self.assertEqual(task.engine, "heavy")
        self.assertEqual(app.project_detail.effective_engine, "lite")

    async def test_completion_refreshes_only_selected_identity_without_resetting_zotero(self) -> None:
        """完成事件刷新当前产物，并保留同一项目的 Zotero 选择。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False)
        task = TaskViewState(input_type="arxiv", inputs=["2508.18791"], task_id="task", total=1)
        project = ProjectViewState(project_name="2508.18791", status=ProjectStatus.RUNNING)
        task.projects = [project]
        app.current_task = task
        app.tasks = [task]
        async with app.run_test():
            app.select_project(project.project_name, task.task_id)
            panel = app.zotero_panel
            panel.populate_zotero_results([{"item_key": "ITEM1", "title": "Paper"}])
            panel.toggle_zotero_row_selection(0)
            with patch.object(app.project_detail, "show_project", wraps=app.project_detail.show_project) as show:
                app.handle_runtime_event(
                    {
                        "type": "project_complete",
                        "project_name": project.project_name,
                        "pdf_path": "paper.pdf",
                    },
                    task,
                )
            self.assertEqual(project.pdf_path, "paper.pdf")
            self.assertEqual(panel.zotero_selected_keys, {"ITEM1"})
            self.assertTrue(show.called)
            self.assertFalse(show.call_args.kwargs["reset_zotero"])

    async def test_select_project_explicitly_resets_zotero_results(self) -> None:
        """用户显式选择项目时要求详情组件重置 Zotero 结果。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False)
        task = TaskViewState(input_type="arxiv", inputs=["first", "second"], task_id="task")
        task.projects = [
            ProjectViewState(project_name="first"),
            ProjectViewState(project_name="second"),
        ]
        app.tasks = [task]
        async with app.run_test():
            app.select_project("first", task.task_id)
            app.zotero_panel.populate_zotero_results([{"item_key": "ITEM1", "title": "Paper"}])
            with patch.object(app.project_detail, "show_project", wraps=app.project_detail.show_project) as show:
                app.select_project("second", task.task_id)
            self.assertTrue(show.call_args.kwargs["reset_zotero"])
            self.assertEqual(app.zotero_panel.zotero_results, [])

    async def test_selected_history_task_supplies_its_own_arxiv_id(self) -> None:
        """历史任务项目使用所属任务输入，不误取当前任务的 arXiv ID。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False)
        current = TaskViewState(
            input_type="arxiv",
            inputs=["https://arxiv.org/abs/1111.11111"],
            task_id="current",
        )
        history = TaskViewState(
            input_type="arxiv",
            inputs=["https://arxiv.org/abs/2222.22222"],
            task_id="history",
        )
        history.projects = [ProjectViewState(project_name="renamed-paper")]
        app.current_task = current
        app.tasks = [current, history]
        async with app.run_test():
            app.select_project("renamed-paper", history.task_id)
            self.assertEqual(app.zotero_panel.arxiv_id, "2222.22222")

    async def test_entry_enter_submits_once(self) -> None:
        """入口输入框按 Enter 只创建并启动一次任务。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False)
        async with app.run_test() as pilot:
            batch_input = app.query_one("#batch-input", TextArea)
            batch_input.text = "2508.18791"
            batch_input.focus()
            with patch.object(app, "start_current_task") as start, patch.object(app, "notify"):
                await pilot.press("enter")
                await pilot.pause()
            start.assert_called_once_with()
            self.assertEqual(len(app.tasks), 1)

    async def test_project_and_zotero_clicks_toggle_once_across_resize(self) -> None:
        """项目表和 Zotero 表单击仅切换一次，缩放后保留选择与游标。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False)
        task = TaskViewState(input_type="arxiv", inputs=["paper"], task_id="task", total=1)
        task.projects = [ProjectViewState(project_name="paper", status=ProjectStatus.COMPLETED)]
        app.tasks = [task]
        async with app.run_test(size=(200, 40)) as pilot:
            app.refresh_task_table()
            app.action_project_manager()
            await pilot.pause()
            task_table = app.query_one("#task-table", DataTable)
            self.assertTrue(await pilot.click(task_table, offset=(1, 1)))
            await pilot.pause()
            self.assertEqual(task_table.get_cell_at((0, 0)), "[√]")
            task_wide = tuple(column.width for column in task_table.ordered_columns)

            await pilot.resize_terminal(140, 40)
            for _ in range(10):
                await pilot.pause(0.05)
                if tuple(column.width for column in task_table.ordered_columns) != task_wide:
                    break
            self.assertNotEqual(
                tuple(column.width for column in task_table.ordered_columns),
                task_wide,
            )
            await pilot.resize_terminal(62, 24)
            await pilot.pause()
            self.assertEqual(task_table.get_cell_at((0, 0)), "[√]")
            self.assertEqual(task_table.cursor_coordinate.row, 0)

            app.select_project("paper", task.task_id)
            app.query_one("#detail-tabs").active = "zotero-tab"
            app.zotero_panel.populate_zotero_results(
                [{"item_key": "ITEM1", "title": "Paper"}]
            )
            await pilot.pause()
            self.adapter.list_libraries.assert_called()
            zotero_table = app.query_one("#zotero-results", DataTable)
            self.assertTrue(await pilot.click(zotero_table, offset=(10, 1)))
            await pilot.pause()
            self.assertEqual(app.zotero_panel.zotero_selected_keys, {"ITEM1"})
            zotero_narrow = tuple(column.width for column in zotero_table.ordered_columns)

            await pilot.resize_terminal(140, 40)
            for _ in range(10):
                await pilot.pause(0.05)
                if tuple(column.width for column in zotero_table.ordered_columns) != zotero_narrow:
                    break
            zotero_wide = tuple(column.width for column in zotero_table.ordered_columns)
            self.assertNotEqual(zotero_wide, zotero_narrow)
            await pilot.resize_terminal(62, 24)
            for _ in range(10):
                await pilot.pause(0.05)
                if tuple(column.width for column in zotero_table.ordered_columns) != zotero_wide:
                    break
            self.assertNotEqual(
                tuple(column.width for column in zotero_table.ordered_columns),
                zotero_wide,
            )
            self.assertEqual(app.zotero_panel.zotero_selected_keys, {"ITEM1"})
            self.assertEqual(zotero_table.cursor_coordinate.row, 0)

    async def test_cancelled_task_ignores_late_completion(self) -> None:
        """任务取消后到达的完成事件不能覆盖 cancelled 状态。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False)
        handle = Mock()
        task = TaskViewState(input_type="arxiv", inputs=["paper"], task_id="task", total=1)
        task.projects = [ProjectViewState(project_name="paper", status=ProjectStatus.RUNNING)]
        app.current_task = task
        app.tasks = [task]
        app.task_processes[task.task_id] = handle
        async with app.run_test():
            with patch("src.tui.app.terminate_tui_task_process"):
                app.terminate_task_process(task.task_id)
            app.handle_runtime_event(
                {"type": "project_complete", "project_name": "paper"},
                task,
            )
        self.assertEqual(task.projects[0].status, ProjectStatus.CANCELLED)

    async def test_replaced_runner_branch_still_receives_task_engine(self) -> None:
        """替换旧 runner 的兼容分支仍被调用且使用任务自身引擎。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False)
        task = TaskViewState(
            input_type="arxiv",
            inputs=["paper"],
            task_id="task",
            engine="heavy",
        )
        app.current_task = task
        app.tasks = [task]
        fake_runner = Mock(return_value={"completed_projects": [], "failed_projects": []})
        async with app.run_test():
            with patch("src.tui.app.run_tui_task", fake_runner):
                app.start_current_task()
                await app.workers.wait_for_complete()
        fake_runner.assert_called_once()
        self.assertEqual(fake_runner.call_args.kwargs["engine"], "heavy")


if __name__ == "__main__":
    unittest.main()


