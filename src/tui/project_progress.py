"""从工作流日志提取适合侧栏展示的当前进度。"""

import re


_PROGRESS_PATTERNS = (
    r"Translating sections:\s*\d+/\d+",
    r"Retranslating error parts:\s*\d+/\d+",
    r"Parsing LaTeX document",
    r"Requesting terminology decisions",
    r"Validating translation results",
    r"Start generating for project",
    r"Refactoring LaTeX document",
    r"Compiling PDF document",
)
_PROGRESS_RE = re.compile("|".join(_PROGRESS_PATTERNS))


def extract_progress_text(message: str) -> str | None:
    """识别已知阶段与计数，忽略日志装饰及普通调试信息。"""
    match = _PROGRESS_RE.search(message)
    return " ".join(match.group().split()) if match else None
