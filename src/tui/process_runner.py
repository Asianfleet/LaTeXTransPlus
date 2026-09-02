"""Run TUI translation tasks in independently terminable processes."""

from __future__ import annotations

import multiprocessing
import os
import queue as queue_module
import sys
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
def _suppress_console_output() -> Iterator[None]:
    """Temporarily detach Python console streams from the parent TUI terminal.

    TUI task processes are spawned with ``multiprocessing`` and therefore inherit
    the parent's terminal handles.  Redirecting both regular and dunder streams
    prevents libraries that write to ``sys.__stdout__``/``sys.__stderr__`` from
    corrupting Textual's alternate screen while preserving stream state on exit.
    """
    original_streams: tuple[TextIO, TextIO, TextIO, TextIO] = (
        sys.stdout,
        sys.stderr,
        sys.__stdout__,
        sys.__stderr__,
    )
    with open(os.devnull, "w", encoding="utf-8") as null_stream:
        sys.stdout = null_stream
        sys.stderr = null_stream
        sys.__stdout__ = null_stream
        sys.__stderr__ = null_stream
        try:
            yield
        finally:
            sys.stdout, sys.stderr, sys.__stdout__, sys.__stderr__ = original_streams


def _process_entry(
    config_path: str,
    input_type: str,
    items: list[str],
    overrides: dict[str, Any],
    message_queue: Queue,
) -> None:
    """Execute one TUI task and publish events, result, or failure to the queue."""

    def emit_event(event: dict[str, Any]) -> None:
        """Publish a runtime event tagged for the parent process."""
        message_queue.put(("event", event))

    with _suppress_console_output():
        try:
            result = run_tui_task(
                config_path=config_path,
                input_type=input_type,
                items=items,
                overrides=overrides,
                event_callback=emit_event,
            )
            message_queue.put(("result", result))
        except Exception as exc:  # pragma: no cover - exact exception comes from runtime integrations
            message_queue.put(("error", {"error": str(exc)}))


def start_tui_task_process(
    config_path: str,
    input_type: str,
    items: list[str],
    overrides: dict[str, Any],
) -> TuiTaskProcess:
    """Start a translation task in a fresh process using the spawn context."""

    context = multiprocessing.get_context("spawn")
    message_queue = context.Queue()
    process = context.Process(
        target=_process_entry,
        args=(config_path, input_type, list(items), dict(overrides), message_queue),
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
