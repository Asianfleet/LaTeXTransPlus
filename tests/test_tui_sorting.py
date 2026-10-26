"""验证任务表与侧栏的排序方向和点击行为。"""

from rich.cells import cell_len
from textual.widgets import Button, DataTable, ListView, Select

from src.tui.app import LaTeXTransTuiApp
from src.tui.state import ProjectStatus, ProjectViewState, TaskViewState
from src.tui.sidebar import SidebarLayout
from tests.test_tui_app import TuiAppTests


class TuiSortingTests(TuiAppTests):
    """在隔离配置的真实 TUI 中验证排序与项目身份。"""

    def _make_app(self):
        """构造各列顺序不同的三个任务，暴露错误的排序键。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False)
        for day, name, title, model, status in (
            (1, "gamma", "Alpha", "zeta", ProjectStatus.RUNNING),
            (2, "alpha", "Zulu", "alpha", ProjectStatus.FAILED),
            (3, "beta", "Middle", "middle", ProjectStatus.COMPLETED),
        ):
            task = TaskViewState(input_type="arxiv", inputs=[name], task_id=f"2026100{day}T120000.000")
            task.projects.append(ProjectViewState(
                project_name=name, title=title, translation_model=model, status=status,
            ))
            app.tasks.append(task)
        return app

    def _table_names(self, table):
        """读取表格当前显示的项目名顺序。"""
        return [table.get_cell_at((row, 1)).plain for row in range(table.row_count)]

    async def _click_header(self, pilot, table, column):
        """按实际列宽点击表头，覆盖鼠标事件与排序的连接。"""
        x = sum(item.get_render_width(table) for item in table.ordered_columns[:column]) + 1
        self.assertTrue(await pilot.click(table, offset=(x, 0)))
        await pilot.pause()

    async def test_task_table_defaults_to_newest_task_id_and_selects_displayed_row(self):
        """默认新任务在前，点击和键盘选择使用显示行的完整身份。"""
        app = self._make_app()
        async with app.run_test(size=(200, 40)) as pilot:
            app.action_project_manager()
            app.refresh_task_table()
            await pilot.pause()
            table = app.query_one("#task-table", DataTable)
            self.assertEqual(self._table_names(table), ["beta", "alpha", "gamma"])
            await pilot.click(table, offset=(1, 1))
            await pilot.pause()
            self.assertEqual(app.selected_project_keys, {(app.tasks[2].task_id, "beta")})
            table.move_cursor(row=2)
            await pilot.press("enter")
            await pilot.pause()
            self.assertEqual(app.selected_project_keys, {
                (app.tasks[2].task_id, "beta"), (app.tasks[0].task_id, "gamma"),
            })

    async def test_every_header_sorts_and_repeated_click_reverses(self):
        """六个表头均可排序，重复点击反转，刷新和缩放后保留排序。"""
        app = self._make_app()
        app.selected_project_keys = {(app.tasks[1].task_id, "alpha")}
        async with app.run_test(size=(200, 40)) as pilot:
            app.action_project_manager()
            app.refresh_task_table()
            await pilot.pause()
            table = app.query_one("#task-table", DataTable)
            for column, ascending, descending in (
                (0, ["gamma", "beta", "alpha"], ["alpha", "gamma", "beta"]),
                (1, ["alpha", "beta", "gamma"], ["gamma", "beta", "alpha"]),
                (2, ["gamma", "beta", "alpha"], ["alpha", "beta", "gamma"]),
                (3, ["alpha", "beta", "gamma"], ["gamma", "beta", "alpha"]),
                (4, ["beta", "alpha", "gamma"], ["gamma", "alpha", "beta"]),
                (5, ["gamma", "alpha", "beta"], ["beta", "alpha", "gamma"]),
            ):
                with self.subTest(column=column):
                    await self._click_header(pilot, table, column)
                    self.assertEqual(self._table_names(table), ascending)
                    await self._click_header(pilot, table, column)
                    self.assertEqual(self._table_names(table), descending)
                    self.assertEqual(app.selected_project_keys, {(app.tasks[1].task_id, "alpha")})
                    app.refresh_task_table()
                    await pilot.pause()
                    self.assertEqual(self._table_names(table), descending)
            await pilot.resize_terminal(130, 35)
            await pilot.pause()
            self.assertEqual(self._table_names(table), ["beta", "alpha", "gamma"])
            # 排序后的悬浮提示仍须指向显示行，而不是原始行。
            self.assertEqual(table._cell_tooltips[(0, 2)], "Middle")

    async def test_sidebar_defaults_to_creation_time_and_direction_button_reverses(self):
        """侧栏默认创建时间降序，方向按钮位于选择器右侧并保持项目身份。"""
        app = self._make_app()
        app.selected_task_id = app.tasks[2].task_id
        app.selected_project_name = "beta"
        async with app.run_test(size=(120, 40)) as pilot:
            app.refresh_project_list()
            await pilot.pause()
            select = app.query_one("#project-sort-select", Select)
            direction = app.query_one("#project-sort-direction-button", Button)
            items = app.query_one("#project-list", ListView)
            self.assertEqual(select.value, "created_at")
            self.assertEqual(str(direction.label), "↓")
            self.assertEqual([item.project_key[1] for item in items.children], ["beta", "alpha", "gamma"])
            self.assertGreaterEqual(direction.region.x, select.region.right)
            self.assertEqual(direction.region.y, select.region.y)
            await pilot.click(direction)
            await pilot.pause()
            self.assertEqual(str(direction.label), "↑")
            self.assertEqual([item.project_key[1] for item in items.children], ["gamma", "alpha", "beta"])
            self.assertEqual(items.index, 2)
            select.value = "title"
            await pilot.pause()
            self.assertEqual(str(direction.label), "↑")
            self.assertEqual([item.project_key[1] for item in items.children], ["gamma", "beta", "alpha"])
            await pilot.click(direction)
            await pilot.pause()
            self.assertEqual(str(direction.label), "↓")
            self.assertEqual([item.project_key[1] for item in items.children], ["alpha", "beta", "gamma"])
            self.assertEqual(app.selected_project_name, "beta")
            self.assertEqual(app.selected_task_id, app.tasks[2].task_id)

    async def test_sidebar_direction_button_keeps_fixed_width_when_sidebar_resizes(self):
        """侧栏宽度变化时方向按钮固定三列，选择器填满其余空间。"""
        app = self._make_app()
        async with app.run_test(size=(200, 40)) as pilot:
            layout = app.query_one(SidebarLayout)
            controls = app.query_one("#project-sort-controls")
            select = app.query_one("#project-sort-select", Select)
            direction = app.query_one("#project-sort-direction-button", Button)
            for width in (26, 60, 34):
                with self.subTest(sidebar_width=width):
                    layout.set_sidebar_width(width)
                    await pilot.pause()
                    self.assertEqual(direction.region.width, 3)
                    self.assertEqual(select.region.width, controls.content_size.width - 3)
                    self.assertEqual(direction.region.x, select.region.right)
                    self.assertEqual(direction.region.right, controls.content_region.right)

    async def test_sidebar_direction_button_renders_within_fixed_width_in_all_states(self):
        """箭头按钮各交互状态的每行实际绘制宽度均不超出三列。"""
        app = self._make_app()
        async with app.run_test(size=(200, 40)) as pilot:
            direction = app.query_one("#project-sort-direction-button", Button)
            for label in ("↓", "↑"):
                direction.label = label
                direction.blur()
                direction.remove_class("-active")
                await pilot.hover("#project-sort-select")
                await pilot.pause()
                for state in ("normal", "hover", "focus", "active"):
                    if state == "hover":
                        await pilot.hover(direction)
                    elif state == "focus":
                        direction.focus()
                        await pilot.hover("#project-sort-select")
                    elif state == "active":
                        direction.add_class("-active")
                    await pilot.pause()
                    for row, strip in enumerate(direction.render_lines(direction.region.reset_offset)):
                        with self.subTest(label=label, state=state, row=row):
                            # 渲染缓存报告的宽度可能仍为三列，必须检查实际输出字符。
                            self.assertEqual(cell_len(strip.text), direction.region.width)
