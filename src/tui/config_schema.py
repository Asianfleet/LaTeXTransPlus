"""配置页字段 schema 和表单值转换。"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from typing import Any, Literal

from src.engines.base import normalize_engine
from src.engines.lite_fonts import DEFAULT_CJK_FONT_CANDIDATES, parse_font_candidates


FieldKind = Literal[
    "input", "textarea", "select", "switch", "integer", "font_list", "font_family"
]

# 字体类字段在输入框下方列出可用字体时使用的语言过滤；None 表示列出全部字体。
FONT_HINT_LANGUAGE_BY_KIND: dict[str, str | None] = {
    "font_list": "zh",
    "font_family": None,
}


@dataclass(frozen=True)
class ConfigField:
    """描述一个可由 TUI 设置页编辑的配置字段。"""

    path: tuple[str, ...]
    label: str
    kind: FieldKind
    section: str
    default: Any = ""
    options: tuple[tuple[str, str], ...] = ()

    @property
    def widget_id(self) -> str:
        """返回字段对应的 Textual widget id。"""
        return "config-" + "-".join(self.path)


LANGUAGE_OPTIONS: tuple[tuple[str, str], ...] = (
    ("中文", "ch"),
    ("英文", "en"),
    ("德文", "de"),
    ("法文", "fr"),
    ("日文", "ja"),
    ("韩文", "ko"),
)

MODE_OPTIONS: tuple[tuple[str, str], ...] = (
    ("plain", "plain"),
)

SEVERITY_OPTIONS: tuple[tuple[str, str], ...] = (
    ("error", "error"),
    ("warning", "warning"),
)

ENGINE_OPTIONS: tuple[tuple[str, str], ...] = (
    ("Heavy", "heavy"),
    ("Lite", "lite"),
)

SHARED_CONFIG_FIELDS: tuple[ConfigField, ...] = (
    ConfigField(("engine",), "默认引擎", "select", "基础", "heavy", ENGINE_OPTIONS),
    ConfigField(("source_language",), "源语言", "select", "基础", "en", LANGUAGE_OPTIONS),
    ConfigField(("target_language",), "目标语言", "select", "基础", "ch", LANGUAGE_OPTIONS),
    ConfigField(("category",), "术语领域", "textarea", "基础", {}),
    ConfigField(("update_term",), "动态术语更新", "switch", "基础", "False"),
    ConfigField(("mode",), "翻译模式", "select", "基础", "plain", MODE_OPTIONS),
    ConfigField(("user_term",), "用户术语文件", "input", "基础", ""),
    ConfigField(("terminology", "enabled"), "启用项目术语", "switch", "术语", True),
    ConfigField(("terminology", "review_before_translate"), "术语审核后再翻译", "switch", "术语", False),
    ConfigField(("terminology", "max_llm_candidates"), "候选术语上限", "integer", "术语", 30),
    ConfigField(("llm_config", "profile"), "LLM 配置 profile", "input", "LLM", ""),
    ConfigField(("zotero", "local_api_base"), "Zotero 本地 API", "input", "Zotero", "http://127.0.0.1:23119/api"),
    ConfigField(("zotero", "web_api_key_env"), "Zotero Web API key 环境变量", "input", "Zotero", "ZOTERO_API_KEY"),
)

HEAVY_CONFIG_FIELDS: tuple[ConfigField, ...] = (
    ConfigField(("heavy", "tex_sources_dir"), "TeX 源目录", "input", "基础", "tex source"),
    ConfigField(("heavy", "output_dir"), "输出目录", "input", "基础", "outputs"),
    ConfigField(("heavy", "paper_list"), "论文列表", "textarea", "基础", []),
    ConfigField(("heavy", "retranslate_with_terms"), "使用已有术语重译", "switch", "基础", False),
    ConfigField(("heavy", "validation", "retry", "max_attempts"), "校验重试次数", "integer", "校验", 3),
    ConfigField(("heavy", "validation", "retry", "generate_pdf_on_error"), "错误时仍生成 PDF", "switch", "校验", True),
    ConfigField(("heavy", "validation", "retry", "fail_on_error"), "校验错误标记失败", "switch", "校验", True),
    ConfigField(("heavy", "validation", "issues", "command_mismatch", "severity"), "命令不匹配级别", "select", "校验", "error", SEVERITY_OPTIONS),
    ConfigField(("heavy", "validation", "issues", "command_mismatch", "retryable"), "命令不匹配可重试", "switch", "校验", True),
    ConfigField(("heavy", "validation", "issues", "placeholder_mismatch", "severity"), "占位符不匹配级别", "select", "校验", "error", SEVERITY_OPTIONS),
    ConfigField(("heavy", "validation", "issues", "placeholder_mismatch", "retryable"), "占位符不匹配可重试", "switch", "校验", True),
    ConfigField(("heavy", "validation", "issues", "bracket_mismatch", "severity"), "括号不匹配级别", "select", "校验", "error", SEVERITY_OPTIONS),
    ConfigField(("heavy", "validation", "issues", "bracket_mismatch", "retryable"), "括号不匹配可重试", "switch", "校验", True),
)

LITE_CONFIG_FIELDS: tuple[ConfigField, ...] = (
    ConfigField(("lite", "output_dir"), "输出目录", "input", "基础", "output-lite"),
    ConfigField(("lite", "mineru_api_key_env"), "MinerU API key 环境变量", "input", "基础", "MINERU_TOKEN"),
    ConfigField(("lite", "mainfont"), "正文字体 mainfont", "font_family", "PDF", ""),
    ConfigField(
        ("lite", "cjk_mainfont_candidates"),
        "中文字体候选",
        "font_list",
        "PDF",
        DEFAULT_CJK_FONT_CANDIDATES,
    ),
    ConfigField(("lite", "geometry"), "页面边距 geometry", "input", "PDF", ""),
)

# 保留旧调用方的默认 heavy 字段集；动态表单应使用 config_fields_for_engine。
CONFIG_FIELDS: tuple[ConfigField, ...] = SHARED_CONFIG_FIELDS + HEAVY_CONFIG_FIELDS


def config_fields_for_engine(engine: str) -> tuple[ConfigField, ...]:
    """Return shared fields plus only the selected engine's settings."""
    selected = normalize_engine(engine)
    engine_fields = HEAVY_CONFIG_FIELDS if selected == "heavy" else LITE_CONFIG_FIELDS
    return SHARED_CONFIG_FIELDS + engine_fields


def grouped_config_fields(engine: str = "heavy") -> list[tuple[str, list[ConfigField]]]:
    """按设置页展示顺序返回字段分组。"""
    sections = ["基础", "术语", "校验", "LLM", "PDF", "Zotero"]
    visible_fields = config_fields_for_engine(engine)
    return [
        (section, fields)
        for section in sections
        if (fields := [field for field in visible_fields if field.section == section])
    ]


def get_config_value(config: dict[str, Any], path: tuple[str, ...], default: Any = "") -> Any:
    """从嵌套配置中读取字段值。"""
    current: Any = config
    for part in path:
        if not isinstance(current, dict) or part not in current:
            return default
        current = current[part]
    return current


def set_config_value(config: dict[str, Any], path: tuple[str, ...], value: Any) -> None:
    """将字段值写入嵌套配置。"""
    current = config
    for part in path[:-1]:
        next_value = current.setdefault(part, {})
        if not isinstance(next_value, dict):
            next_value = {}
            current[part] = next_value
        current = next_value
    current[path[-1]] = value


def form_text_for_field(field: ConfigField, config: dict[str, Any]) -> str:
    """把配置值转换为设置页文本控件内容。"""
    value = get_config_value(config, field.path, field.default)
    if field.path == ("category",):
        return json.dumps(value or {}, ensure_ascii=False)
    if field.path[-1] == "paper_list":
        return json.dumps(value or [], ensure_ascii=False)
    return "" if value is None else str(value)


def bool_for_field(field: ConfigField, config: dict[str, Any]) -> bool:
    """把配置值转换为开关状态。"""
    value = get_config_value(config, field.path, field.default)
    if isinstance(value, str):
        return value.strip().lower() == "true"
    return bool(value)


def select_value_for_field(field: ConfigField, config: dict[str, Any]) -> str:
    """把配置值转换为下拉框当前值。"""
    value = str(get_config_value(config, field.path, field.default))
    allowed = {option_value for _label, option_value in field.options}
    return value if value in allowed else str(field.default)


def normalized_config_from_form(
    base_config: dict[str, Any],
    values: dict[tuple[str, ...], Any],
) -> dict[str, Any]:
    """把表单字段值合并回配置副本，保留不可编辑元数据。"""
    config = copy.deepcopy(base_config)
    if any(path[0] == "llm_config" for path in values):
        config["llm_config"] = {}
    for path, value in values.items():
        set_config_value(config, path, value)
    return config


def parse_textarea_value(field: ConfigField, text: str) -> Any:
    """解析多行文本字段为配置值。"""
    if field.path == ("category",):
        stripped = text.strip()
        if not stripped:
            return {}
        value = json.loads(stripped)
        if not isinstance(value, dict):
            raise ValueError("category 必须是 JSON object。")
        return value
    if field.path[-1] == "paper_list":
        stripped = text.strip()
        if not stripped:
            return []
        value = json.loads(stripped)
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise ValueError("paper_list 必须是 JSON string array。")
        return value
    return text


def parse_font_list_value(field: ConfigField, text: str) -> str:
    """把逗号分隔的字体候选文本规范化为去重后的逗号列表。"""
    if not text.strip():
        return ""
    candidates = parse_font_candidates(text)
    if not candidates:
        raise ValueError(f"{field.label} 必须是逗号分隔的字体名。")
    return ", ".join(candidates)


def parse_font_family_value(field: ConfigField, text: str) -> str:
    """规范化单个字体名，并拒绝误填的逗号列表。"""
    value = " ".join(text.split())
    if "," in value:
        raise ValueError(f"{field.label} 只能填一个字体名，逗号列表请填到中文字体候选。")
    return value


def parse_integer_value(field: ConfigField, text: str) -> int:
    """解析非负整数设置项。"""
    try:
        value = int(text.strip())
    except ValueError as exc:
        raise ValueError(f"{field.label} 必须是非负整数。") from exc
    if value < 0:
        raise ValueError(f"{field.label} 必须是非负整数。")
    return value
