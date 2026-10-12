"""会话内可拖动侧栏的布局与鼠标交互。"""

from textual import events
from textual.containers import Horizontal
from textual.widgets import Rule


class SidebarLayout(Horizontal):
    """记录侧栏比例，并随整体布局尺寸更新字符列宽。"""

    def __init__(self, **kwargs) -> None:
        """以约五分之一宽度开始一个独立会话。"""
        super().__init__(**kwargs)
        self._sidebar_ratio = 1 / 5

    def set_sidebar_width(self, width: int) -> None:
        """限制实际宽度，并记录供终端缩放使用的会话比例。"""
        total = self.content_size.width
        if total < 2:
            return
        minimum = (total + 7) // 8
        maximum = total // 2
        width = max(minimum, min(maximum, width))
        self.query_one("#sidebar").styles.width = width
        self._sidebar_ratio = width / total

    def on_resize(self, event: events.Resize) -> None:
        """缩放时保留所选比例，并按新的整体宽度限制边界。"""
        total = self.content_size.width
        ratio = self._sidebar_ratio
        self.set_sidebar_width(round(total * ratio))
        # 列宽取整不应在反复缩放时累积改变用户选定的比例。
        self._sidebar_ratio = ratio


class SidebarDivider(Rule):
    """捕获左键拖动，为相邻侧栏设置宽度。"""

    # Screen 在分发 MouseDown 前判断此属性，避免先启动跨控件文本选择。
    ALLOW_SELECT = False

    def __init__(self, **kwargs) -> None:
        """初始化单列垂直分隔线及拖动起点。"""
        super().__init__(orientation="vertical", **kwargs)
        self._drag_origin: tuple[float, int] | None = None

    def on_mouse_down(self, event: events.MouseDown) -> None:
        """记录左键起点并捕获鼠标，允许拖出分隔线。"""
        if event.button != 1:
            return
        layout = self.parent
        if isinstance(layout, SidebarLayout):
            self._drag_origin = (
                event.screen_x,
                layout.query_one("#sidebar").region.width,
            )
            self.capture_mouse()
            self.add_class("dragging")
            event.stop()

    def on_mouse_move(self, event: events.MouseMove) -> None:
        """使用屏幕坐标差调节宽度，避免分隔线移动影响计算。"""
        if self._drag_origin is None:
            return
        layout = self.parent
        if isinstance(layout, SidebarLayout):
            start_x, start_width = self._drag_origin
            layout.set_sidebar_width(start_width + round(event.screen_x - start_x))
            event.stop()

    def on_mouse_up(self, event: events.MouseUp) -> None:
        """左键松开时结束拖动并恢复普通鼠标分发。"""
        if event.button == 1 and self._drag_origin is not None:
            self._drag_origin = None
            self.remove_class("dragging")
            self.release_mouse()
            event.stop()
