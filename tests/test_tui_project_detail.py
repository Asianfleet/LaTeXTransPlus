import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from rich.syntax import Syntax
from textual.widgets import DataTable, RichLog, Static, TabbedContent

from src.tui.app import LaTeXTransTuiApp
from src.tui.project_detail import (
    ProjectDetail,
    _merge_project_log_text,
    compact_progress_log_for_display,
)
from src.tui.state import ProjectViewState


class TuiProjectDetailTests(unittest.IsolatedAsyncioTestCase):
    """验证项目详情组件独立维护展示上下文和局部刷新。"""

    async def asyncSetUp(self) -> None:
        """将 UI 生命周期放入临时目录并拦截配置和外部适配器。"""
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

    def test_log_helpers_merge_pending_lines_and_compact_progress(self) -> None:
        """日志合并去重准备行，连续进度只保留首中末三行。"""
        merged = _merge_project_log_text(
            "[ParserAgent] parsed\n",
            ["Downloading paper", "[ParserAgent] parsed"],
        )
        self.assertEqual(
            merged.splitlines(),
            ["Downloading paper", "[ParserAgent] parsed"],
        )
        progress = "\n".join(
            [
                "before",
                "[##----------------------]  10.0% step 1",
                "[####--------------------]  20.0% step 2",
                "[######------------------]  30.0% step 3",
                "[########----------------]  40.0% step 4",
                "[##########--------------]  50.0% step 5",
                "after",
            ]
        )
        self.assertEqual(
            compact_progress_log_for_display(progress).splitlines(),
            [
                "before",
                "[##----------------------]  10.0% step 1",
                "[######------------------]  30.0% step 3",
                "[##########--------------]  50.0% step 5",
                "after",
            ],
        )

    def test_set_engine_before_mount_only_records_engine(self) -> None:
        """未挂载时切换引擎不查询控件，挂载后再应用标签显隐。"""
        detail = ProjectDetail("heavy", adapter_factory=Mock())
        detail.set_engine("lite")
        self.assertEqual(detail.effective_engine, "lite")

    async def test_heavy_and_lite_artifacts_render_with_missing_messages(self) -> None:
        """Heavy 展示 TeX，Lite 展示 Markdown，并保留缺失产物提示。"""
        root = Path(self.temporary.name)
        tex_path = root / "main.tex"
        source_path = root / "source.md"
        tex_path.write_text("\\section{Result}", encoding="utf-8")
        source_path.write_text("# Source", encoding="utf-8")
        app = LaTeXTransTuiApp(load_history_on_mount=False)
        async with app.run_test() as pilot:
            detail = app.project_detail
            detail.show_project(
                ProjectViewState(project_name="heavy", project_dir=str(root)),
                task_id="heavy-task",
                task_log_lines=[],
                input_type="local",
                arxiv_id="",
                zotero_config={},
            )
            await pilot.pause()
            tex_preview = detail.query_one("#tex-preview", Static)
            self.assertIsInstance(tex_preview.content, Syntax)
            self.assertIn("\\section{Result}", tex_preview.content.code)

            detail.set_engine("lite")
            detail.show_project(
                ProjectViewState(
                    project_name="lite",
                    engine="lite",
                    source_markdown_path=str(source_path),
                ),
                task_id="lite-task",
                task_log_lines=[],
                input_type="pdf",
                arxiv_id="",
                zotero_config={},
            )
            await pilot.pause()
            self.assertIn(
                "# Source",
                detail.query_one("#source-markdown-preview", Static).content.code,
            )
            self.assertEqual(
                str(detail.query_one("#translated-markdown-preview", Static).content),
                "没有可用的译文 Markdown 文件。",
            )
            tabs = detail.query_one("#detail-tabs", TabbedContent)
            self.assertEqual(tabs.active, "source-markdown-tab")

    async def test_show_none_clears_context_without_reading_files(self) -> None:
        """空选择清理详情和 Zotero 上下文，且不尝试读取产物文件。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False)
        async with app.run_test():
            detail = app.project_detail
            with patch("src.tui.project_detail.Path.read_text") as read_text:
                detail.show_project(
                    None,
                    task_id=None,
                    task_log_lines=["stale"],
                    input_type="",
                    arxiv_id="",
                    zotero_config={},
                )
            read_text.assert_not_called()
            self.assertIsNone(detail.project)
            self.assertIsNone(detail.zotero_panel.project)
            self.assertEqual(detail.task_log_lines, ["stale"])
            self.assertEqual(detail.query_one("#errors-table", DataTable).row_count, 0)

    async def test_log_refreshes_use_copied_snapshot_and_do_not_reload_artifacts(self) -> None:
        """日志事件只刷新日志，项目日志额外刷新术语且快照不共享列表。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False)
        async with app.run_test():
            detail = app.project_detail
            project = ProjectViewState(project_name="paper")
            lines = ["first"]
            detail.show_project(
                project,
                task_id="task",
                task_log_lines=lines,
                input_type="arxiv",
                arxiv_id="2508.18791",
                zotero_config={},
            )
            lines.append("late mutation")
            self.assertEqual(detail.task_log_lines, ["first"])
            with patch.object(detail, "_refresh_project_log") as refresh_log, patch.object(
                detail, "_refresh_terms_table"
            ) as refresh_terms, patch.object(detail, "_refresh_tex_preview") as refresh_tex, patch.object(
                detail, "_refresh_errors_table"
            ) as refresh_errors:
                detail.refresh_log(["task line"])
                refresh_log.assert_called_once_with(project)
                refresh_terms.assert_not_called()
                refresh_tex.assert_not_called()
                refresh_errors.assert_not_called()

                refresh_log.reset_mock()
                detail.refresh_log_and_terms(["project line"])
                refresh_log.assert_called_once_with(project)
                refresh_terms.assert_called_once_with(project)
                refresh_tex.assert_not_called()
                refresh_errors.assert_not_called()

    async def test_error_tab_activation_and_resize_refit_without_losing_cursor(self) -> None:
        """错误标签激活和终端缩放都重绘列宽并保留当前游标。"""
        root = Path(self.temporary.name)
        (root / "sections_map.json").write_text(
            json.dumps(
                [
                    {
                        "section": "1",
                        "content": "source " + "A" * 120,
                        "trans_content": "translation " + "B" * 120,
                    }
                ]
            ),
            encoding="utf-8",
        )
        (root / "errors_report.json").write_text(
            json.dumps(
                [
                    {
                        "part": "sec",
                        "num_or_ph": "1",
                        "issues": [{"type": "command_mismatch", "message": "bad command"}],
                    }
                ]
            ),
            encoding="utf-8",
        )
        app = LaTeXTransTuiApp(load_history_on_mount=False)
        async with app.run_test(size=(80, 40)) as pilot:
            app.switch_page("detail")
            detail = app.project_detail
            detail.show_project(
                ProjectViewState(project_name="paper", output_dir=str(root)),
                task_id="task",
                task_log_lines=[],
                input_type="local",
                arxiv_id="",
                zotero_config={},
            )
            tabs = detail.query_one("#detail-tabs", TabbedContent)
            tabs.active = "errors-tab"
            await pilot.pause()
            table = detail.query_one("#errors-table", DataTable)
            table.move_cursor(row=0, column=4, scroll=False)
            narrow = tuple(column.width for column in table.ordered_columns)

            await pilot.resize_terminal(140, 40)
            await pilot.pause()
            wide = tuple(column.width for column in table.ordered_columns)
            self.assertGreater(wide[4], narrow[4])
            self.assertEqual(table.cursor_coordinate.row, 0)

            await pilot.resize_terminal(70, 40)
            await pilot.pause()
            narrow_again = tuple(column.width for column in table.ordered_columns)
            self.assertLess(narrow_again[4], wide[4])
            self.assertEqual(table.cursor_coordinate.row, 0)

    async def test_zotero_context_resets_on_project_switch_but_not_refresh(self) -> None:
        """普通产物刷新保留 Zotero 选择，显式项目切换清空选择。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False)
        async with app.run_test():
            detail = app.project_detail
            first = ProjectViewState(project_name="first")
            detail.show_project(
                first,
                task_id="task",
                task_log_lines=[],
                input_type="arxiv",
                arxiv_id="2508.18791",
                zotero_config={"local_api_base": "http://local"},
                reset_zotero=True,
            )
            detail.zotero_panel.populate_zotero_results(
                [{"item_key": "ITEM1", "title": "Paper"}]
            )
            detail.zotero_panel.toggle_zotero_row_selection(0)

            detail.show_project(
                first,
                task_id="task",
                task_log_lines=[],
                input_type="arxiv",
                arxiv_id="2508.18791",
                zotero_config={"local_api_base": "http://changed"},
            )
            self.assertEqual(detail.zotero_panel.zotero_selected_keys, {"ITEM1"})

            detail.show_project(
                ProjectViewState(project_name="second"),
                task_id="task",
                task_log_lines=[],
                input_type="arxiv",
                arxiv_id="",
                zotero_config={},
                reset_zotero=True,
            )
            self.assertEqual(detail.zotero_panel.zotero_results, [])
            self.assertEqual(detail.zotero_panel.zotero_selected_keys, set())


if __name__ == "__main__":
    unittest.main()
