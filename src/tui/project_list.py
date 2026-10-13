"""侧栏项目条目的标题和临时进度展示。"""

from rich.text import Text
from textual import events
from textual.widgets import ListItem, Static

from src.tui.state import ProjectStatus, ProjectViewState


class ProjectListItem(ListItem):
    """以完整项目身份标识条目，并局部更新第二行进度。"""

    def __init__(
        self, task_id: str, project: ProjectViewState, running_task: bool
    ) -> None:
        """构建单行标题和可隐藏的进度行，保留原有任务颜色。"""
        self.project_key = (task_id, project.project_name)
        self._progress_indent = min(len(project.project_name), 10) + 3
        display_title = project.title or "未识别标题"
        text = f"{project.project_name} · {display_title}"
        title = Static(Text(text, overflow="ellipsis", no_wrap=True))
        tooltip = Text(project.project_name + "\n" + display_title)
        title.tooltip = tooltip
        if running_task:
            title.add_class("running-task-project")
        self.progress_label = Static(classes="project-progress")
        self._displayed_progress: str | None = None
        super().__init__(title, self.progress_label)
        self.tooltip = tooltip
        self.update_progress(project)

    def update_progress(self, project: ProjectViewState) -> None:
        """仅在项目运行且已有阶段文本时显示第二行。"""
        visible = project.status == ProjectStatus.RUNNING and bool(project.progress_text)
        text = project.progress_text if visible else ""
        if self._displayed_progress == text:
            return
        self._displayed_progress = text
        self.progress_label.update(
            Text("⌊ " + text, overflow="ellipsis", no_wrap=True)
        )
        self.progress_label.tooltip = Text(project.progress_text) if visible else None
        self.progress_label.display = visible

    def on_resize(self, event: events.Resize) -> None:
        """缩窄条目时收缩缩进，至少留出十二列展示进度文本。"""
        indent = min(self._progress_indent, max(0, self.content_size.width - 12))
        self.progress_label.styles.padding = (0, 0, 0, indent)
