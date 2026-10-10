"""从原文产物提取用于项目识别的标题，不依赖翻译或外部服务。"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from pylatexenc import latex2text, latexwalker
from pylatexenc.latex2text import LatexNodes2Text, MacroTextSpec
from pylatexenc.macrospec import MacroSpec

from src.formats.latex.utils import get_command_pattern, get_newcommand_pattern


def _title_converter(newcommands: list[dict[str, Any]]) -> tuple[LatexNodes2Text, Any]:
    """为标题建立宏上下文，忽略装饰并有限展开项目中的文字宏。"""
    parser_context = latexwalker.get_default_latex_context_db()
    text_context = latex2text.get_default_latex_context_db()
    parser_specs = [MacroSpec("includegraphics", "*[{"), MacroSpec("raisebox", "{[[{"),
                    MacroSpec("centering", "")]
    text_specs = [MacroTextSpec("includegraphics", discard=True),
                  MacroTextSpec("raisebox", simplify_repl="%(4)s"),
                  MacroTextSpec("centering", discard=True)]
    definitions = {}
    pattern = get_newcommand_pattern()
    for command in newcommands:
        if not isinstance(command, dict):
            continue
        for match in pattern.finditer(str(command.get("content") or "")):
            name = match.group(1) or match.group(2)
            if name in {"includegraphics", "raisebox", "centering"}:
                continue
            definitions[name] = (int(match.group(3) or 0), match.group(5))
    active_macros = set()
    expansion_count = 0

    def expand_macro(node, l2tobj):
        """展开宏参数和嵌套宏，并限制循环及过量展开。"""
        nonlocal expansion_count
        name = node.macroname
        if name in active_macros or expansion_count >= 128:
            return ""
        expansion_count += 1
        active_macros.add(name)
        try:
            body = definitions[name][1]
            arguments = node.nodeargd.argnlist if node.nodeargd else []
            for index, argument in reversed(list(enumerate(arguments, 1))):
                value = argument.latex_verbatim() if argument else ""
                if isinstance(argument, latexwalker.LatexGroupNode):
                    value = value[1:-1]
                body = body.replace(f"#{index}", value)
            return l2tobj.latex_to_text(body, latex_context=parser_context)
        finally:
            active_macros.remove(name)

    for name, (argument_count, _) in definitions.items():
        parser_specs.append(MacroSpec(name, "{" * argument_count))
        text_specs.append(MacroTextSpec(name, simplify_repl=expand_macro))
    parser_context.add_context_category("project-title", macros=parser_specs, prepend=True)
    text_context.add_context_category("project-title", macros=text_specs, prepend=True)
    return LatexNodes2Text(latex_context=text_context), parser_context


def title_from_latex_captions(
    captions: list[dict[str, Any]], newcommands: list[dict[str, Any]] | None = None
) -> str:
    """从已有 LaTeX 标题记录提取完整嵌套参数中的可读原文。"""
    pattern = get_command_pattern(r"title|icmltitle")
    converter, parser_context = _title_converter(newcommands or [])
    for caption in captions:
        if not isinstance(caption, dict) or caption.get("cap_type") not in {"title", "icmltitle"}:
            continue
        match = pattern.search(str(caption.get("content") or ""))
        if match:
            # 使用最后的完整花括号参数，避免短标题选项或嵌套格式造成截断。
            argument = match.group(3)[1:-1]
            title = " ".join(converter.latex_to_text(argument, latex_context=parser_context).split())
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
        return title_from_latex_captions(captions, read_project_title_macros(project_dir)) if isinstance(captions, list) else ""
    except (OSError, UnicodeError, ValueError):
        return ""


def read_project_title_macros(project_dir: Path) -> list[dict[str, Any]]:
    """容错读取项目宏映射，宏产物缺失时仍可提取普通标题。"""
    try:
        commands = json.loads((project_dir / "newcommands_map.json").read_text(encoding="utf-8"))
        return commands if isinstance(commands, list) else []
    except (OSError, UnicodeError, ValueError):
        return []
