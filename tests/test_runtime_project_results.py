import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import tempfile
from unittest.mock import patch

from src.runtime import (
    classify_project_result,
    load_runtime_config,
    run_projects,
    should_exit_with_failure,
)
from src.agents.tool_agents.base_tool_agent import BaseToolAgent


class RuntimeProjectResultTests(unittest.TestCase):
    def test_load_runtime_config_applies_retranslate_with_terms_override(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "config.toml"
            config_path.write_text(
                """
paper_list = []
retranslate_with_terms = false

[llm_config]
profile = "test"
""".strip(),
                encoding="utf-8",
            )
            (Path(tmp_dir) / "provider").mkdir()
            (Path(tmp_dir) / "provider" / "test.toml").write_text(
                """
model = "test-model"
api_key_env = ""
base_url = "https://example.test/v1/chat/completions"
custom_json = ""
""".strip(),
                encoding="utf-8",
            )

            config = load_runtime_config(
                str(config_path),
                overrides={"retranslate_with_terms": True},
            )

        self.assertTrue(config["retranslate_with_terms"])

    def test_cli_uses_runtime_prepare_and_run_projects(self):
        import main

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            config_path = tmp_path / "config.toml"
            source_dir = tmp_path / "tex-source"
            output_dir = tmp_path / "outputs"
            project_dir = tmp_path / "paper"
            project_dir.mkdir()
            config_path.write_text(
                f"""
paper_list = []
tex_sources_dir = {str(source_dir)!r}
output_dir = {str(output_dir)!r}
target_language = "ch"

[llm_config]
profile = "test"
""".strip(),
                encoding="utf-8",
            )
            runtime_config = {"target_language": "ch", "paper_list": []}

            with patch.object(
                main.sys,
                "argv",
                ["latextrans", "--config", str(config_path), "--project", str(project_dir)],
            ):
                with patch("src.runtime.load_runtime_config", return_value=runtime_config):
                    with patch(
                        "src.runtime.prepare_projects",
                        return_value=([str(project_dir)], runtime_config, str(source_dir), str(output_dir)),
                    ) as prepare_projects:
                        with patch(
                            "src.runtime.run_projects",
                            return_value={"completed_projects": [{"project_name": "paper"}], "failed_projects": []},
                        ) as run_projects_mock:
                            with redirect_stdout(StringIO()):
                                main.main()

        prepare_projects.assert_called_once_with(
            config=runtime_config,
            project_items=[str(project_dir)],
            project_url_items=[],
            all_existing=False,
        )
        run_projects_mock.assert_called_once()
        self.assertEqual(run_projects_mock.call_args.kwargs["config"], runtime_config)
        self.assertEqual(run_projects_mock.call_args.kwargs["projects"], [str(project_dir)])
        self.assertEqual(run_projects_mock.call_args.kwargs["output_dir"], str(output_dir))

    def test_cli_does_not_disable_config_retranslate_when_flag_absent(self):
        import main

        runtime_config = {"target_language": "ch", "paper_list": []}

        with patch.object(main.sys, "argv", ["latextrans", "--config", "config/test.toml"]):
            with patch("src.runtime.load_runtime_config", return_value=runtime_config) as load_config:
                with patch(
                    "src.runtime.prepare_projects",
                    return_value=(["paper"], runtime_config, "tex-source", "outputs"),
                ):
                    with patch(
                        "src.runtime.run_projects",
                        return_value={"completed_projects": [{"project_name": "paper"}], "failed_projects": []},
                    ):
                        with redirect_stdout(StringIO()):
                            main.main()

        overrides = load_config.call_args.kwargs["overrides"]
        self.assertNotEqual(overrides.get("retranslate_with_terms"), False)

    def test_cli_passes_project_url_items_to_prepare_projects(self):
        import main

        runtime_config = {"target_language": "ch", "paper_list": []}
        argv = [
            "latextrans",
            "--config",
            "config/test.toml",
            "--project-url",
            "https://example.test/paper.tar.gz,https://example.test/paper2.zip",
        ]

        with patch.object(main.sys, "argv", argv):
            with patch("src.runtime.load_runtime_config", return_value=runtime_config):
                with patch(
                    "src.runtime.prepare_projects",
                    return_value=(["paper"], runtime_config, "tex-source", "outputs"),
                ) as prepare_projects:
                    with patch(
                        "src.runtime.run_projects",
                        return_value={
                            "completed_projects": [{"project_name": "paper"}],
                            "failed_projects": [],
                        },
                    ):
                        with redirect_stdout(StringIO()):
                            main.main()

        prepare_projects.assert_called_once_with(
            config=runtime_config,
            project_items=[],
            project_url_items=[
                "https://example.test/paper.tar.gz",
                "https://example.test/paper2.zip",
            ],
            all_existing=False,
        )

    def test_cli_json_events_stdout_contains_only_json_lines(self):
        import json
        import main

        runtime_config = {
            "target_language": "ch",
            "source_language": "en",
            "paper_list": [],
        }
        events_seen = []

        def fake_run_projects(**kwargs):
            kwargs["event_callback"](
                {
                    "type": "project_start",
                    "index": 1,
                    "total": 1,
                    "project_name": "paper",
                    "project_dir": r"D:\paper",
                    "output_dir": r"D:\outputs\ch_paper",
                    "log_path": r"D:\outputs\ch_paper\latextrans.log",
                }
            )
            kwargs["event_callback"](
                {
                    "type": "project_complete",
                    "index": 1,
                    "total": 1,
                    "project_name": "paper",
                    "project_dir": r"D:\paper",
                    "output_dir": r"D:\outputs\ch_paper",
                    "pdf_path": r"D:\outputs\ch_paper\ch_paper.pdf",
                    "errors_report_path": r"D:\outputs\ch_paper\errors_report.json",
                    "validation_summary": {"warnings": 0, "errors": 0, "total": 0},
                    "error": None,
                    "log_path": r"D:\outputs\ch_paper\latextrans.log",
                }
            )
            events_seen.append(kwargs["event_callback"])
            return {"completed_projects": [{"project_name": "paper"}], "failed_projects": []}

        argv = [
            "latextrans",
            "--config",
            "config/test.toml",
            "--project",
            r"D:\paper",
            "--json-events",
            "stdout",
        ]

        with patch.object(main.sys, "argv", argv):
            with patch("src.runtime.load_runtime_config", return_value=runtime_config):
                with patch("src.runtime.prepare_projects", return_value=([r"D:\paper"], runtime_config, "tex-source", r"D:\outputs")):
                    with patch("src.runtime.run_projects", side_effect=fake_run_projects):
                        with redirect_stdout(StringIO()) as stdout:
                            main.main()

        lines = stdout.getvalue().splitlines()
        self.assertEqual([json.loads(line)["type"] for line in lines], [
            "run_start",
            "project_start",
            "project_complete",
            "run_complete",
        ])
        for line in lines:
            payload = json.loads(line)
            self.assertEqual(payload["schema_version"], 1)
            self.assertIn("timestamp", payload)
        self.assertNotIn("Console log will be saved to", stdout.getvalue())

    def test_cli_json_events_file_writes_events(self):
        import json
        import main

        runtime_config = {"target_language": "ch", "source_language": "en", "paper_list": []}

        def fake_run_projects(**kwargs):
            kwargs["event_callback"](
                {
                    "type": "project_error",
                    "index": 1,
                    "total": 1,
                    "project_name": "paper",
                    "project_dir": r"D:\paper",
                    "output_dir": r"D:\outputs\ch_paper",
                    "pdf_path": None,
                    "errors_report_path": None,
                    "validation_summary": None,
                    "error": "boom",
                    "log_path": r"D:\outputs\ch_paper\latextrans.log",
                }
            )
            return {"completed_projects": [], "failed_projects": [{"project_name": "paper"}]}

        with tempfile.TemporaryDirectory() as tmp_dir:
            events_path = Path(tmp_dir) / "events.jsonl"
            argv = [
                "latextrans",
                "--config",
                "config/test.toml",
                "--project",
                r"D:\paper",
                "--json-events-file",
                str(events_path),
            ]

            with patch.object(main.sys, "argv", argv):
                with patch("src.runtime.load_runtime_config", return_value=runtime_config):
                    with patch("src.runtime.prepare_projects", return_value=([r"D:\paper"], runtime_config, "tex-source", r"D:\outputs")):
                        with patch("src.runtime.run_projects", side_effect=fake_run_projects):
                            with self.assertRaises(SystemExit):
                                with redirect_stdout(StringIO()):
                                    main.main()

            events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines()]

        self.assertEqual([event["type"] for event in events], ["run_start", "project_error", "run_complete"])
        self.assertFalse(events[-1]["ok"])
        self.assertEqual(events[-1]["failed"], 1)

    def test_cli_json_events_stdout_redirects_prepare_logs_away_from_stdout(self):
        import json
        import main

        runtime_config = {"target_language": "ch", "source_language": "en", "paper_list": []}

        def fake_prepare_projects(**kwargs):
            print("prepare noisy log")
            return [r"D:\paper"], runtime_config, "tex-source", r"D:\outputs"

        argv = [
            "latextrans",
            "--config",
            "config/test.toml",
            "--project",
            r"D:\paper",
            "--json-events",
            "stdout",
        ]

        with patch.object(main.sys, "argv", argv):
            with patch("src.runtime.load_runtime_config", return_value=runtime_config):
                with patch("src.runtime.prepare_projects", side_effect=fake_prepare_projects):
                    with patch(
                        "src.runtime.run_projects",
                        return_value={"completed_projects": [{"project_name": "paper"}], "failed_projects": []},
                    ):
                        with redirect_stdout(StringIO()) as stdout:
                            main.main()

        lines = stdout.getvalue().splitlines()
        event_types = [json.loads(line)["type"] for line in lines]
        self.assertEqual(event_types, ["run_start", "run_complete"])
        self.assertNotIn("prepare noisy log", stdout.getvalue())

    def test_cli_json_events_stdout_writes_run_complete_when_run_projects_raises(self):
        import json
        import main

        runtime_config = {"target_language": "ch", "source_language": "en", "paper_list": []}
        argv = [
            "latextrans",
            "--config",
            "config/test.toml",
            "--project",
            r"D:\paper",
            "--json-events",
            "stdout",
        ]

        with patch.object(main.sys, "argv", argv):
            with patch("src.runtime.load_runtime_config", return_value=runtime_config):
                with patch(
                    "src.runtime.prepare_projects",
                    return_value=([r"D:\paper"], runtime_config, "tex-source", r"D:\outputs"),
                ):
                    with patch("src.runtime.run_projects", side_effect=RuntimeError("boom")):
                        with self.assertRaises(RuntimeError):
                            with redirect_stdout(StringIO()) as stdout:
                                main.main()

        events = [json.loads(line) for line in stdout.getvalue().splitlines()]
        self.assertEqual([event["type"] for event in events], ["run_start", "run_complete"])
        self.assertFalse(events[-1]["ok"])
        self.assertEqual(events[-1]["failed"], 1)
        self.assertEqual(events[-1]["error"], "boom")

    def test_prepare_projects_downloads_remote_archives(self):
        from src.runtime import prepare_projects

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            source_dir = tmp_path / "tex-source"
            output_dir = tmp_path / "outputs"
            config = {
                "paper_list": [],
                "tex_sources_dir": str(source_dir),
                "output_dir": str(output_dir),
            }
            downloaded_archive = source_dir / "paper.tar.gz"
            extracted_project = source_dir / "paper"

            with patch("src.runtime.download_remote_archive", return_value=str(downloaded_archive)) as download_mock:
                with patch("src.runtime.extract_local_archive", return_value=str(extracted_project)) as extract_mock:
                    projects, returned_config, projects_dir, returned_output_dir = prepare_projects(
                        config=config,
                        project_items=[],
                        project_url_items=["https://example.test/paper.tar.gz"],
                        all_existing=False,
                    )

        download_mock.assert_called_once_with("https://example.test/paper.tar.gz", str(source_dir))
        extract_mock.assert_called_once_with(str(downloaded_archive), str(source_dir))
        self.assertEqual(projects, [str(extracted_project.resolve())])
        self.assertEqual(returned_config, config)
        self.assertEqual(projects_dir, str(source_dir.resolve()))
        self.assertEqual(returned_output_dir, str(output_dir.resolve()))

    def test_prepare_projects_combines_local_and_remote_inputs(self):
        from src.runtime import prepare_projects

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            local_project = tmp_path / "local-paper"
            local_project.mkdir()
            source_dir = tmp_path / "tex-source"
            output_dir = tmp_path / "outputs"
            extracted_project = source_dir / "remote-paper"
            config = {
                "paper_list": [],
                "tex_sources_dir": str(source_dir),
                "output_dir": str(output_dir),
            }

            with patch("src.runtime.download_remote_archive", return_value=str(source_dir / "remote-paper.zip")):
                with patch("src.runtime.extract_local_archive", return_value=str(extracted_project)):
                    projects, _, _, _ = prepare_projects(
                        config=config,
                        project_items=[str(local_project)],
                        project_url_items=["https://example.test/remote-paper.zip"],
                        all_existing=False,
                    )

        self.assertEqual(
            projects,
            [
                str(local_project.resolve()),
                str(extracted_project.resolve()),
            ],
        )

    def test_prepare_projects_removes_downloaded_remote_archive_after_extract(self):
        from src.runtime import prepare_projects

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            source_dir = tmp_path / "tex-source"
            output_dir = tmp_path / "outputs"
            config = {
                "paper_list": [],
                "tex_sources_dir": str(source_dir),
                "output_dir": str(output_dir),
            }
            source_dir.mkdir()
            downloaded_archive = source_dir / "paper.tar.gz"
            downloaded_archive.write_bytes(b"archive-bytes")
            extracted_project = source_dir / "paper"

            with patch("src.runtime.download_remote_archive", return_value=str(downloaded_archive)):
                with patch("src.runtime.extract_local_archive", return_value=str(extracted_project)):
                    prepare_projects(
                        config=config,
                        project_items=[],
                        project_url_items=["https://example.test/paper.tar.gz"],
                        all_existing=False,
                    )

            self.assertFalse(downloaded_archive.exists())

    def test_prepare_projects_removes_downloaded_remote_archive_after_extract_failure(self):
        from src.runtime import prepare_projects

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            source_dir = tmp_path / "tex-source"
            output_dir = tmp_path / "outputs"
            config = {
                "paper_list": [],
                "tex_sources_dir": str(source_dir),
                "output_dir": str(output_dir),
            }
            source_dir.mkdir()
            downloaded_archive = source_dir / "paper.tar.gz"
            downloaded_archive.write_bytes(b"archive-bytes")

            with patch("src.runtime.download_remote_archive", return_value=str(downloaded_archive)):
                with patch("src.runtime.extract_local_archive", side_effect=ValueError("broken archive")):
                    with self.assertRaisesRegex(ValueError, "No valid TeX projects available for processing."):
                        with redirect_stdout(StringIO()) as stdout:
                            prepare_projects(
                                config=config,
                                project_items=[],
                                project_url_items=["https://example.test/paper.tar.gz"],
                                all_existing=False,
                            )

            self.assertFalse(downloaded_archive.exists())
            self.assertIn(
                "[SKIP] Failed to extract remote archive https://example.test/paper.tar.gz: broken archive",
                stdout.getvalue(),
            )

    def test_prepare_projects_skips_failed_remote_archives(self):
        from src.runtime import prepare_projects
        from src.project_sources import RemoteArchiveDownloadError

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            config = {
                "paper_list": [],
                "tex_sources_dir": str(tmp_path / "tex-source"),
                "output_dir": str(tmp_path / "outputs"),
            }

            with patch(
                "src.runtime.download_remote_archive",
                side_effect=RemoteArchiveDownloadError("Response is not a supported archive."),
            ):
                with self.assertRaisesRegex(ValueError, "No valid TeX projects available for processing."):
                    with redirect_stdout(StringIO()) as stdout:
                        prepare_projects(
                            config=config,
                            project_items=[],
                            project_url_items=["https://example.test/download"],
                            all_existing=False,
                        )

        self.assertIn("[SKIP] Failed to download remote archive https://example.test/download", stdout.getvalue())

    def test_prepare_projects_continues_after_one_remote_archive_fails(self):
        from src.runtime import prepare_projects
        from src.project_sources import RemoteArchiveDownloadError

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            source_dir = tmp_path / "tex-source"
            output_dir = tmp_path / "outputs"
            extracted_project = source_dir / "paper"
            config = {
                "paper_list": [],
                "tex_sources_dir": str(source_dir),
                "output_dir": str(output_dir),
            }

            with patch(
                "src.runtime.download_remote_archive",
                side_effect=[
                    RemoteArchiveDownloadError("Response is not a supported archive."),
                    str(source_dir / "paper.zip"),
                ],
            ) as download_mock:
                with patch("src.runtime.extract_local_archive", return_value=str(extracted_project)) as extract_mock:
                    with redirect_stdout(StringIO()) as stdout:
                        projects, _, _, _ = prepare_projects(
                            config=config,
                            project_items=[],
                            project_url_items=[
                                "https://example.test/bad",
                                "https://example.test/paper.zip",
                            ],
                            all_existing=False,
                        )

        self.assertEqual(projects, [str(extracted_project.resolve())])
        self.assertEqual(download_mock.call_count, 2)
        extract_mock.assert_called_once_with(str(source_dir / "paper.zip"), str(source_dir))
        self.assertIn("[SKIP] Failed to download remote archive https://example.test/bad", stdout.getvalue())

    def test_run_translation_passes_project_url_items_to_prepare_projects(self):
        from src.runtime import run_translation

        runtime_config = {"target_language": "ch", "paper_list": []}
        prepared_projects = [r"D:\paper"]

        with patch("src.runtime.load_runtime_config", return_value=runtime_config):
            with patch(
                "src.runtime.prepare_projects",
                return_value=(prepared_projects, runtime_config, "tex-source", "outputs"),
            ) as prepare_projects:
                with patch(
                    "src.runtime.run_projects",
                    return_value={"completed_projects": [], "failed_projects": []},
                ):
                    run_translation(project_url_items=["https://example.test/paper.tar.gz"])

        prepare_projects.assert_called_once_with(
            config=runtime_config,
            project_items=None,
            project_url_items=["https://example.test/paper.tar.gz"],
            all_existing=False,
        )

    def test_cli_passes_runtime_config_overrides(self):
        import main

        runtime_config = {"target_language": "ch", "paper_list": []}
        argv = [
            "latextrans",
            "--config",
            "config/test.toml",
            "--url",
            "https://example.test/v1",
            "--model",
            "test-model",
            "--key",
            "test-key",
            "--source",
            "tex-source",
            "--output",
            "outputs",
            "--arxiv",
            "2501.00001,2501.00002",
            "--retranslate-with-terms",
        ]

        with patch.object(main.sys, "argv", argv):
            with patch("src.runtime.load_runtime_config", return_value=runtime_config) as load_config:
                with patch(
                    "src.runtime.prepare_projects",
                    return_value=(["paper"], runtime_config, "tex-source", "outputs"),
                ):
                    with patch(
                        "src.runtime.run_projects",
                        return_value={"completed_projects": [{"project_name": "paper"}], "failed_projects": []},
                    ):
                        with redirect_stdout(StringIO()):
                            main.main()

        load_config.assert_called_once()
        self.assertEqual(load_config.call_args.kwargs["config_path"], "config/test.toml")
        self.assertEqual(
            load_config.call_args.kwargs["overrides"],
            {
                "url": "https://example.test/v1",
                "model": "test-model",
                "key": "test-key",
                "source": "tex-source",
                "output": "outputs",
                "source_language": "",
                "target_language": "",
                "retranslate_with_terms": True,
                "paper_list": ["2501.00001", "2501.00002"],
            },
        )

    def test_classify_project_result_completed(self):
        result = classify_project_result(
            index=1,
            total=2,
            project_name="paper",
            project_dir=r"D:\paper",
            workflow_result={
                "ok": True,
                "pdf_path": r"outputs\ch_paper\ch_paper.pdf",
                "validation_summary": {"warnings": 0, "errors": 0, "total": 0},
            },
        )

        self.assertEqual(result["type"], "completed")
        self.assertTrue(result["ok"])

    def test_classify_project_result_failed(self):
        result = classify_project_result(
            index=1,
            total=2,
            project_name="paper",
            project_dir=r"D:\paper",
            workflow_result={
                "ok": False,
                "pdf_path": r"outputs\ch_paper\ch_paper.pdf",
                "validation_summary": {"warnings": 0, "errors": 1, "total": 1},
            },
        )

        self.assertEqual(result["type"], "failed")
        self.assertFalse(result["ok"])
        self.assertEqual(result["validation_summary"]["errors"], 1)

    def test_classify_project_result_preserves_term_review_status(self):
        result = classify_project_result(
            index=1,
            total=2,
            project_name="paper",
            project_dir=r"D:\paper",
            workflow_result={
                "ok": False,
                "status": "needs_term_review",
                "project_terms_path": r"outputs\ch_paper\project_terms.csv",
                "project_terms_decisions_path": r"outputs\ch_paper\project_terms_decisions.json",
                "error": "review terms",
            },
        )

        self.assertEqual(result["type"], "failed")
        self.assertEqual(result["status"], "needs_term_review")
        self.assertEqual(result["project_terms_path"], r"outputs\ch_paper\project_terms.csv")
        self.assertEqual(
            result["project_terms_decisions_path"],
            r"outputs\ch_paper\project_terms_decisions.json",
        )

    def test_should_exit_with_failure_when_any_project_failed(self):
        self.assertTrue(should_exit_with_failure({
            "completed_projects": [{"project_name": "a"}],
            "failed_projects": [{"project_name": "b"}],
        }))
        self.assertFalse(should_exit_with_failure({
            "completed_projects": [{"project_name": "a"}],
            "failed_projects": [],
        }))

    def test_run_projects_continues_after_workflow_failure_result(self):
        workflow_results = [
            {
                "ok": False,
                "pdf_path": None,
                "validation_summary": {"warnings": 0, "errors": 1, "total": 1},
                "error": None,
            },
            {
                "ok": True,
                "pdf_path": r"outputs\ch_second\ch_second.pdf",
                "validation_summary": {"warnings": 0, "errors": 0, "total": 0},
                "error": None,
            },
        ]
        processed_projects = []

        class FakeCoordinatorAgent:
            def __init__(self, config, project_dir, output_dir):
                processed_projects.append(project_dir)

            def workflow_latextrans(self):
                return workflow_results.pop(0)

        with patch("src.runtime.CoordinatorAgent", FakeCoordinatorAgent):
            with redirect_stdout(StringIO()):
                status = run_projects(
                    config={},
                    projects=[r"D:\first", r"D:\second"],
                    output_dir="outputs",
                )

        self.assertEqual(processed_projects, [r"D:\first", r"D:\second"])
        self.assertEqual(len(status["failed_projects"]), 1)
        self.assertEqual(len(status["completed_projects"]), 1)
        self.assertEqual(status["failed_projects"][0]["project_name"], "first")
        self.assertEqual(status["completed_projects"][0]["project_name"], "second")

    def test_run_projects_failure_status_includes_output_and_log_paths(self):
        class FakeCoordinatorAgent:
            def __init__(self, config, project_dir, output_dir):
                pass

            def workflow_latextrans(self):
                return {
                    "ok": False,
                    "pdf_path": None,
                    "errors_report_path": None,
                    "validation_summary": {"warnings": 1, "errors": 1, "total": 2},
                    "error": "validation failed",
                }

        with patch("src.runtime.CoordinatorAgent", FakeCoordinatorAgent):
            with redirect_stdout(StringIO()):
                status = run_projects(
                    config={"target_language": "ch"},
                    projects=[r"D:\tex source\paper"],
                    output_dir=r"D:\repo\outputs",
                )

        failure = status["failed_projects"][0]
        self.assertEqual(failure["type"], "failed")
        self.assertFalse(failure["ok"])
        self.assertEqual(failure["output_dir"], r"D:\repo\outputs\ch_paper")
        self.assertEqual(failure["log_path"], r"D:\repo\outputs\ch_paper\latextrans.log")
        self.assertIsNone(failure["pdf_path"])
        self.assertIsNone(failure["errors_report_path"])
        self.assertEqual(failure["validation_summary"], {"warnings": 1, "errors": 1, "total": 2})
        self.assertEqual(failure["error"], "validation failed")

    def test_run_projects_uses_retranslation_workflow_when_requested(self):
        calls = []

        class FakeCoordinatorAgent:
            def __init__(self, config, project_dir, output_dir):
                self.project_dir = project_dir

            def workflow_latextrans_with_existing_terms(self):
                calls.append(("retranslate", self.project_dir))
                return {
                    "ok": True,
                    "pdf_path": r"outputs\ch_paper\ch_paper.pdf",
                    "validation_summary": {"warnings": 0, "errors": 0, "total": 0},
                    "error": None,
                }

            def workflow_latextrans(self):
                calls.append(("normal", self.project_dir))
                return {"ok": False, "error": "wrong path"}

        with patch("src.runtime.CoordinatorAgent", FakeCoordinatorAgent):
            with redirect_stdout(StringIO()):
                status = run_projects(
                    config={"retranslate_with_terms": True},
                    projects=[r"D:\paper"],
                    output_dir="outputs",
                )

        self.assertEqual(calls, [("retranslate", r"D:\paper")])
        self.assertEqual(len(status["completed_projects"]), 1)

    def test_run_projects_event_payload_preserves_term_review_status(self):
        events = []

        class FakeCoordinatorAgent:
            def __init__(self, config, project_dir, output_dir):
                pass

            def workflow_latextrans(self):
                return {
                    "ok": False,
                    "status": "needs_term_review",
                    "project_terms_path": r"outputs\ch_paper\project_terms.csv",
                    "project_terms_decisions_path": r"outputs\ch_paper\project_terms_decisions.json",
                    "error": "review terms",
                }

        with patch("src.runtime.CoordinatorAgent", FakeCoordinatorAgent):
            with redirect_stdout(StringIO()):
                run_projects(
                    config={},
                    projects=[r"D:\paper"],
                    output_dir="outputs",
                    event_callback=events.append,
                )

        final_event = events[-1]
        self.assertEqual(final_event["type"], "project_error")
        self.assertEqual(final_event["status"], "needs_term_review")
        self.assertEqual(final_event["project_terms_path"], r"outputs\ch_paper\project_terms.csv")
        self.assertEqual(
            final_event["project_terms_decisions_path"],
            r"outputs\ch_paper\project_terms_decisions.json",
        )

    def test_run_projects_event_payload_includes_output_and_log_paths(self):
        events = []

        class FakeCoordinatorAgent:
            def __init__(self, config, project_dir, output_dir):
                pass

            def workflow_latextrans(self):
                return {
                    "ok": True,
                    "pdf_path": r"outputs\ch_paper\ch_paper.pdf",
                    "errors_report_path": r"outputs\ch_paper\errors_report.json",
                    "validation_summary": {"warnings": 0, "errors": 0, "total": 0},
                    "error": None,
                }

        with patch("src.runtime.CoordinatorAgent", FakeCoordinatorAgent):
            with redirect_stdout(StringIO()):
                run_projects(
                    config={"target_language": "ch"},
                    projects=[r"D:\tex source\paper"],
                    output_dir=r"D:\repo\outputs",
                    event_callback=events.append,
                )

        start_event = events[0]
        complete_event = events[1]
        self.assertEqual(start_event["type"], "project_start")
        self.assertEqual(start_event["output_dir"], r"D:\repo\outputs\ch_paper")
        self.assertEqual(start_event["log_path"], r"D:\repo\outputs\ch_paper\latextrans.log")
        self.assertEqual(complete_event["type"], "project_complete")
        self.assertEqual(complete_event["output_dir"], r"D:\repo\outputs\ch_paper")
        self.assertEqual(complete_event["log_path"], r"D:\repo\outputs\ch_paper\latextrans.log")
        self.assertEqual(complete_event["pdf_path"], r"outputs\ch_paper\ch_paper.pdf")
        self.assertIsNone(complete_event["error"])

    def test_run_projects_emits_and_writes_agent_log_events(self):
        """Agent log callback should emit project_log events and write latextrans.log."""
        events = []

        class FakeToolAgent(BaseToolAgent):
            """Fake tool agent that exercises BaseToolAgent.log."""

            def __init__(self, config):
                """Store config through the production base class."""
                super().__init__(agent_name="FakeAgent", config=config)

            def execute(self, data=None, **kwargs):
                """Emit one agent log line."""
                self.log("hello from callback")

        class FakeCoordinatorAgent:
            """Fake coordinator that runs one logging tool agent."""

            def __init__(self, config, project_dir, output_dir):
                """Keep the runtime-provided config for the fake workflow."""
                self.config = config

            def workflow_latextrans(self):
                """Run the fake tool agent and return a successful result."""
                FakeToolAgent(self.config).execute()
                return {
                    "ok": True,
                    "pdf_path": None,
                    "errors_report_path": None,
                    "validation_summary": {"warnings": 0, "errors": 0, "total": 0},
                    "error": None,
                }

        with tempfile.TemporaryDirectory() as tmp_dir:
            output_dir = Path(tmp_dir) / "outputs"
            with patch("src.runtime.CoordinatorAgent", FakeCoordinatorAgent):
                with redirect_stdout(StringIO()):
                    run_projects(
                        config={"target_language": "ch"},
                        projects=[r"D:\tex source\paper"],
                        output_dir=str(output_dir),
                        event_callback=events.append,
                    )

            log_path = output_dir / "ch_paper" / "latextrans.log"
            log_text = log_path.read_text(encoding="utf-8")

        log_event = next(event for event in events if event["type"] == "project_log")
        self.assertEqual(log_event["project_name"], "paper")
        self.assertEqual(log_event["agent_name"], "FakeAgent")
        self.assertEqual(log_event["level"], "info")
        self.assertEqual(log_event["line"], "[FakeAgent] [INFO] hello from callback")
        self.assertIn("[FakeAgent] [INFO] hello from callback", log_text)

    def test_run_projects_routes_progress_updates_to_project_log(self):
        """TUI-style runs should log progress updates without writing terminal output."""
        from src.utils.progress import st

        events = []

        class FakeCoordinatorAgent:
            """Fake coordinator that emits one progress update."""

            def __init__(self, config, project_dir, output_dir):
                """Accept the production coordinator constructor arguments."""
                pass

            def workflow_latextrans(self):
                """Emit progress status lines and return a successful result."""
                progress_bar = st.progress(0)
                progress_bar.progress(50, text="halfway")
                st.success("done")
                return {
                    "ok": True,
                    "pdf_path": None,
                    "errors_report_path": None,
                    "validation_summary": {"warnings": 0, "errors": 0, "total": 0},
                    "error": None,
                }

        with tempfile.TemporaryDirectory() as tmp_dir:
            output_dir = Path(tmp_dir) / "outputs"
            stdout = StringIO()
            with patch("src.runtime.CoordinatorAgent", FakeCoordinatorAgent):
                with redirect_stdout(stdout):
                    run_projects(
                        config={"target_language": "ch"},
                        projects=[r"D:\tex source\paper"],
                        output_dir=str(output_dir),
                        event_callback=events.append,
                    )

            log_path = output_dir / "ch_paper" / "latextrans.log"
            log_text = log_path.read_text(encoding="utf-8")

        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("halfway", log_text)
        self.assertIn("done", log_text)
        self.assertTrue(
            any(event["type"] == "project_log" and "halfway" in event["line"] for event in events)
        )
        self.assertTrue(any(event["type"] == "project_log" and event["line"] == "done" for event in events))

    def test_run_projects_exception_event_includes_paths_and_null_result_fields(self):
        events = []

        class FailingCoordinatorAgent:
            def __init__(self, config, project_dir, output_dir):
                pass

            def workflow_latextrans(self):
                raise RuntimeError("boom")

        with patch("src.runtime.CoordinatorAgent", FailingCoordinatorAgent):
            with redirect_stdout(StringIO()):
                run_projects(
                    config={"target_language": "ch"},
                    projects=[r"D:\tex source\paper"],
                    output_dir=r"D:\repo\outputs",
                    event_callback=events.append,
                )

        error_event = events[1]
        self.assertEqual(error_event["type"], "project_error")
        self.assertEqual(error_event["output_dir"], r"D:\repo\outputs\ch_paper")
        self.assertEqual(error_event["log_path"], r"D:\repo\outputs\ch_paper\latextrans.log")
        self.assertIsNone(error_event["pdf_path"])
        self.assertIsNone(error_event["errors_report_path"])
        self.assertIsNone(error_event["validation_summary"])
        self.assertEqual(error_event["error"], "boom")

    def test_run_projects_exception_status_includes_paths_and_null_result_fields(self):
        class FailingCoordinatorAgent:
            def __init__(self, config, project_dir, output_dir):
                pass

            def workflow_latextrans(self):
                raise RuntimeError("boom")

        with patch("src.runtime.CoordinatorAgent", FailingCoordinatorAgent):
            with redirect_stdout(StringIO()):
                status = run_projects(
                    config={"target_language": "ch"},
                    projects=[r"D:\tex source\paper"],
                    output_dir=r"D:\repo\outputs",
                )

        failed_result = status["failed_projects"][0]
        self.assertEqual(failed_result["type"], "failed")
        self.assertFalse(failed_result["ok"])
        self.assertEqual(failed_result["index"], 1)
        self.assertEqual(failed_result["total"], 1)
        self.assertEqual(failed_result["project_name"], "paper")
        self.assertEqual(failed_result["project_dir"], r"D:\tex source\paper")
        self.assertEqual(failed_result["output_dir"], r"D:\repo\outputs\ch_paper")
        self.assertEqual(failed_result["log_path"], r"D:\repo\outputs\ch_paper\latextrans.log")
        self.assertIsNone(failed_result["pdf_path"])
        self.assertIsNone(failed_result["errors_report_path"])
        self.assertIsNone(failed_result["validation_summary"])
        self.assertEqual(failed_result["error"], "boom")


if __name__ == "__main__":
    unittest.main()
