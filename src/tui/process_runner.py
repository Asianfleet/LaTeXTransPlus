"""Run TUI translation tasks in independently terminable processes."""

from __future__ import annotations

import multiprocessing
import os
import queue as queue_module
import sys
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from multiprocessing.queues import Queue
from typing import Any, Iterator, TextIO

from src.tui.runner import run_tui_task

ProcessMessage = tuple[str, object]


@dataclass
class TuiTaskProcess:
    """Hold a spawned translation process and its parent-side message queue."""

    process: multiprocessing.Process
    queue: Queue


@contextmanager
def _capture_console_output(emit_line: Any) -> Iterator[None]:
    """Capture child console output and forward complete lines to the TUI.

    TUI task processes are spawned with ``multiprocessing`` and therefore inherit
    the parent's terminal handles.  Redirecting both regular and dunder streams
    prevents libraries that write to ``sys.__stdout__``/``sys.__stderr__`` from
    corrupting Textual's alternate screen while preserving stream state on exit.
    Separate pipes retain whether a line came from stdout or stderr.
    """
    original_streams: tuple[TextIO, TextIO, TextIO, TextIO] = (
        sys.stdout,
        sys.stderr,
        sys.__stdout__,
        sys.__stderr__,
    )
    saved_fds = (os.dup(1), os.dup(2))
    stdout_read, stdout_write = os.pipe()
    stderr_read, stderr_write = os.pipe()

    def forward_lines(read_fd: int, level: str) -> None:
        """Read one redirected stream and publish each complete output line."""
        with open(read_fd, "r", encoding="utf-8", errors="replace") as stream:
            for line in stream:
                text = line.rstrip("\r\n")
                if text:
                    emit_line(text, level)

    stdout_thread = threading.Thread(target=forward_lines, args=(stdout_read, "info"), daemon=True)
    stderr_thread = threading.Thread(target=forward_lines, args=(stderr_read, "error"), daemon=True)
    try:
        os.dup2(stdout_write, 1)
        os.dup2(stderr_write, 2)
        stdout_stream = open(os.dup(stdout_write), "w", encoding="utf-8", buffering=1)
        stderr_stream = open(os.dup(stderr_write), "w", encoding="utf-8", buffering=1)
        sys.stdout = stdout_stream
        sys.stderr = stderr_stream
        sys.__stdout__ = stdout_stream
        sys.__stderr__ = stderr_stream
        stdout_thread.start()
        stderr_thread.start()
        try:
            yield
        finally:
            stdout_stream.flush()
            stderr_stream.flush()
            sys.stdout, sys.stderr, sys.__stdout__, sys.__stderr__ = original_streams
            stdout_stream.close()
            stderr_stream.close()
    finally:
        os.dup2(saved_fds[0], 1)
        os.dup2(saved_fds[1], 2)
        os.close(saved_fds[0])
        os.close(saved_fds[1])
        os.close(stdout_write)
        os.close(stderr_write)
        stdout_thread.join(timeout=2)
        stderr_thread.join(timeout=2)


def _process_entry(
    config_path: str,
    input_type: str,
    items: list[str],
    overrides: dict[str, Any],
    message_queue: Queue,
    engine: str = "heavy",
) -> None:
    """Execute one TUI task and publish events, result, or failure to the queue."""

    def emit_event(event: dict[str, Any]) -> None:
        """Publish a runtime event tagged for the parent process."""
        tagged_event = dict(event)
        tagged_event["engine"] = engine
        message_queue.put(("event", tagged_event))

    def emit_console_line(line: str, level: str) -> None:
        """Publish output from uninstrumented task code as a task-level log."""
        emit_event({"type": "task_log", "level": level, "message": line, "line": line})

    with _capture_console_output(emit_console_line):
        try:
            result = run_tui_task(
                config_path=config_path,
                input_type=input_type,
                items=items,
                overrides=overrides,
                event_callback=emit_event,
                engine=engine,
            )
            message_queue.put(("result", result))
        except Exception as exc:  # pragma: no cover - exact exception comes from runtime integrations
            message_queue.put(("error", {"error": str(exc)}))


def start_tui_task_process(
    config_path: str,
    input_type: str,
    items: list[str],
    overrides: dict[str, Any],
    engine: str = "heavy",
) -> TuiTaskProcess:
    """Start a translation task in a fresh process using the spawn context."""

    context = multiprocessing.get_context("spawn")
    message_queue = context.Queue()
    process = context.Process(
        target=_process_entry,
        args=(config_path, input_type, list(items), dict(overrides), message_queue, engine),
    )
    process.start()
    return TuiTaskProcess(process=process, queue=message_queue)


def drain_process_messages(handle: TuiTaskProcess) -> list[ProcessMessage]:
    """Drain all currently available child messages without blocking."""

    messages: list[ProcessMessage] = []
    while True:
        try:
            messages.append(handle.queue.get_nowait())
        except queue_module.Empty:
            return messages


def terminate_tui_task_process(handle: TuiTaskProcess) -> None:
    """Force-stop a task process, escalating to kill if termination times out."""

    process = handle.process
    try:
        if process.is_alive():
            process.terminate()
            process.join(timeout=5)
            if process.is_alive():
                kill = getattr(process, "kill", None)
                if kill is not None:
                    kill()
                    process.join(timeout=5)
    finally:
        close_process = getattr(process, "close", None)
        if close_process is not None:
            close_process()
        close_queue = getattr(handle.queue, "close", None)
        if close_queue is not None:
            close_queue()
