"""侧栏实时进度及项目身份隔离的回归测试。"""

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from textual.widgets import ListView, Static

from src.tui.app import LaTeXTransTuiApp
from src.tui.state import ProjectStatus, ProjectViewState, TaskViewState


class ProjectProgressTests(unittest.IsolatedAsyncioTestCase):
    """在隔离配置的完整 UI 生命周期中验证进度更新。"""

    async def asyncSetUp(self) -> None:
        """隔离工作目录并拦截配置保存和配置页外部查询。"""
        original = Path.cwd()
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.addCleanup(os.chdir, original)
        os.chdir(temporary.name)
        for target, value in (
            ("src.tui.config_page.save_ui_config", None),
            ("src.tui.config.save_ui_config", None),
            ("src.tui.app.load_ui_config", {}),
            ("src.tui.config_page.load_ui_config", {}),
            ("src.tui.config_page.list_llm_profiles", []),
            ("src.tui.config_page.list_available_font_families", []),
        ):
            patcher = patch(target, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)

    async def test_log_updates_only_matching_item_without_rebuilding_list(self) -> None:
        """同名项目的进度不串任务，更新保留条目、选择和滚动位置。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False)
        first = TaskViewState(input_type="arxiv", inputs=["paper"], task_id="first")
        second = TaskViewState(input_type="arxiv", inputs=["paper"], task_id="second")
        for task in (first, second):
            task.projects = [ProjectViewState("paper", ProjectStatus.RUNNING)]
        first.projects.extend(
            ProjectViewState(f"extra-{index}", ProjectStatus.COMPLETED)
            for index in range(40)
        )
        app.tasks = [first, second]
        async with app.run_test(size=(120, 35)) as pilot:
            app.refresh_project_list()
            await pilot.pause()
            view = app.query_one("#project-list", ListView)
            items = list(view.children)
            view.index = 1
            view.scroll_to(y=10, animate=False)
            await pilot.pause()
            scroll_y = view.scroll_y
            app.handle_runtime_event(
                {"type": "project_log", "project_name": "paper",
                 "line": "[############------------] 52.6% Translating sections: 10/19"},
                second,
            )
            await pilot.pause()
            self.assertEqual(list(view.children), items)
            self.assertEqual(view.index, 1)
            self.assertEqual(view.scroll_y, scroll_y)
            self.assertFalse(items[0].query_one(".project-progress", Static).display)
            progress = items[-1].query_one(".project-progress", Static)
            self.assertTrue(progress.display)
            self.assertIn("⌊ Translating sections: 10/19", str(progress.content))

    async def test_progress_has_two_rows_and_terminal_event_restores_one(self) -> None:
        """运行进度占第二行，缩窄侧栏仍为两行，完成后恢复一行。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False)
        task = TaskViewState(input_type="arxiv", inputs=["2605.27354"], task_id="task")
        task.projects = [ProjectViewState(
            "2605.27354", ProjectStatus.RUNNING, title="Guiding LLM Post-training"
        )]
        app.tasks = [task]
        async with app.run_test(size=(160, 40)) as pilot:
            app.refresh_project_list()
            await pilot.pause()
            app.handle_runtime_event(
                {"type": "project_log", "project_name": "2605.27354",
                 "line": "Compiling PDF document..."}, task,
            )
            await pilot.pause()
            item = app.query_one("#project-list", ListView).children[0]
            self.assertEqual(item.size.height, 2)
            await pilot.resize_terminal(80, 30)
            await pilot.pause()
            self.assertEqual(item.size.height, 2)
            progress = item.query_one(".project-progress", Static)
            self.assertLessEqual(progress.region.right, item.region.right)
            self.assertIn("⌊ Comp", progress.render_line(0).text)
            self.assertIn("Compiling PDF document", str(progress.tooltip))
            app.handle_runtime_event(
                {"type": "project_complete", "project_name": "2605.27354"}, task,
            )
            await pilot.pause()
            item = app.query_one("#project-list", ListView).children[0]
            self.assertEqual(item.size.height, 1)
            self.assertFalse(item.query_one(".project-progress", Static).display)
