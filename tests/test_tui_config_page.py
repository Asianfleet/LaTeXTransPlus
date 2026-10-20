"""配置页组件的状态所有权和保存生命周期测试。"""

import hashlib
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, call, patch

from textual.css.query import NoMatches
from textual.widgets import Collapsible, Input, Select, Static

from src.tui.app import LaTeXTransTuiApp
from src.tui.config import UI_CONFIG_PATH
from src.tui.config_page import ConfigPage


def _file_summary(path: Path) -> tuple[bool, str | None]:
    """返回文件是否存在及其摘要，便于确认测试未污染真实配置。"""
    if not path.exists():
        return False, None
    return True, hashlib.sha256(path.read_bytes()).hexdigest()


def _complete_config(engine: str = "heavy") -> dict[str, object]:
    """构造覆盖当前配置 schema 的完整测试配置。"""
    return {
        "sys_name": "LaTeXTransPlus",
        "version": "test",
        "engine": engine,
        "source_language": "en",
        "target_language": "ch",
        "category": {},
        "update_term": "False",
        "mode": "plain",
        "user_term": "",
        "terminology": {
            "enabled": True,
            "review_before_translate": False,
            "max_llm_candidates": 30,
        },
        "heavy": {
            "paper_list": [],
            "tex_sources_dir": "tex source",
            "output_dir": "outputs",
            "retranslate_with_terms": False,
            "validation": {
                "retry": {
                    "max_attempts": 3,
                    "generate_pdf_on_error": True,
                    "fail_on_error": True,
                },
                "issues": {
                    "command_mismatch": {"severity": "error", "retryable": True},
                    "placeholder_mismatch": {"severity": "error", "retryable": True},
                    "bracket_mismatch": {"severity": "error", "retryable": True},
                },
            },
        },
        "lite": {
            "output_dir": "output-lite",
            "mineru_api_key_env": "MINERU_TOKEN",
            "protected_token_retry_attempts": 2,
            "translate_appendix": True,
            "mainfont": "",
            "cjk_mainfont_candidates": "SimSun, FandolSong",
            "geometry": "",
        },
        "llm_config": {"profile": "profile-a"},
        "zotero": {
            "local_api_base": "http://127.0.0.1:23119/api",
            "pdf_import_api": "web",
            "web_api_key_env": "ZOTERO_API_KEY",
        },
    }


class TuiConfigPageTests(unittest.IsolatedAsyncioTestCase):
    """在隔离目录中验证配置页组件。"""

    async def asyncSetUp(self) -> None:
        """将整个 UI 生命周期放入临时目录并拦截配置访问。"""
        self.original_cwd = Path.cwd()
        self.original_config = self.original_cwd / UI_CONFIG_PATH
        self.original_config_summary = _file_summary(self.original_config)
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.addCleanup(os.chdir, self.original_cwd)
        self.addCleanup(self._assert_original_config_unchanged)
        os.chdir(self.temporary.name)
        self.save = Mock()
        targets = {
            "src.tui.app.load_ui_config": Mock(return_value={}),
            "src.tui.config_page.load_ui_config": Mock(return_value={}),
            "src.tui.config_page.save_ui_config": self.save,
            "src.tui.config.save_ui_config": self.save,
            "src.tui.config_page.list_llm_profiles": Mock(return_value=[]),
            "src.tui.config_page.list_available_font_families": Mock(return_value=[]),
        }
        self.replacements = targets
        for target, replacement in targets.items():
            patcher = patch(target, replacement)
            patcher.start()
            self.addCleanup(patcher.stop)

    def _assert_original_config_unchanged(self) -> None:
        """确认测试没有创建或修改工作树中的真实 UI 配置。"""
        self.assertEqual(
            _file_summary(self.original_config),
            self.original_config_summary,
            "TUI 测试不得创建或修改真实 UI 配置文件。",
        )

    async def test_mount_rebuild_and_delayed_edit_save_only_user_change(self) -> None:
        """组件挂载和重建不保存，用户编辑只保存一次。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.set_engine("lite")
            await app.workers.wait_for_complete()
            await pilot.pause()
            self.save.assert_not_called()
            page = app.config_page
            self.assertFalse(page.loading_config_form)
            config = {"target_language": "ja", "engine": "heavy"}
            target_language = app.query_one("#config-target_language", Select)
            self.assertEqual(target_language.value, "ch")
            with patch.object(page, "_config_from_form", return_value=config), patch.object(
                page,
                "persist_form",
                wraps=page.persist_form,
            ) as persist:
                target_language.value = "ja"
                for _ in range(10):
                    if persist.called:
                        break
                    await pilot.pause(0.05)
            persist.assert_called_once_with()
            self.assertFalse(page.loading_config_form)
            self.save.assert_called_once()
            self.assertEqual(page.get_config()["target_language"], "ja")
            self.assertEqual(app.effective_engine, "lite")

    async def test_unsupported_local_pdf_api_restores_web_selection(self) -> None:
        """本地写入不可用时提示用户且不保存切换。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False)
        async with app.run_test() as pilot:
            page = app.config_page
            page.set_config(_complete_config())
            page._populate_config_form(page.get_config())
            await pilot.pause()
            select = app.query_one("#config-zotero-pdf_import_api", Select)
            with patch("src.tui.config_page.ZoteroAdapter") as adapter:
                adapter.return_value.check_local_write_support.side_effect = RuntimeError("unsupported")
                select.value = "local"
                await pilot.pause()
            self.assertEqual(select.value, "web")
            self.assertEqual(page.get_config()["zotero"]["pdf_import_api"], "web")
            self.assertIn("unsupported", str(app.query_one("#config-error", Static).render()))
            self.save.assert_not_called()

    async def test_supported_local_pdf_api_is_saved(self) -> None:
        """支持本地写入时保存所选 PDF 导入方式。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False)
        async with app.run_test() as pilot:
            page = app.config_page
            page.set_config(_complete_config())
            page._populate_config_form(page.get_config())
            await pilot.pause()
            with patch("src.tui.config_page.ZoteroAdapter") as adapter:
                app.query_one("#config-zotero-pdf_import_api", Select).value = "local"
                await pilot.pause()
            adapter.return_value.check_local_write_support.assert_called_once_with()
            self.assertEqual(page.get_config()["zotero"]["pdf_import_api"], "local")
            self.assertEqual(self.save.call_args.args[1]["zotero"]["pdf_import_api"], "local")

    async def test_config_snapshot_and_message_are_deep_copies(self) -> None:
        """外部配置与变化消息都不能共享组件内部的可变字典。"""
        source = {"nested": {"value": "original"}}
        page = ConfigPage("heavy")
        page.set_config(source)
        source["nested"]["value"] = "source-mutated"
        first = page.get_config()
        first["nested"]["value"] = "returned-mutated"
        message = ConfigPage.ConfigChanged(page.get_config())
        message.config["nested"]["value"] = "message-mutated"

        self.assertEqual(page.get_config(), {"nested": {"value": "original"}})

    async def test_empty_snapshot_loads_once_without_saving_or_form_events(self) -> None:
        """空快照按需加载并缓存，且不保存或触发表单生命周期。"""
        loaded = {"nested": {"value": "loaded"}}
        loader = self.replacements["src.tui.config_page.load_ui_config"]
        loader.return_value = loaded
        page = ConfigPage("heavy")

        first = page.get_config()
        loaded["nested"]["value"] = "mutated-after-load"
        second = page.get_config()

        self.assertEqual(first, {"nested": {"value": "loaded"}})
        self.assertEqual(second, first)
        loader.assert_called_once_with(Path.cwd())
        self.save.assert_not_called()

    async def test_explicit_empty_snapshot_restores_lazy_fallback(self) -> None:
        """显式清空快照后，下次读取重新加载并只缓存一次。"""
        loader = self.replacements["src.tui.config_page.load_ui_config"]
        loader.return_value = {"engine": "lite"}
        page = ConfigPage("heavy")
        page.set_config({"engine": "heavy"})
        page.set_config({})

        self.assertEqual(page.get_config(), {"engine": "lite"})
        self.assertEqual(page.get_config(), {"engine": "lite"})
        loader.assert_called_once_with(Path.cwd())
        self.save.assert_not_called()

    async def test_saved_default_engine_does_not_switch_active_session(self) -> None:
        """设置未来默认引擎只保存配置，不切换当前会话。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False, initial_engine="heavy")
        async with app.run_test() as pilot:
            app.config_page.set_config(_complete_config("heavy"))
            app.config_page.save_default_engine("lite")
            await pilot.pause()

            self.assertEqual(app.effective_engine, "heavy")
            self.assertEqual(app.current_config["engine"], "lite")
            self.assertEqual(self.save.call_args.args[1]["engine"], "lite")

    async def test_engine_changed_before_mount_composes_matching_fields(self) -> None:
        """挂载前切换会话引擎时，配置页应按新引擎组合字段。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False, initial_engine="heavy")
        app.set_engine("lite")

        async with app.run_test():
            self.assertIsNotNone(app.query_one("#config-lite-output_dir", Input))
            with self.assertRaises(NoMatches):
                app.query_one("#config-heavy-output_dir", Input)

    async def test_back_to_back_rebuild_ignores_stale_refresh_callback(self) -> None:
        """连续重建时旧 refresh 回调不能提前放行表单保存。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False)
        async with app.run_test() as pilot:
            await pilot.pause()
            page = app.config_page
            callbacks: list[tuple[object, tuple[object, ...]]] = []

            def capture(callback, *args, **_kwargs):
                """记录 refresh 回调，按测试控制的顺序执行。"""
                callbacks.append((callback, args))
                return True

            with patch.object(page, "call_after_refresh", side_effect=capture):
                app.set_engine("lite")
                await app.workers.wait_for_complete()
                app.set_engine("heavy")
                await app.workers.wait_for_complete()

            self.assertGreaterEqual(len(callbacks), 2)
            stale_callback, stale_args = callbacks[-2]
            stale_callback(*stale_args)
            with patch.object(page, "_config_from_form", return_value={"engine": "heavy"}):
                page.persist_form()

            self.save.assert_not_called()
            latest_callback, latest_args = callbacks[-1]
            latest_callback(*latest_args)
            self.assertFalse(page.loading_config_form)

    async def test_load_during_rebuild_keeps_guard_and_does_not_save(self) -> None:
        """重建仍活动时完成加载也不能提前解除保存保护。"""
        config = _complete_config("lite")
        self.replacements["src.tui.config_page.load_ui_config"].return_value = config
        app = LaTeXTransTuiApp(load_history_on_mount=False)
        async with app.run_test() as pilot:
            await pilot.pause()
            page = app.config_page
            original_populate = page._populate_config_form
            guard_states: list[bool] = []
            nested = False

            def populate_with_nested_load(values):
                """在重建填充阶段插入一次同步加载以制造生命周期交叠。"""
                nonlocal nested
                if not nested:
                    nested = True
                    page.load_config()
                    guard_states.append(page.loading_config_form)
                original_populate(values)

            with patch.object(page, "_populate_config_form", side_effect=populate_with_nested_load), patch.object(
                page,
                "call_after_refresh",
                side_effect=lambda callback, *args, **_kwargs: callback(*args) or True,
            ):
                app.set_engine("lite")
                await app.workers.wait_for_complete()

            self.assertEqual(guard_states, [True])
            self.save.assert_not_called()

    async def test_complete_then_abort_waits_for_refresh_before_persisting(self) -> None:
        """交叠更新先完成后取消时，仍需排空 Changed 才能保存。"""
        page = ConfigPage("heavy")
        page.set_config({"engine": "heavy"})
        callbacks: list[tuple[object, tuple[object, ...]]] = []

        def capture(callback, *args, **_kwargs):
            """记录最终解除保护的 refresh 回调。"""
            callbacks.append((callback, args))
            return True

        with patch.object(page, "call_after_refresh", side_effect=capture):
            page._begin_config_lifecycle()
            page._begin_config_lifecycle()
            page._complete_config_lifecycle()
            page._abort_config_lifecycle()

        self.assertTrue(page.loading_config_form)
        with patch.object(page, "_config_from_form", return_value={"engine": "heavy"}):
            page.persist_form()
        self.save.assert_not_called()

        self.assertEqual(len(callbacks), 1)
        callback, args = callbacks[0]
        callback(*args)
        self.assertFalse(page.loading_config_form)

    async def test_invalid_integer_does_not_save(self) -> None:
        """非法整数显示校验错误并阻止保存。"""
        app = LaTeXTransTuiApp(load_history_on_mount=False)
        async with app.run_test() as pilot:
            app.current_config = _complete_config()
            app.load_config_page()
            await pilot.pause()
            self.save.reset_mock()

            app.query_one("#config-terminology-max_llm_candidates", Input).value = "-1"
            await pilot.pause()

            self.save.assert_not_called()
            self.assertIn("非负整数", str(app.query_one("#config-error", Static).content))

    async def test_reasoning_effort_loads_saves_and_survives_engine_rebuild(self) -> None:
        """强度选择应自动保存、跨引擎保留，并可恢复为未设置。"""
        config = _complete_config()
        config["llm_config"]["reasoning_effort"] = "xhigh"
        self.replacements["src.tui.config_page.load_ui_config"].return_value = config
        app = LaTeXTransTuiApp(load_history_on_mount=False)
        async with app.run_test() as pilot:
            app.load_config_page()
            await pilot.pause()
            select = app.query_one("#config-llm_config-reasoning_effort", Select)
            self.assertEqual(select.value, "xhigh")
            self.save.assert_not_called()

            for effort in ("low", "medium", "high", "xhigh", "max", "ultra"):
                select.value = effort
                await pilot.pause()
                self.assertEqual(
                    self.save.call_args.args[1]["llm_config"],
                    {"profile": "profile-a", "reasoning_effort": effort},
                )

            app.set_engine("lite")
            await app.workers.wait_for_complete()
            await pilot.pause()
            select = app.query_one("#config-llm_config-reasoning_effort", Select)
            self.assertEqual(select.value, "ultra")
            select.value = ""
            await pilot.pause()
            self.assertEqual(
                self.save.call_args.args[1]["llm_config"]["reasoning_effort"], "",
            )

    async def test_reasoning_effort_defaults_to_unset_for_existing_config(self) -> None:
        """旧配置加载新字段时保持未设置，且不触发额外保存。"""
        self.replacements["src.tui.config_page.load_ui_config"].return_value = _complete_config()
        app = LaTeXTransTuiApp(load_history_on_mount=False)
        async with app.run_test() as pilot:
            app.load_config_page()
            await pilot.pause()
            self.assertEqual(
                app.query_one("#config-llm_config-reasoning_effort", Select).value, "",
            )
            self.save.assert_not_called()

    async def test_profiles_are_populated_in_both_engines_and_fonts_only_in_lite(self) -> None:
        """两种引擎都刷新 profile，只有 Lite 构建字体字段和提示。"""
        profiles = self.replacements["src.tui.config_page.list_llm_profiles"]
        profiles.return_value = [("profile-a", "profile-a"), ("profile-b", "profile-b")]
        fonts = self.replacements["src.tui.config_page.list_available_font_families"]
        fonts.return_value = ["SimSun", "FandolSong"]

        for engine in ("heavy", "lite"):
            self.replacements["src.tui.config_page.load_ui_config"].return_value = (
                _complete_config(engine)
            )
            app = LaTeXTransTuiApp(load_history_on_mount=False, initial_engine=engine)
            async with app.run_test() as pilot:
                app.load_config_page()
                await pilot.pause()
                self.assertEqual(
                    app.query_one("#config-llm_config-profile", Select).value,
                    "profile-a",
                )
                if engine == "lite":
                    panel = app.query_one("#config-lite-mainfont-hint", Collapsible)
                    self.assertEqual(panel.title, "可用字体 (2)")
                else:
                    with self.assertRaises(NoMatches):
                        app.query_one("#config-lite-mainfont", Input)

        self.assertEqual(profiles.call_count, 2)
        self.assertIn(call("zh"), fonts.call_args_list)
        self.assertIn(call(None), fonts.call_args_list)

    async def test_engine_rebuild_hides_other_fields_and_preserves_unknown_metadata(self) -> None:
        """切换会话引擎只换可见字段，保存仍保留隐藏段和未知元数据。"""
        config = _complete_config("heavy")
        config["custom_metadata"] = {"keep": ["value"]}
        self.replacements["src.tui.config_page.load_ui_config"].return_value = config
        app = LaTeXTransTuiApp(load_history_on_mount=False, initial_engine="heavy")
        async with app.run_test() as pilot:
            app.load_config_page()
            app.set_engine("lite")
            await app.workers.wait_for_complete()
            await pilot.pause()
            self.save.reset_mock()

            with self.assertRaises(NoMatches):
                app.query_one("#config-heavy-output_dir", Input)
            app.query_one("#config-lite-output_dir", Input).value = "translated-lite"
            await pilot.pause()

            saved = self.save.call_args.args[1]
            self.assertEqual(saved["custom_metadata"], {"keep": ["value"]})
            self.assertEqual(saved["heavy"]["output_dir"], "outputs")
            self.assertEqual(saved["lite"]["output_dir"], "translated-lite")


if __name__ == "__main__":
    unittest.main()
