"""State models for the Textual terminal UI."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ProjectStatus(str, Enum):
    """Project processing status displayed in the UI."""

    PENDING = "pending"
    RUNNING = "running"
    TERMS_READY = "terms_ready"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class ProjectViewState:
    """Display state for one translated project."""

    project_name: str
    status: ProjectStatus = ProjectStatus.PENDING
    project_dir: str | None = None
    output_dir: str | None = None
    pdf_path: str | None = None
    errors_report_path: str | None = None
    project_terms_path: str | None = None
    project_terms_decisions_path: str | None = None
    log_path: str | None = None
    validation_summary: dict[str, Any] | None = None
    error: str | None = None
    zotero_status: str = "not_imported"
    log_lines: list[str] = field(default_factory=list)
    engine: str = "heavy"
    source_markdown_path: str | None = None
    translated_markdown_path: str | None = None
    pdf_error: str | None = None


@dataclass
class TaskViewState:
    """Display state for a single UI-submitted translation task."""

    input_type: str
    inputs: list[str]
    task_id: str = ""
    total: int = 0
    completed: int = 0
    failed: int = 0
    running_project: str | None = None
    completion_notified: bool = False
    notified_project_events: set[tuple[str, str]] = field(default_factory=set)
    events: list[dict[str, Any]] = field(default_factory=list)
    task_log_lines: list[str] = field(default_factory=list)
    projects: list[ProjectViewState] = field(default_factory=list)
    engine: str = "heavy"

    def apply_event(self, event: dict[str, Any]) -> None:
        """Merge a runtime event into UI state."""
        self.events.append(event)
        event_type = event.get("type")
        if event_type == "run_start":
            self.total = int(event.get("total") or 0)
            return

        if event_type == "task_log":
            line = str(event.get("line") or event.get("message") or "")
            if line:
                self.task_log_lines.append(line)
            return

        if event_type == "project_start":
            project = self._get_or_create_project(str(event.get("project_name") or "project"))
            project.status = ProjectStatus.RUNNING
            self.running_project = project.project_name
            self._copy_project_fields(project, event)
            return

        if event_type == "project_log":
            project = self._get_or_create_project(str(event.get("project_name") or "project"))
            line = str(event.get("line") or event.get("message") or "")
            if line:
                project.log_lines.append(line)
            self._copy_project_fields(project, event)
            return

        if event_type in {"project_complete", "project_error", "project_cancelled"}:
            project = self._get_or_create_project(str(event.get("project_name") or "project"))
            self._copy_project_fields(project, event)
            project.status = self._project_status_from_event(event_type, event)
            self.completed = sum(1 for item in self.projects if item.status == ProjectStatus.COMPLETED)
            self.failed = sum(1 for item in self.projects if item.status == ProjectStatus.FAILED)
            return

    def _get_or_create_project(self, project_name: str) -> ProjectViewState:
        """Return existing project state or create a new entry."""
        for project in self.projects:
            if project.project_name == project_name:
                return project
        project = ProjectViewState(project_name=project_name, engine=self.engine)
        self.projects.append(project)
        return project

    def _copy_project_fields(self, project: ProjectViewState, event: dict[str, Any]) -> None:
        """Copy known runtime event fields into a project view state."""
        event_engine = event.get("engine")
        if event_engine in {"heavy", "lite"}:
            project.engine = str(event_engine)
        for key in (
            "project_dir",
            "output_dir",
            "pdf_path",
            "source_markdown_path",
            "translated_markdown_path",
            "errors_report_path",
            "project_terms_path",
            "project_terms_decisions_path",
            "log_path",
            "validation_summary",
            "error",
            "pdf_error",
        ):
            if key in event:
                setattr(project, key, event[key])

    def _project_status_from_event(self, event_type: object, event: dict[str, Any]) -> ProjectStatus:
        """Return the project status represented by a terminal runtime event."""
        if event_type == "project_cancelled":
            return ProjectStatus.CANCELLED
        if event.get("status") == "needs_term_review":
            return ProjectStatus.TERMS_READY
        if event_type == "project_complete":
            return ProjectStatus.COMPLETED
        return ProjectStatus.FAILED
