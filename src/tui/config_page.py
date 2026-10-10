"""封装 TUI 配置页的表单、状态和持久化生命周期。"""

from __future__ import annotations

import copy
from pathlib import Path

import toml
from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.css.query import NoMatches
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Collapsible, Input, Select, Static, Switch, TabPane, TabbedContent, TextArea

from src.engines.base import normalize_engine
from src.engines.lite_fonts import list_available_font_families
from src.tui.config import UI_CONFIG_PATH, list_llm_profiles, load_ui_config, save_ui_config
from src.tui.config_schema import (
    FONT_HINT_LANGUAGE_BY_KIND,
    ConfigField,
    bool_for_field,
    config_fields_for_engine,
    form_text_for_field,
    grouped_config_fields,
    normalized_config_from_form,
    parse_font_family_value,
    parse_font_list_value,
    parse_integer_value,
    parse_textarea_value,
    select_value_for_field,
)
from src.tui.widgets import ConfigTabbedContent


class ConfigPage(Vertical):
    """拥有配置快照并管理设置表单的加载、编辑和保存。"""

    class ConfigChanged(Message):
        """通知父组件配置快照已经持久化。"""

        def __init__(self, config: dict[str, object]) -> None:
            """保存与组件状态隔离的配置副本。"""
            super().__init__()
            self.config = copy.deepcopy(config)

    def __init__(self, engine: str, id: str = "config") -> None:
        """使用指定会话引擎初始化配置页。"""
        super().__init__(id=id)
        self.effective_engine = normalize_engine(engine)
        self.current_config: dict[str, object] = {}
        self.loading_config_form = True
        self._config_loaded = False
        self._font_families_cache: dict[str | None, list[str]] = {}
        self._config_lifecycle_generation = 0
        self._active_config_lifecycles = 0

    def compose(self) -> ComposeResult:
        """组合配置表单与只读 TOML 预览。"""
        with ConfigTabbedContent(initial="config-form-tab", id="config-tabs"):
            with TabPane("配置", id="config-form-tab"):
                with VerticalScroll(id="config-form"):
                    with Vertical(id="config-fields"):
                        yield from self._config_form_widgets()
                    yield Static("", id="config-error")
            with TabPane("预览", id="config-preview-tab"):
                preview = TextArea(id="config-preview", language="toml")
                preview.read_only = True
                yield preview

    def on_mount(self) -> None:
        """等待初始字段及其延迟事件稳定后再允许保存。"""
        self._begin_config_lifecycle()
        self._complete_config_lifecycle()

    def load_config(self) -> None:
        """读取配置，受保护地填充表单并更新预览。"""
        config = load_ui_config(Path.cwd())
        self.set_config(config)
        self._config_loaded = True
        completed = False
        self._begin_config_lifecycle()
        try:
            self._populate_config_form(config)
            self._update_config_preview(config)
            self.query_one("#config-error", Static).update("")
            completed = True
        finally:
            if completed:
                self._complete_config_lifecycle()
            else:
                self._abort_config_lifecycle()

    def get_config(self) -> dict[str, object]:
        """返回配置深拷贝，并在首次读取时按需加载配置。"""
        if not self._config_loaded:
            self.current_config = copy.deepcopy(load_ui_config(Path.cwd()))
            self._config_loaded = True
        return copy.deepcopy(self.current_config)

    def set_config(self, config: dict[str, object]) -> None:
        """替换内部配置快照，不触发表单事件或保存。"""
        self.current_config = copy.deepcopy(config)
        self._config_loaded = bool(config)

    def set_engine(self, engine: str, rebuild: bool = True) -> None:
        """切换表单使用的引擎，并按需异步重建字段。"""
        self.effective_engine = normalize_engine(engine)
        if rebuild and self.is_mounted:
            self._rebuild_config_fields()

    def persist_form(self) -> None:
        """校验当前表单，保存配置并刷新预览。"""
        if self.loading_config_form:
            return
        try:
            config = self._config_from_form()
        except NoMatches:
            return
        except ValueError as exc:
            self.query_one("#config-error", Static).update(str(exc))
            return
        save_ui_config(Path.cwd(), config)
        self.set_config(config)
        self._config_loaded = True
        self._update_config_preview(config)
        self.query_one("#config-error", Static).update("")
        self.post_message(self.ConfigChanged(config))

    def save_default_engine(self, engine: str) -> None:
        """保存未来会话的默认引擎而不改变当前表单引擎。"""
        config = self.get_config()
        config["engine"] = normalize_engine(engine)
        save_ui_config(Path.cwd(), config)
        self.set_config(config)
        self._config_loaded = True
        if self.is_mounted:
            self.post_message(self.ConfigChanged(config))

    def on_input_changed(self, event: Input.Changed) -> None:
        """消费配置输入框变化并立即保存。"""
        if self._is_config_widget(event.input.id):
            event.stop()
            self.persist_form()

    def on_select_changed(self, event: Select.Changed) -> None:
        """消费配置下拉框变化并立即保存。"""
        if self._is_config_widget(event.select.id):
            event.stop()
            self.persist_form()

    def on_switch_changed(self, event: Switch.Changed) -> None:
        """消费配置开关变化并立即保存。"""
        if self._is_config_widget(event.switch.id):
            event.stop()
            self.persist_form()

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        """消费配置多行文本变化并立即保存。"""
        if self._is_config_widget(event.text_area.id):
            event.stop()
            self.persist_form()

    def on_tabbed_content_tab_activated(self, event: TabbedContent.TabActivated) -> None:
        """切到预览页时校验、保存并刷新当前表单。"""
        if event.tabbed_content.id != "config-tabs":
            return
        event.stop()
        if event.pane.id == "config-preview-tab":
            self.persist_form()

    @work(group="config-form", exclusive=True)
    async def _rebuild_config_fields(self) -> None:
        """替换引擎字段，并在挂载完成后受保护地填充快照。"""
        fields = self.query_one("#config-fields", Vertical)
        completed = False
        self._begin_config_lifecycle()
        try:
            await fields.remove_children()
            await fields.mount(*self._config_form_widgets())
            self._populate_config_form(self.get_config())
            completed = True
        finally:
            if completed:
                self._complete_config_lifecycle()
            else:
                self._abort_config_lifecycle()

    def _begin_config_lifecycle(self) -> None:
        """登记一轮配置更新并保持即时保存保护。"""
        self._config_lifecycle_generation += 1
        self._active_config_lifecycles += 1
        self.loading_config_form = True

    def _complete_config_lifecycle(self) -> None:
        """结束一轮配置更新，并在全部更新完成后安排解除保护。"""
        self._finish_config_lifecycle()

    def _abort_config_lifecycle(self) -> None:
        """在异常或取消时归还活动计数，并等待延迟事件排空。"""
        self._finish_config_lifecycle()

    def _finish_config_lifecycle(self) -> None:
        """归还活动计数，并由当前代次安排解除保存保护。"""
        self._active_config_lifecycles -= 1
        if self._active_config_lifecycles == 0:
            generation = self._config_lifecycle_generation
            self.call_after_refresh(self._enable_config_persistence, generation)

    def _enable_config_persistence(self, generation: int) -> None:
        """仅由当前且已完成的生命周期解除即时保存保护。"""
        if generation != self._config_lifecycle_generation:
            return
        if self._active_config_lifecycles != 0:
            return
        self.loading_config_form = False

    def _is_config_widget(self, widget_id: str | None) -> bool:
        """判断事件来源是否为可编辑配置控件。"""
        return bool(widget_id and widget_id.startswith("config-") and widget_id != "config-preview")

    def _config_from_form(self) -> dict[str, object]:
        """将当前表单合并到完整配置快照。"""
        values = self._collect_config_form_values()
        return normalized_config_from_form(self.get_config(), values)

    def _config_form_widgets(self) -> list[Widget]:
        """构造当前会话引擎的配置分组。"""
        widgets: list[Widget] = []
        for section, fields in grouped_config_fields(self.effective_engine):
            widgets.append(Static(section, classes="config-section-title"))
            widgets.extend(self._config_field_row(field) for field in fields)
        return widgets

    def _config_field_row(self, field: ConfigField) -> Vertical:
        """构造带标签及可选提示的单个配置行。"""
        children: list[Widget] = [
            Horizontal(
                Static(field.label, classes="config-field-label"),
                self._config_field_input(field),
                classes="config-field-row",
            )
        ]
        hint = self._config_field_hint(field)
        if hint is not None:
            children.append(hint)
        classes = "config-field-block"
        if hint is not None:
            classes += " config-field-block-with-hint"
        return Vertical(*children, classes=classes)

    def _config_field_hint(self, field: ConfigField) -> Widget | None:
        """返回 profile 或字体字段提示，不需要时返回 None。"""
        if field.path == ("llm_config", "profile"):
            return Static("", id=f"{field.widget_id}-hint", classes="config-field-hint")
        if field.kind not in FONT_HINT_LANGUAGE_BY_KIND:
            return None
        families = self._available_font_families(FONT_HINT_LANGUAGE_BY_KIND[field.kind])
        hint_id = f"{field.widget_id}-hint"
        if not families:
            return Static(
                "未检测到可用字体：需要随 TeX Live 一起安装的 fc-list。",
                id=hint_id,
                classes="config-field-hint",
            )
        return Collapsible(
            Static(", ".join(families), classes="config-font-list"),
            title=f"可用字体 ({len(families)})",
            collapsed=True,
            id=hint_id,
            classes="config-field-hint",
        )

    def _available_font_families(self, language: str | None) -> list[str]:
        """按语言过滤并缓存 fontconfig 报告的字体列表。"""
        if language not in self._font_families_cache:
            self._font_families_cache[language] = list_available_font_families(language)
        return self._font_families_cache[language]

    def _config_field_input(self, field: ConfigField) -> Widget:
        """创建一个 schema 字段所需的 Textual 控件。"""
        if field.kind == "select":
            return Select(field.options, id=field.widget_id)
        if field.kind == "switch":
            return Switch(id=field.widget_id)
        if field.kind == "textarea":
            return TextArea(id=field.widget_id)
        return Input(id=field.widget_id)

    def _populate_config_form(self, config: dict[str, object]) -> None:
        """在阻止 Changed 消息的上下文中填充配置表单。"""
        with self.prevent(Input.Changed, Select.Changed, Switch.Changed, TextArea.Changed):
            for field in config_fields_for_engine(self.effective_engine):
                if field.kind == "select":
                    select = self.query_one(f"#{field.widget_id}", Select)
                    if field.path == ("llm_config", "profile"):
                        self._populate_profile_select(select, config)
                    else:
                        select.value = select_value_for_field(field, config)
                elif field.kind == "switch":
                    self.query_one(f"#{field.widget_id}", Switch).value = bool_for_field(field, config)
                elif field.kind == "textarea":
                    self.query_one(f"#{field.widget_id}", TextArea).text = form_text_for_field(field, config)
                else:
                    self.query_one(f"#{field.widget_id}", Input).value = form_text_for_field(field, config)

    def _populate_profile_select(self, select: Select, config: dict[str, object]) -> None:
        """刷新 profile 选项并保留当前失效值。"""
        options = list_llm_profiles(Path.cwd() / UI_CONFIG_PATH)
        llm_config = config.get("llm_config")
        current = str(llm_config.get("profile") or "") if isinstance(llm_config, dict) else ""
        names = {value for _, value in options}
        hint = ""
        if not options:
            hint = "没有可用 profile，请在 config/provider 中添加 TOML 配置文件。"
        if current and current not in names:
            options.append((f"{current}（文件不存在）", current))
            hint += " 当前 profile 文件不存在，运行前请重新选择。"
        select.set_options(options)
        select.value = current if current else Select.NULL
        select.prompt = "选择 profile" if names else "没有可用 profile"
        self.query_one(f"#{select.id}-hint", Static).update(hint.strip())

    def _collect_config_form_values(self) -> dict[tuple[str, ...], object]:
        """读取并校验当前引擎的所有可见配置字段。"""
        values: dict[tuple[str, ...], object] = {}
        for field in config_fields_for_engine(self.effective_engine):
            if field.kind == "select":
                select = self.query_one(f"#{field.widget_id}", Select)
                values[field.path] = "" if select.is_blank() else str(select.value)
            elif field.kind == "switch":
                value = self.query_one(f"#{field.widget_id}", Switch).value
                values[field.path] = (
                    "True" if value else "False"
                ) if field.path == ("update_term",) else value
            elif field.kind == "textarea":
                text = self.query_one(f"#{field.widget_id}", TextArea).text
                values[field.path] = parse_textarea_value(field, text)
            elif field.kind == "integer":
                text = self.query_one(f"#{field.widget_id}", Input).value
                values[field.path] = parse_integer_value(field, text)
            elif field.kind == "font_list":
                text = self.query_one(f"#{field.widget_id}", Input).value
                values[field.path] = parse_font_list_value(field, text)
            elif field.kind == "font_family":
                text = self.query_one(f"#{field.widget_id}", Input).value
                values[field.path] = parse_font_family_value(field, text)
            else:
                values[field.path] = self.query_one(f"#{field.widget_id}", Input).value
        return values

    def _update_config_preview(self, config: dict[str, object]) -> None:
        """刷新只读 TOML 配置预览。"""
        with self.prevent(TextArea.Changed):
            self.query_one("#config-preview", TextArea).text = toml.dumps(config)
