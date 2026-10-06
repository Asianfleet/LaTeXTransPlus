"""两种 TUI 模式的 profile、标题展示和项目表回归测试。"""

import hashlib
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from textual.widgets import ListView, Select, Static

from src.tui.app import PAGE_TASKS, LaTeXTransTuiApp, ProjectManagementTable
from src.tui.history import read_project_metadata
from src.tui.state import TaskViewState


class TuiMetadataUiTests(unittest.IsolatedAsyncioTestCase):
    """在完整交互生命周期隔离真实 UI 配置保存。"""

    async def asyncSetUp(self):
        """记录配置哈希并拦截全部保存入口。"""
        self.config_path = Path.cwd() / "config/ui.toml"
        self.config_hash = hashlib.sha256(self.config_path.read_bytes()).hexdigest()
        self.save = Mock()
        self.patchers = [patch("src.tui.app.save_ui_config", self.save),
                         patch("src.tui.config.save_ui_config", self.save)]
        for patcher in self.patchers:
            patcher.start()

    async def asyncTearDown(self):
        """确保异步事件结束后真实配置仍完全相同。"""
        for patcher in reversed(self.patchers):
            patcher.stop()
        self.assertEqual(hashlib.sha256(self.config_path.read_bytes()).hexdigest(), self.config_hash)

    async def test_profile_selection_saves_in_both_modes(self):
        """下拉选中项写入 profile，初次填充不触发保存。"""
        for engine in ("heavy", "lite"):
            self.save.reset_mock()
            config = {"engine": engine, "llm_config": {"profile": "a"}}
            with patch("src.tui.app.load_ui_config", return_value=config), patch(
                "src.tui.app.list_llm_profiles", return_value=[("a", "a"), ("b", "b")], create=True
            ):
                app = LaTeXTransTuiApp(load_history_on_mount=False, initial_engine=engine)
                async with app.run_test() as pilot:
                    await pilot.pause()
                    await pilot.click("#settings-button")
                    await pilot.pause()
                    select = app.query_one("#config-llm_config-profile", Select)
                    self.assertEqual(select.value, "a")
                    self.save.assert_not_called()
                    select.value = "b"
                    await pilot.pause()
                    self.assertEqual(self.save.call_args.args[1]["llm_config"], {"profile": "b"})

    async def test_missing_and_empty_profiles_do_not_change_saved_value(self):
        """空目录保留失效值并提示，完全未配置时保持空选项。"""
        for profile in ("missing", ""):
            self.save.reset_mock()
            config = {"llm_config": {"profile": profile}}
            with patch("src.tui.app.load_ui_config", return_value=config), patch(
                "src.tui.app.list_llm_profiles", return_value=[], create=True
            ):
                app = LaTeXTransTuiApp(load_history_on_mount=False)
                async with app.run_test() as pilot:
                    await pilot.pause()
                    await pilot.click("#settings-button")
                    await pilot.pause()
                    select = app.query_one("#config-llm_config-profile", Select)
                    self.assertEqual("" if select.is_blank() else select.value, profile)
                    self.assertIn("没有可用", str(app.query_one("#config-llm_config-profile-hint", Static).content))
                    self.save.assert_not_called()

    async def test_metadata_refresh_persists_title_and_model_and_preserves_selection(self):
        """两种模式实时显示元数据，长标题悬浮可读，缩放后列宽更新。"""
        for engine in ("heavy", "lite"):
            with TemporaryDirectory() as directory:
                app = LaTeXTransTuiApp(load_history_on_mount=False, initial_engine=engine)
                title = ("完整标题 [不是样式] " + "研究 Title " * 30).strip()
                task = TaskViewState(input_type="local", inputs=["paper"], task_id="task", engine=engine)
                app.tasks = [task]
                async with app.run_test(size=(120, 40), tooltips=True) as pilot:
                    app.handle_runtime_event({"type": "project_start", "project_name": "paper", "output_dir": directory}, task)
                    app.selected_project_keys.add(("task", "paper"))
                    app.handle_runtime_event({"type": "project_metadata", "project_name": "paper", "title": title,
                                              "translation_model": "model-a"}, task)
                    app.switch_page(PAGE_TASKS)
                    await pilot.pause()
                    metadata = read_project_metadata(Path(directory))
                    self.assertEqual(metadata.get("title"), title)
                    self.assertEqual(metadata.get("translation_model"), "model-a")
                    table = app.query_one("#task-table", ProjectManagementTable)
                    self.assertEqual([str(column.label) for column in table.columns.values()],
                                     ["选中", "项目", "标题", "翻译模型", "状态", "任务 id"])
                    self.assertEqual(str(table.get_row_at(0)[2]), title)
                    self.assertEqual(str(table.get_row_at(0)[3]), "model-a")
                    self.assertEqual(table.get_row_at(0)[0], "[√]")
                    item = app.query_one("#project-list", ListView).children[0]
                    label = item.query_one(Static)
                    self.assertIn(title, str(item.tooltip))
                    rendered = "\n".join(strip.text for strip in label.render_lines(label.size.region))
                    self.assertIn("…", rendered)
                    self.assertEqual(label.size.height, 1)
                    await pilot.hover(label)
                    await pilot.pause(0.6)
                    tooltip = app.screen.query("Tooltip").first()
                    self.assertTrue(tooltip.display)
                    self.assertIn(title, str(tooltip.content))
                    old_width = list(table.columns.values())[2].width
                    await pilot.resize_terminal(180, 40)
                    await pilot.pause()
                    self.assertGreater(list(table.columns.values())[2].width, old_width,
                                       (table.size, table.parent.size, app.query_one("#main-switcher").size))
                    self.assertIn(("task", "paper"), app.selected_project_keys)
