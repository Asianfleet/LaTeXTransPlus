"""Persist provider requests and responses for task-level reproducibility."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import threading
from typing import Any


class LlmCallLogger:
    """Append one JSON record for every LLM provider attempt in a task."""

    _write_lock = threading.Lock()

    def __init__(self, output_dir: str | Path | None, agent_name: str) -> None:
        """Initialize a logger that writes below ``output_dir`` when configured."""
        self.output_dir = Path(output_dir) if output_dir else None
        self.agent_name = agent_name

    def record(
        self,
        *,
        operation: str,
        attempt: int,
        payload: Any,
        response: Any = None,
        status_code: int | None = None,
        error: str | None = None,
    ) -> None:
        """Append a UTF-8 JSONL record without storing request headers or credentials."""
        if self.output_dir is None:
            return

        record: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "agent_name": self.agent_name,
            "operation": operation,
            "attempt": attempt,
            "request": payload,
        }
        if status_code is not None:
            record["status_code"] = status_code
        if response is not None:
            record["response"] = response
        if error is not None:
            record["error"] = error

        path = self.output_dir / "llm_calls.jsonl"
        with self._write_lock:
            self.output_dir.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
