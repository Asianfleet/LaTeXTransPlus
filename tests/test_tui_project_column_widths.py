"""验证项目管理表紧凑列宽和状态完整显示。"""

import os
import unittest
from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from rich.text import Text

from src.tui.app import PAGE_TASKS, LaTeXTransTuiApp, ProjectManagementTable
from src.tui.state import ProjectStatus, ProjectViewState, TaskViewState


class ProjectColumnWidthsTests(unittest.IsolatedAsyncioTestCase):
    """隔离真实配置，检查列宽在终端缩放和错误数变化后更新。"""

    async def test_compact_identity_columns_leave_full_status_visible(self):
        """项目及任务 id 减少留白，状态在窄屏及多位错误数下保持完整。"""
        original_cwd = Path.cwd()
        with TemporaryDirectory() as temp_dir, ExitStack() as stack:
            os.chdir(temp_dir)
            try:
                for target, value in {
                    "src.tui.app.load_ui_config": {},
                    "src.tui.config_page.load_ui_config": {},
                    "src.tui.config_page.list_llm_profiles": [],
                    "src.tui.config_page.list_available_font_families": [],
                }.items():
                    stack.enter_context(patch(target, return_value=value))
                for target in ("src.tui.config.save_ui_config", "src.tui.config_page.save_ui_config"):
                    stack.enter_context(patch(target))
                project = ProjectViewState(
                    project_name="2604.26904", status=ProjectStatus.COMPLETED_WITH_ERRORS,
                    validation_summary={"errors": 123},
                )
                task = TaskViewState(input_type="arxiv", inputs=[project.project_name],
                                     task_id="20261013-123456", projects=[project])
                app = LaTeXTransTuiApp(load_history_on_mount=False)
                app.tasks = [task]
                async with app.run_test(size=(160, 40)) as pilot:
                    app.switch_page(PAGE_TASKS)
                    await pilot.pause()
                    table = app.query_one("#task-table", ProjectManagementTable)
                    title_widths = []
                    for size, errors in (((160, 40), 123), ((120, 40), 123456), ((80, 30), 1)):
                        project.validation_summary = {"errors": errors}
                        app.refresh_task_table()
                        await pilot.resize_terminal(*size)
                        await pilot.pause()
                        columns = list(table.columns.values())
                        self.assertLess(columns[1].width, 18)
                        self.assertLess(columns[5].width, 23)
                        self.assertGreaterEqual(columns[1].width, Text(project.project_name).cell_len)
                        self.assertGreaterEqual(columns[5].width, Text(task.task_id).cell_len)
                        self.assertGreaterEqual(columns[4].width, Text(project.status_label).cell_len)
                        title_widths.append(columns[2].width)
                    self.assertGreater(title_widths[0], title_widths[-1])
            finally:
                os.chdir(original_cwd)
