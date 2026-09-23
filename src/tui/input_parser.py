"""终端 UI 的输入解析和校验工具。"""

from __future__ import annotations

import re
from typing import Literal
from urllib.parse import urlparse

from src.engines.lite_inputs import parse_lite_input

InputType = Literal["arxiv", "local", "remote"]

_ARXIV_ID_PATTERN = re.compile(r"^\d{4}\.\d{4,5}(v\d+)?$")


def parse_input_items(input_type: InputType, text: str) -> list[str]:
    """将用户批量输入拆分为去除空白后的条目列表。"""
    del input_type
    normalized = text.replace("\n", ",")
    return [item.strip() for item in normalized.split(",") if item.strip()]


def validate_input_items(input_type: InputType, items: list[str]) -> list[str]:
    """按所选输入类型返回每个无效条目的错误信息。"""
    errors: list[str] = []
    for item in items:
        parsed = urlparse(item)

        if input_type == "arxiv":
            if _ARXIV_ID_PATTERN.match(item):
                continue
            if (
                parsed.scheme in {"http", "https"}
                and parsed.netloc.lower().endswith("arxiv.org")
            ):
                continue
            errors.append(f"arxiv input must be an arXiv ID or arXiv URL: {item}")
        elif input_type == "local":
            if parsed.scheme in {"http", "https"}:
                errors.append(f"local input must be a local path, not a URL: {item}")
        elif input_type == "remote":
            if parsed.scheme not in {"http", "https"}:
                errors.append(f"remote input must be an http or https URL: {item}")
        else:
            errors.append(f"unsupported input type: {input_type}")

    return errors


def validate_lite_input(value: str) -> list[str]:
    """Return validation errors for the lite engine's exactly-one input contract."""
    stripped = value.strip()
    if not stripped:
        return ["lite input must not be empty"]
    if "," in stripped or "\n" in stripped or "\r" in stripped:
        return ["lite accepts exactly one input item per task"]
    try:
        parse_lite_input(stripped)
    except ValueError as exc:
        return [str(exc)]
    return []
