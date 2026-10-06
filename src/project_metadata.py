"""从原文产物提取用于项目识别的标题，不依赖翻译或外部服务。"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from pylatexenc.latex2text import LatexNodes2Text

from src.formats.latex.utils import get_command_pattern


def title_from_latex_captions(captions: list[dict[str, Any]]) -> str:
    """从已有 LaTeX 标题记录提取完整嵌套参数中的可读原文。"""
    pattern = get_command_pattern(r"title|icmltitle")
    for caption in captions:
        if not isinstance(caption, dict) or caption.get("cap_type") not in {"title", "icmltitle"}:
            continue
        match = pattern.search(str(caption.get("content") or ""))
        if match:
            # 使用最后的完整花括号参数，避免短标题选项或嵌套格式造成截断。
            argument = match.group(3)[1:-1]
            title = " ".join(LatexNodes2Text().latex_to_text(argument).split())
            if title:
                return title
    return ""


def title_from_markdown(markdown: str) -> str:
    """提取首个非代码块一级标题，并清除常见行内展示标记。"""
    fence_character = ""
    fence_length = 0
    for line in markdown.splitlines():
        fence = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line)
        if fence:
            marker = fence.group(1)
            if not fence_character:
                fence_character, fence_length = marker[0], len(marker)
            elif marker[0] == fence_character and len(marker) >= fence_length and not fence.group(2).strip():
                fence_character = ""
            continue
        if fence_character:
            continue
        heading = re.match(r"^ {0,3}#[ \t]+(.+?)(?:[ \t]+#+)?[ \t]*$", line)
        if heading:
            text = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", heading.group(1))
            text = re.sub(r"<[^>]+>", "", text)
            return " ".join(text.replace("**", "").replace("__", "").replace("`", "").strip("*_ ").split())
    return ""


def read_project_title(project_dir: Path, engine: str, source_markdown_path: str | None = None) -> str:
    """容错读取历史原文产物；损坏或缺失产物返回空标题。"""
    try:
        if engine == "lite":
            path = Path(source_markdown_path) if source_markdown_path else project_dir / "source.md"
            return title_from_markdown(path.read_text(encoding="utf-8"))
        captions = json.loads((project_dir / "captions_map.json").read_text(encoding="utf-8"))
        return title_from_latex_captions(captions) if isinstance(captions, list) else ""
    except (OSError, UnicodeError, ValueError):
        return ""
