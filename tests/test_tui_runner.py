"""Tests for the TUI runtime runner bridge."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.tui.runner import run_tui_task
from src.tui.state import TaskViewState


class TuiRunnerTests(unittest.TestCase):
    """Verify that TUI tasks are routed into the shared runtime workflow."""

    def test_run_tui_task_passes_arxiv_inputs_as_paper_list(self):
        """ArXiv UI inputs should be passed to runtime as paper_list overrides."""
        config = {"target_language": "ch", "paper_list": []}
        events = []

        with patch("src.tui.runner.ensure_ui_config", return_value=Path("config/ui.toml")):
            with patch("src.tui.runner.runtime.load_runtime_config", return_value=config) as load_config:
                with patch(
                    "src.tui.runner.runtime.prepare_projects",
                    return_value=([r"D:\paper"], config, "tex-source", "outputs"),
                ) as prepare_projects:
                    with patch(
                        "src.tui.runner.runtime.run_projects",
                        return_value={"completed_projects": [], "failed_projects": []},
                    ) as run_projects:
                        result = run_tui_task(
                            config_path="config/ui.toml",
                            input_type="arxiv",
                            items=["2508.18791"],
                            overrides={"target_language": "ja"},
                            event_callback=events.append,
                        )

        self.assertEqual(load_config.call_args.kwargs["overrides"]["paper_list"], ["2508.18791"])
        prepare_projects.assert_called_once()
        self.assertIn("prepare_log_callback", prepare_projects.call_args.kwargs)
        run_projects.assert_called_once()
        self.assertEqual(result["projects"], [r"D:\paper"])

    def test_run_tui_task_routes_local_and_remote_inputs(self):
        """Local and remote UI inputs should be routed to runtime project arguments."""
        config = {"target_language": "ch", "paper_list": []}

        with patch("src.tui.runner.ensure_ui_config", return_value=Path("config/ui.toml")):
            with patch("src.tui.runner.runtime.load_runtime_config", return_value=config):
                with patch("src.tui.runner.runtime.prepare_projects", return_value=([], config, "src", "out")) as prepare_projects:
                    with patch("src.tui.runner.runtime.run_projects", return_value={"completed_projects": [], "failed_projects": []}):
                        run_tui_task("config/ui.toml", "local", [r"D:\paper"], {}, lambda event: None)
                        run_tui_task("config/ui.toml", "remote", ["https://example.test/paper.zip"], {}, lambda event: None)

        self.assertEqual(prepare_projects.call_args_list[0].kwargs["project_items"], [r"D:\paper"])
        self.assertEqual(prepare_projects.call_args_list[1].kwargs["project_url_items"], ["https://example.test/paper.zip"])

    def test_run_tui_task_ensures_missing_ui_config_before_loading(self):
        """Missing config/ui.toml should be initialized before runtime config loading."""
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_dir = root / "config"
            config_dir.mkdir()
            (config_dir / "default.toml").write_text('target_language = "ch"\n', encoding="utf-8")
            config = {"target_language": "ch", "paper_list": []}
            old_cwd = Path.cwd()

            try:
                os.chdir(root)
                with patch("src.tui.runner.runtime.load_runtime_config", return_value=config) as load_config:
                    with patch(
                        "src.tui.runner.runtime.prepare_projects",
                        return_value=([str(root / "paper")], config, "src", "out"),
                    ):
                        with patch(
                            "src.tui.runner.runtime.run_projects",
                            return_value={"completed_projects": [], "failed_projects": []},
                        ):
                            run_tui_task("config/ui.toml", "arxiv", ["2508.18791"], {}, lambda event: None)
            finally:
                os.chdir(old_cwd)

            self.assertTrue((config_dir / "ui.toml").is_file())
            self.assertEqual(load_config.call_args.kwargs["config_path"], str(config_dir / "ui.toml"))

    def test_run_tui_task_forwards_project_log_events(self):
        """TUI runner should forward runtime project_log events to the UI callback."""
        config = {"target_language": "ch", "paper_list": []}
        events = []

        def fake_run_projects(**kwargs):
            """Emit a project_log event through the provided callback."""
            kwargs["event_callback"](
                {
                    "type": "project_log",
                    "project_name": "paper",
                    "line": "[FakeAgent] [INFO] hello",
                }
            )
            return {"completed_projects": [], "failed_projects": []}

        with patch("src.tui.runner.ensure_ui_config", return_value=Path("config/ui.toml")):
            with patch("src.tui.runner.runtime.load_runtime_config", return_value=config):
                with patch(
                    "src.tui.runner.runtime.prepare_projects",
                    return_value=([r"D:\paper"], config, "src", "out"),
                ):
                    with patch("src.tui.runner.runtime.run_projects", side_effect=fake_run_projects):
                        run_tui_task("config/ui.toml", "local", [r"D:\paper"], {}, events.append)

        self.assertEqual(events[0]["type"], "project_log")
        self.assertEqual(events[0]["line"], "[FakeAgent] [INFO] hello")

    def test_run_tui_task_forwards_prepare_logs(self):
        """准备阶段日志应通过项目日志事件进入 UI，而不是写入终端。"""
        config = {"target_language": "ch", "paper_list": []}
        events = []

        def fake_prepare_projects(**kwargs):
            kwargs["prepare_log_callback"]({
                "project_name": "2508.18791",
                "line": "Downloading 2508.18791: 1.00MB / 2.00MB",
                "level": "info",
            })
            return ([r"D:\paper"], config, "src", "out")

        with patch("src.tui.runner.ensure_ui_config", return_value=Path("config/ui.toml")):
            with patch("src.tui.runner.runtime.load_runtime_config", return_value=config):
                with patch("src.tui.runner.runtime.prepare_projects", side_effect=fake_prepare_projects):
                    with patch(
                        "src.tui.runner.runtime.run_projects",
                        return_value={"completed_projects": [], "failed_projects": []},
                    ):
                        run_tui_task("config/ui.toml", "arxiv", ["2508.18791"], {}, events.append)

        self.assertEqual(events[0]["type"], "project_log")
        self.assertEqual(events[0]["project_name"], "2508.18791")

    def test_run_tui_task_does_not_create_phantom_project_for_unscoped_prepare_log(self):
        """无法归属项目的准备日志应使用任务日志事件，而非虚构项目。"""
        config = {"target_language": "ch", "paper_list": []}
        events = []

        def fake_prepare_projects(**kwargs):
            kwargs["prepare_log_callback"]({"line": "preparing"})
            return ([r"D:\paper"], config, "src", "out")

        with patch("src.tui.runner.ensure_ui_config", return_value=Path("config/ui.toml")):
            with patch("src.tui.runner.runtime.load_runtime_config", return_value=config):
                with patch("src.tui.runner.runtime.prepare_projects", side_effect=fake_prepare_projects):
                    with patch(
                        "src.tui.runner.runtime.run_projects",
                        return_value={"completed_projects": [], "failed_projects": []},
                    ):
                        run_tui_task("config/ui.toml", "local", [r"D:\paper"], {}, events.append)

        self.assertEqual(events[0]["type"], "task_log")
        self.assertNotIn("project_name", events[0])

    def test_run_tui_task_routes_unrelated_prepare_project_log_to_task_log(self):
        """历史归档的准备日志不得创建虚假的项目条目。"""
        config = {"target_language": "ch", "paper_list": []}
        events = []

        def fake_prepare_projects(**kwargs):
            kwargs["prepare_log_callback"](
                {"project_name": "old-paper", "line": "Extracted old-paper.tar.gz"}
            )
            return ([r"D:\\paper"], config, "src", "out")

        with patch("src.tui.runner.ensure_ui_config", return_value=Path("config/ui.toml")):
            with patch("src.tui.runner.runtime.load_runtime_config", return_value=config):
                with patch("src.tui.runner.runtime.prepare_projects", side_effect=fake_prepare_projects):
                    with patch(
                        "src.tui.runner.runtime.run_projects",
                        return_value={"completed_projects": [], "failed_projects": []},
                    ):
                        run_tui_task("config/ui.toml", "arxiv", ["2508.18791"], {}, events.append)

        self.assertEqual(events[0]["type"], "task_log")
        self.assertNotIn("project_name", events[0])

    def test_run_tui_task_emits_errors_for_prepare_skipped_inputs(self):
        """Prepare skips should emit visible project_error events while valid projects continue."""
        config = {"target_language": "ch", "paper_list": []}
        valid_project = r"D:\tex-source\valid"
        events = []

        with patch("src.tui.runner.ensure_ui_config", return_value=Path("config/ui.toml")):
            with patch("src.tui.runner.runtime.load_runtime_config", return_value=config):
                with patch(
                    "src.tui.runner.runtime.prepare_projects",
                    return_value=([valid_project], config, "src", "out"),
                ):
                    with patch(
                        "src.tui.runner.runtime.run_projects",
                        side_effect=lambda **kwargs: kwargs["event_callback"](
                            {"type": "project_complete", "project_name": "valid", "project_dir": valid_project}
                        )
                        or {"completed_projects": [{"project_name": "valid"}], "failed_projects": []},
                    ):
                        run_tui_task(
                            "config/ui.toml",
                            "local",
                            [r"D:\missing", valid_project],
                            {},
                            events.append,
                        )

        self.assertEqual(
            [event["type"] for event in events],
            ["run_start", "project_complete", "project_error"],
        )
        self.assertEqual(events[0]["total"], 2)
        self.assertEqual(events[2]["project_name"], r"D:\missing")
        self.assertIn("准备阶段跳过", events[2]["error"])

    def test_run_tui_task_does_not_fabricate_prepare_errors_for_execution_value_error(self):
        """An execution ValueError must not be presented as failed input preparation."""
        config = {"target_language": "ch", "paper_list": []}
        events = []

        def fail_during_execution(**kwargs):
            """Expose an execution boundary before raising an unrelated ValueError."""
            kwargs["event_callback"]({"type": "project_start", "project_name": "valid"})
            raise ValueError("translator payload is invalid")

        with patch("src.tui.runner.ensure_ui_config", return_value=Path("config/ui.toml")):
            with patch("src.tui.runner.runtime.load_runtime_config", return_value=config):
                with patch(
                    "src.tui.runner.runtime.run_engine_task",
                    side_effect=fail_during_execution,
                ):
                    with self.assertRaisesRegex(ValueError, "translator payload"):
                        run_tui_task(
                            "config/ui.toml",
                            "local",
                            [r"D:\valid"],
                            {},
                            events.append,
                        )

        self.assertFalse(any(event["type"] == "project_error" for event in events))

    def test_run_tui_task_does_not_misclassify_real_runtime_execution_value_error(self):
        """A post-preparation runtime ValueError must reach the UI without fake skips."""
        events = []
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project_dir = root / "prepared-paper"
            project_dir.mkdir()
            config = {
                "target_language": "ch",
                "paper_list": [],
                "tex_sources_dir": str(root / "tex-source"),
                "output_dir": str(root / "outputs"),
            }

            with patch(
                "src.tui.runner.ensure_ui_config",
                return_value=root / "config" / "ui.toml",
            ):
                with patch("src.tui.runner.runtime.load_runtime_config", return_value=config):
                    with patch(
                        "src.runtime.run_projects",
                        side_effect=ValueError("coordinator payload is invalid"),
                    ) as run_projects:
                        with self.assertRaisesRegex(ValueError, "coordinator payload"):
                            run_tui_task(
                                str(root / "config" / "ui.toml"),
                                "local",
                                [str(project_dir)],
                                {},
                                events.append,
                            )

        self.assertEqual(run_projects.call_args.kwargs["projects"], [str(project_dir)])
        self.assertEqual(events, [])

    def test_run_tui_task_counts_all_inputs_before_late_prepare_skip_events(self):
        """A valid completion must not finish a task before skipped inputs are accounted for."""
        config = {"target_language": "ch", "paper_list": []}
        valid_project = r"D:\tex-source\valid"
        events = []

        def complete_only_prepared_project(**kwargs):
            """Model one prepared project while another submitted input is skipped."""
            kwargs["event_callback"](
                {"type": "project_start", "project_name": "valid", "project_dir": valid_project}
            )
            kwargs["event_callback"](
                {"type": "project_complete", "project_name": "valid", "project_dir": valid_project}
            )
            return {"projects": [valid_project], "completed_projects": [], "failed_projects": []}

        with patch("src.tui.runner.ensure_ui_config", return_value=Path("config/ui.toml")):
            with patch("src.tui.runner.runtime.load_runtime_config", return_value=config):
                with patch(
                    "src.tui.runner.runtime.run_engine_task",
                    side_effect=complete_only_prepared_project,
                ):
                    run_tui_task(
                        "config/ui.toml",
                        "local",
                        [r"D:\missing", valid_project],
                        {},
                        events.append,
                    )

        self.assertEqual(
            [event["type"] for event in events],
            ["run_start", "project_start", "project_complete", "project_error"],
        )
        self.assertEqual(events[0]["total"], 2)
        state_before_skip = TaskViewState(input_type="local", inputs=[r"D:\missing", valid_project])
        for event in events[:3]:
            state_before_skip.apply_event(event)
        self.assertEqual((state_before_skip.total, state_before_skip.completed, state_before_skip.failed), (2, 1, 0))
        self.assertLess(state_before_skip.completed + state_before_skip.failed, state_before_skip.total)

        final_state = TaskViewState(input_type="local", inputs=[r"D:\missing", valid_project])
        for event in events:
            final_state.apply_event(event)
        self.assertEqual((final_state.total, final_state.completed, final_state.failed), (2, 1, 1))

    def test_run_tui_task_emits_all_prepare_errors_when_prepare_raises(self):
        """All submitted inputs should get project_error events when prepare raises."""
        config = {"target_language": "ch", "paper_list": []}
        events = []

        with patch("src.tui.runner.ensure_ui_config", return_value=Path("config/ui.toml")):
            with patch("src.tui.runner.runtime.load_runtime_config", return_value=config):
                with patch(
                    "src.tui.runner.runtime.prepare_projects",
                    side_effect=ValueError("No valid TeX projects available for processing."),
                ):
                    with patch("src.tui.runner.runtime.run_projects") as run_projects:
                        with self.assertRaisesRegex(ValueError, "No valid TeX projects"):
                            run_tui_task(
                                "config/ui.toml",
                                "local",
                                [r"D:\missing-one", r"D:\missing-two"],
                                {},
                                events.append,
                            )

        run_projects.assert_not_called()
        self.assertEqual(
            [event["type"] for event in events],
            ["run_start", "project_error", "project_error"],
        )
        self.assertEqual(events[0]["total"], 2)
        self.assertEqual(
            [event["project_name"] for event in events[1:]],
            [r"D:\missing-one", r"D:\missing-two"],
        )

    def test_run_tui_task_remote_skip_resets_total_without_url_errors(self):
        """Remote skips should reset total without marking a specific URL failed."""
        config = {"target_language": "ch", "paper_list": []}
        events = []

        with patch("src.tui.runner.ensure_ui_config", return_value=Path("config/ui.toml")):
            with patch("src.tui.runner.runtime.load_runtime_config", return_value=config):
                with patch(
                    "src.tui.runner.runtime.prepare_projects",
                    return_value=([r"D:\tex-source\renamed-paper"], config, "src", "out"),
                ):
                    with patch(
                        "src.tui.runner.runtime.run_projects",
                        side_effect=lambda **kwargs: kwargs["event_callback"](
                            {
                                "type": "project_complete",
                                "total": 1,
                                "project_name": "renamed-paper",
                                "project_dir": r"D:\tex-source\renamed-paper",
                            }
                        )
                        or {"completed_projects": [{"project_name": "renamed-paper"}], "failed_projects": []},
                    ):
                        run_tui_task(
                            "config/ui.toml",
                            "remote",
                            [
                                "https://example.test/original-name.zip",
                                "https://example.test/missing.zip",
                            ],
                            {},
                            events.append,
                        )

        self.assertEqual([event["type"] for event in events], ["run_start", "project_complete"])
        self.assertEqual(events[0]["total"], 1)
        self.assertFalse(
            any(
                event.get("type") == "project_error"
                and str(event.get("project_name", "")).startswith("https://example.test/")
                for event in events
            )
        )

    def test_run_tui_task_remote_prepare_error_resets_total_without_url_errors(self):
        """Remote prepare errors should reset total to zero without per-URL failures."""
        config = {"target_language": "ch", "paper_list": []}
        events = []

        with patch("src.tui.runner.ensure_ui_config", return_value=Path("config/ui.toml")):
            with patch("src.tui.runner.runtime.load_runtime_config", return_value=config):
                with patch(
                    "src.tui.runner.runtime.prepare_projects",
                    side_effect=ValueError("No valid TeX projects available for processing."),
                ):
                    with self.assertRaisesRegex(ValueError, "No valid TeX projects"):
                        run_tui_task(
                            "config/ui.toml",
                            "remote",
                            [
                                "https://example.test/first.zip",
                                "https://example.test/second.zip",
                            ],
                            {},
                            events.append,
                        )

        self.assertEqual(events, [{"type": "run_start", "total": 0, "engine": "heavy"}])

    def test_run_tui_task_dispatches_selected_engine_and_tags_events(self):
        """The runner should freeze the selected engine into runtime dispatch and events."""
        config = {
            "engine": "heavy",
            "heavy": {"output_dir": "outputs"},
            "lite": {"output_dir": "output-lite"},
        }
        events = []

        def fake_run_engine_task(**kwargs):
            """Emit an untagged event to verify the runner's engine boundary."""
            kwargs["event_callback"]({"type": "project_start", "project_name": "paper"})
            return {"completed_projects": [], "failed_projects": []}

        with patch("src.tui.runner.ensure_ui_config", return_value=Path("config/ui.toml")):
            with patch("src.tui.runner.runtime.load_runtime_config", return_value=config) as load_config:
                with patch(
                    "src.tui.runner.runtime.run_engine_task",
                    side_effect=fake_run_engine_task,
                ) as dispatch:
                    run_tui_task(
                        "config/ui.toml",
                        "pdf",
                        ["paper.pdf"],
                        {"retranslate_with_terms": True},
                        events.append,
                        engine="lite",
                    )

        self.assertNotIn("retranslate_with_terms", load_config.call_args.kwargs["overrides"])
        self.assertEqual(dispatch.call_args.kwargs["engine"], "lite")
        self.assertEqual(dispatch.call_args.kwargs["input_type"], "pdf")
        self.assertEqual(events[0]["engine"], "lite")


if __name__ == "__main__":
    unittest.main()
