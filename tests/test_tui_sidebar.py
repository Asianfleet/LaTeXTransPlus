"""侧栏拖动和会话宽度的回归测试。"""

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from src.tui.app import LaTeXTransTuiApp


class TuiSidebarTests(unittest.IsolatedAsyncioTestCase):
    """使用真实布局验证鼠标调节，并隔离用户配置。"""

    async def asyncSetUp(self) -> None:
        """将整个交互生命周期放在临时工作目录。"""
        original = Path.cwd()
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.addCleanup(os.chdir, original)
        os.chdir(temporary.name)
        for target in (
            "src.tui.config_page.save_ui_config",
            "src.tui.config.save_ui_config",
        ):
            patcher = patch(target)
            patcher.start()
            self.addCleanup(patcher.stop)
        for target, value in (
            ("src.tui.app.load_ui_config", {}),
            ("src.tui.config_page.load_ui_config", {}),
            ("src.tui.config_page.list_llm_profiles", []),
            ("src.tui.config_page.list_available_font_families", []),
        ):
            patcher = patch(target, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)

    async def test_drag_limits_and_mouse_release(self) -> None:
        """拖动实时更新宽度，越界受限且松开后不再跟随。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False)
        async with app.run_test(size=(160, 45)) as pilot:
            await pilot.pause()
            sidebar = app.query_one("#sidebar")
            self.assertTrue(await pilot.mouse_down("#sidebar-rule", offset=(0, 5)))
            self.assertIs(app.mouse_captured, app.query_one("#sidebar-rule"))
            await pilot.hover(offset=(60, 5))
            await pilot.pause()
            self.assertEqual(sidebar.region.width, 60)
            await pilot.hover(offset=(150, 5))
            await pilot.pause()
            self.assertEqual(sidebar.region.width, 80)
            await pilot.hover(offset=(0, 5))
            await pilot.pause()
            self.assertEqual(sidebar.region.width, 20)
            await pilot.mouse_up(offset=(0, 5))
            await pilot.hover(offset=(100, 5))
            await pilot.pause()
            self.assertEqual(sidebar.region.width, 20)
            self.assertIsNone(app.mouse_captured)

    async def test_resize_preserves_ratio_and_new_session_resets(self) -> None:
        """缩放保留会话比例，新 App 恢复默认比例。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False)
        async with app.run_test(size=(160, 45)) as pilot:
            await pilot.pause()
            await pilot.mouse_down("#sidebar-rule", offset=(0, 5))
            await pilot.hover(offset=(80, 5))
            await pilot.mouse_up(offset=(80, 5))
            await pilot.resize_terminal(80, 35)
            await pilot.pause()
            self.assertEqual(app.query_one("#sidebar").region.width, 40)
            await pilot.resize_terminal(161, 45)
            await pilot.pause()
            self.assertEqual(app.query_one("#sidebar").region.width, 80)
        fresh = LaTeXTransTuiApp(load_history_on_mount=False)
        async with fresh.run_test(size=(160, 45)) as pilot:
            await pilot.pause()
            self.assertEqual(fresh.query_one("#sidebar").region.width, 32)

    async def test_right_button_does_not_resize(self) -> None:
        """仅左键可启动拖动。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False)
        async with app.run_test(size=(160, 45)) as pilot:
            await pilot.pause()
            width = app.query_one("#sidebar").size.width
            await pilot.mouse_down("#sidebar-rule", button=3)
            await pilot.hover(offset=(80, 5))
            await pilot.pause()
            self.assertEqual(app.query_one("#sidebar").size.width, width)
            self.assertIsNone(app.mouse_captured)

    async def test_drag_does_not_select_text_and_title_remains_selectable(self) -> None:
        """分隔线拖动不选中文字，标题的普通文本选择仍可使用。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False)
        async with app.run_test(size=(160, 45)) as pilot:
            await pilot.pause()
            title = app.query_one("#app-title")
            title_y = title.region.y + 1
            await pilot.mouse_down("#sidebar-rule", offset=(0, title_y))
            await pilot.hover(offset=(140, title_y + 2))
            await pilot.pause()
            self.assertFalse(app.screen.selections)
            await pilot.hover(offset=(3, 5))
            await pilot.pause()
            self.assertFalse(app.screen.selections)
            await pilot.mouse_up(offset=(3, 5))
            await pilot.pause()
            self.assertFalse(app.screen.selections)

            await pilot.mouse_down("#app-title", offset=(1, 1))
            await pilot.hover("#app-title", offset=(10, 2))
            await pilot.mouse_up("#app-title", offset=(10, 2))
            await pilot.pause()
            self.assertTrue(app.screen.selections)
