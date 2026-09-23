"""Adapt the existing CoordinatorAgent workflow to the engine interface."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from src.agents.coordinator_agent import CoordinatorAgent


class HeavyEngine:
    """Run one prepared LaTeX project without changing validation or retry behavior."""

    def __init__(self, coordinator_factory: Callable[..., Any] | None = None) -> None:
        """Configure the existing coordinator factory for production or tests."""
        self._coordinator_factory = coordinator_factory or CoordinatorAgent

    def run(
        self,
        input_item: str,
        config: dict[str, Any],
        output_root: Path,
        log_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        """Delegate one project to the unchanged heavy coordinator workflow."""
        project_config = dict(config)
        if log_callback is not None:
            project_config["_project_log_callback"] = log_callback
        coordinator = self._coordinator_factory(
            config=project_config,
            project_dir=input_item,
            output_dir=str(output_root),
        )
        if project_config.get("retranslate_with_terms", False):
            workflow_result = coordinator.workflow_latextrans_with_existing_terms()
        else:
            workflow_result = coordinator.workflow_latextrans()

        result = dict(workflow_result)
        result.setdefault("engine", "heavy")
        result.setdefault("project_name", Path(input_item).name)
        result.setdefault("project_dir", input_item)
        return result
