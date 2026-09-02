"""Tests for the hard-terminable TUI task process wrapper."""

import multiprocessing
import queue
import io
import sys
import unittest
from unittest.mock import MagicMock, patch

from src.tui import process_runner


class TuiProcessRunnerTests(unittest.TestCase):
    """Verify process entry-point messaging and process lifecycle handling."""

    def test_process_entry_emits_events_and_result(self):
        """The child entry point should wrap callback events and its result."""
        messages = multiprocessing.Queue()

        def fake_runner(config_path, input_type, items, overrides, event_callback):
            """Emit one fake event without invoking the real runtime."""
            event_callback({"type": "project_start", "project_name": "paper"})
            return {"completed_projects": ["paper"]}

        with patch.object(process_runner, "run_tui_task", side_effect=fake_runner):
            process_runner._process_entry("config.toml", "local", ["paper"], {"x": 1}, messages)

        self.assertEqual(messages.get(timeout=1), ("event", {"type": "project_start", "project_name": "paper"}))
        self.assertEqual(messages.get(timeout=1), ("result", {"completed_projects": ["paper"]}))

    def test_process_entry_emits_error_message_when_runner_fails(self):
        """Runner exceptions should be converted into an error queue message."""
        messages = multiprocessing.Queue()

        with patch.object(process_runner, "run_tui_task", side_effect=RuntimeError("boom")):
            process_runner._process_entry("config.toml", "local", [], {}, messages)

        self.assertEqual(messages.get(timeout=1), ("error", {"error": "boom"}))

    def test_process_entry_suppresses_all_python_console_streams(self):
        """Child task output must not leak into the parent's Textual terminal."""
        messages = multiprocessing.Queue()
        captured_stdout = io.StringIO()
        captured_stderr = io.StringIO()
        original_streams = (sys.stdout, sys.stderr, sys.__stdout__, sys.__stderr__)

        def fake_runner(config_path, input_type, items, overrides, event_callback):
            """Write through every Python console stream used by task code."""
            print("stdout leak")
            print("stderr leak", file=sys.stderr)
            sys.__stdout__.write("dunder stdout leak\n")
            sys.__stderr__.write("dunder stderr leak\n")
            return {"ok": True}

        sys.stdout = captured_stdout
        sys.stderr = captured_stderr
        sys.__stdout__ = captured_stdout
        sys.__stderr__ = captured_stderr
        try:
            with patch.object(process_runner, "run_tui_task", side_effect=fake_runner):
                process_runner._process_entry("config.toml", "local", [], {}, messages)
        finally:
            sys.stdout, sys.stderr, sys.__stdout__, sys.__stderr__ = original_streams

        self.assertEqual(captured_stdout.getvalue(), "")
        self.assertEqual(captured_stderr.getvalue(), "")
        self.assertEqual(messages.get(timeout=1), ("result", {"ok": True}))

    def test_terminate_terminates_joins_kills_and_closes(self):
        """Termination should force-stop a live process and release resources."""
        process = MagicMock()
        process.is_alive.side_effect = [True, True, False]
        process_runner_handle = process_runner.TuiTaskProcess(process=process, queue=MagicMock())

        process_runner.terminate_tui_task_process(process_runner_handle)

        process.terminate.assert_called_once_with()
        process.join.assert_any_call(timeout=5)
        process.kill.assert_called_once_with()
        process.close.assert_called_once_with()
        process_runner_handle.queue.close.assert_called_once_with()

    def test_drain_process_messages_returns_all_available_messages(self):
        """Draining should be non-blocking and preserve queue order."""
        message_queue = MagicMock()
        message_queue.get_nowait.side_effect = [
            ("event", {"type": "run_start"}),
            ("result", {"ok": True}),
            queue.Empty,
        ]
        handle = process_runner.TuiTaskProcess(process=MagicMock(), queue=message_queue)

        self.assertEqual(
            process_runner.drain_process_messages(handle),
            [("event", {"type": "run_start"}), ("result", {"ok": True})],
        )


if __name__ == "__main__":
    unittest.main()
