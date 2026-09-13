"""Markdown block scanning and structural protection for the lite engine."""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Mapping, Sequence


_FENCE_OPEN_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
_HEADING_RE = re.compile(r"^ {0,3}##(?:[ \t]+.*)?$")
_ATX_HEADING_RE = re.compile(
    r"^ {0,3}#{1,6}[ \t]+(?P<title>.*?)(?:[ \t]+#+)?[ \t]*$"
)
_REFERENCE_HEADING_RE = re.compile(
    r"^ {0,3}##[ \t]+(?P<title>.*?)(?:[ \t]+#+)?[ \t]*$"
)
_TABLE_SEPARATOR_RE = re.compile(
    r"^[ \t]*\|?[ \t]*:?-{3,}:?[ \t]*"
    r"(?:\|[ \t]*:?-{3,}:?[ \t]*)+\|?[ \t]*$"
)
_REFERENCE_DEFINITION_RE = re.compile(
    r"^ {0,3}\[(?!\^)[^\]\r\n]+\]:[ \t]*\S.*$"
)
_REFERENCE_DEFINITION_ID_RE = re.compile(
    r"^ {0,3}\[((?!\^)[^\]\r\n]+)\]:[ \t]*\S.*$"
)
_FOOTNOTE_DEFINITION_RE = re.compile(
    r"^ {0,3}\[\^[^\]\r\n]+\]:[ \t]*",
)
_FOOTNOTE_REFERENCE_RE = re.compile(r"\[\^[^\]\r\n]+\]")
_REFERENCE_SUFFIX_RE = re.compile(r"(?<=\])\[(?!\^)[^\]\r\n]+\]")
_COLLAPSED_REFERENCE_RE = re.compile(r"(!?\[([^\]\r\n]+)\])\[\]")
_AUTOLINK_RE = re.compile(r"<(?:https?://|mailto:)[^<>\r\n]+>", re.IGNORECASE)
_BARE_URL_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
_BACKSLASH_MATH_RE = re.compile(
    r"(?<!\\)(?:\\\[(?s:.*?)\\\]|\\\((?s:.*?)\\\))"
)
_ProtectionRange = tuple[int, int, str]
_REFERENCE_HEADING_TITLES = {
    "references",
    "bibliography",
    "reference list",
    "works cited",
    "参考文献",
    "参考资料",
    "文献",
    "参考文献一覧",
    "참고문헌",
    "참고 문헌",
}
_APPENDIX_TITLES_BY_LANGUAGE: dict[str, tuple[str, ...]] = {
    "en": ("appendix", "appendices"),
    "ch": ("附录", "附錄"),
    "cn": ("附录", "附錄"),
    "zh": ("附录", "附錄"),
    "de": ("anhang",),
    "fr": ("annexe",),
    "ja": ("付録",),
    "jp": ("付録",),
    "ko": ("부록",),
}
_NUMBERED_HEADING_PREFIX_RE = re.compile(
    r"^(?:\d+(?:\.\d+)*|[A-Za-z])[.)、:：]\s*"
)


@dataclass(frozen=True)
class MarkdownBlock:
    """Represent one ordered Markdown translation unit."""

    index: int
    text: str
    translatable: bool = True
    preserved_suffix: str = ""


@dataclass(frozen=True)
class ProtectedMarkdown:
    """Store protected Markdown text and its opaque token mapping."""

    text: str
    tokens: Mapping[str, str]
    shortcut_tokens: Mapping[str, str] = field(default_factory=dict)
    collapsed_tokens: Mapping[str, tuple[str, str]] = field(default_factory=dict)

    @property
    def mapping(self) -> Mapping[str, str]:
        """Expose the protected token mapping under a descriptive alias."""
        return self.tokens


class ProtectedTokenValidationError(ValueError):
    """Describe protected tokens that a translation omitted or duplicated."""

    def __init__(
        self,
        missing_tokens: Sequence[str],
        duplicate_tokens: Sequence[str],
    ) -> None:
        """Store invalid token groups and create a concise diagnostic message."""
        self.missing_tokens = tuple(missing_tokens)
        self.duplicate_tokens = tuple(duplicate_tokens)
        diagnostics: list[str] = []
        if self.missing_tokens:
            diagnostics.append(f"missing: {', '.join(self.missing_tokens)}")
        if self.duplicate_tokens:
            diagnostics.append(f"duplicated: {', '.join(self.duplicate_tokens)}")
        super().__init__(f"protected token validation failed ({'; '.join(diagnostics)})")


class _ProtectionBuilder:
    """Replace structural spans with readable, collision-free typed tokens."""

    def __init__(self, source: str) -> None:
        """Keep source text so generated token candidates can avoid collisions."""
        self._source = source
        self._tokens: dict[str, str] = {}
        self._next_token_indices: dict[str, int] = {}
        self._shortcut_tokens: dict[str, str] = {}
        self._collapsed_tokens: dict[str, tuple[str, str]] = {}

    @property
    def tokens(self) -> Mapping[str, str]:
        """Return a copy of the tokens generated so far."""
        return dict(self._tokens)

    @property
    def shortcut_tokens(self) -> Mapping[str, str]:
        """Return shortcut tokens keyed by their original visible markup."""
        return dict(self._shortcut_tokens)

    @property
    def collapsed_tokens(self) -> Mapping[str, tuple[str, str]]:
        """Return collapsed tokens with original labels and explicit targets."""
        return dict(self._collapsed_tokens)

    def shortcut_token(self, target: str, original_markup: str) -> str:
        """Create an inserted token that can restore a shortcut reference target."""
        token = self._stash(target, "REF")
        self._shortcut_tokens[token] = original_markup
        return token

    def collapsed_token(self, original_markup: str, target: str) -> str:
        """Create a token that expands when a collapsed label is translated."""
        token = self._stash("[]", "REF")
        self._collapsed_tokens[token] = (original_markup, target)
        return token

    def replace_ranges(self, text: str, ranges: Sequence[_ProtectionRange]) -> str:
        """Replace sorted non-overlapping character ranges with opaque tokens."""
        normalized = _normalize_protection_ranges(ranges, len(text))
        if not normalized:
            return text

        parts: list[str] = []
        cursor = 0
        for start, end, token_type in normalized:
            parts.append(text[cursor:start])
            parts.append(self._stash(text[start:end], token_type))
            cursor = end
        parts.append(text[cursor:])
        return "".join(parts)

    def _stash(self, value: str, token_type: str) -> str:
        """Save one protected value under a readable type-specific token."""
        index = self._next_token_indices.get(token_type, 0)
        token = f"[[LTP_{token_type}_{index}]]"
        while token in self._source or token in self._tokens:
            index += 1
            token = f"[[LTP_{token_type}_{index}]]"
        self._next_token_indices[token_type] = index + 1
        self._tokens[token] = value
        return token


def split_markdown(
    text: str,
    source_language: str = "en",
    translate_appendix: bool = True,
) -> list[MarkdownBlock]:
    """Split Markdown at sections and optionally preserve appendix blocks."""
    lines = text.splitlines(keepends=True)
    if not lines:
        return [MarkdownBlock(index=0, text="")]

    starts: list[int] = []
    offset = 0
    fence_char: str | None = None
    fence_length = 0
    in_front_matter = _front_matter_range(text) is not None
    appendix_start: int | None = None
    references_seen = False

    for line_number, line in enumerate(lines):
        content = _line_content(line)

        if in_front_matter:
            if line_number > 0 and content.strip(" \t") in {"---", "..."}:
                in_front_matter = False
            offset += len(line)
            continue

        if fence_char is not None:
            if _is_fence_close(content, fence_char, fence_length):
                fence_char = None
                fence_length = 0
            offset += len(line)
            continue

        marker = _fence_marker(content)
        if marker is not None:
            fence_char = marker[0]
            fence_length = len(marker)
            offset += len(line)
            continue

        is_appendix_heading = (
            not translate_appendix
            and _is_appendix_heading(content, source_language)
        )
        is_atx_heading = _ATX_HEADING_RE.match(content) is not None
        is_post_references_heading = (
            not translate_appendix and references_seen and is_atx_heading
        )
        if (
            _HEADING_RE.match(content) is not None
            or is_appendix_heading
            or is_post_references_heading
        ):
            starts.append(offset)
        if (
            (is_appendix_heading or is_post_references_heading)
            and appendix_start is None
        ):
            appendix_start = offset
        if _is_reference_heading(content):
            references_seen = True
        offset += len(line)

    boundaries = ([0] if not starts or starts[0] != 0 else []) + starts + [len(text)]
    return [
        _markdown_block(
            index,
            text[start:end],
            translatable=appendix_start is None or start < appendix_start,
        )
        for index, (start, end) in enumerate(zip(boundaries, boundaries[1:]))
    ]


def rebuild_markdown(blocks: Sequence[MarkdownBlock]) -> str:
    """Rebuild Markdown in index order after validating contiguous indices."""
    ordered = sorted(blocks, key=lambda block: block.index)
    indices = [block.index for block in ordered]
    if len(indices) != len(set(indices)):
        raise ValueError("duplicate Markdown block index")
    if indices != list(range(len(ordered))):
        raise ValueError("Markdown block indices must be contiguous from zero")
    parts: list[str] = []
    for block in ordered:
        if parts:
            trailing_newlines = len(parts[-1]) - len(parts[-1].rstrip("\r\n"))
            if trailing_newlines < 2:
                parts.append("\n" * (2 - trailing_newlines))
        parts.append(block.text)
    return "".join(parts)


def translatable_markdown(blocks: Sequence[MarkdownBlock]) -> str:
    """Return Markdown content eligible for terminology processing."""
    return "\n\n".join(block.text for block in blocks if block.translatable)


def _markdown_block(
    index: int,
    text: str,
    translatable: bool = True,
) -> MarkdownBlock:
    """Build a block and retain reference entries outside the translation input."""
    reference_body_start = _reference_body_start(text)
    if reference_body_start is None:
        return MarkdownBlock(index=index, text=text, translatable=translatable)
    return MarkdownBlock(
        index=index,
        text=text,
        translatable=translatable,
        preserved_suffix=text[reference_body_start:],
    )


def _reference_body_start(text: str) -> int | None:
    """Return the offset after a references heading and its following blank lines."""
    lines = text.splitlines(keepends=True)
    if not lines or not _is_reference_heading(_line_content(lines[0])):
        return None

    offset = len(lines[0])
    for line in lines[1:]:
        if _line_content(line).strip(" \t"):
            break
        offset += len(line)
    return offset


def _is_reference_heading(content: str) -> bool:
    """Return whether a second-level heading introduces a bibliography section."""
    match = _REFERENCE_HEADING_RE.match(content)
    if match is None:
        return False
    title = match.group("title").strip().casefold()
    return title in _REFERENCE_HEADING_TITLES


def _is_appendix_heading(content: str, source_language: str) -> bool:
    """Return whether an ATX heading begins an appendix in the source language."""
    match = _ATX_HEADING_RE.match(content)
    if match is None:
        return False
    title = _NUMBERED_HEADING_PREFIX_RE.sub("", match.group("title").strip())
    titles = _APPENDIX_TITLES_BY_LANGUAGE.get(source_language.strip().casefold(), ())
    for appendix_title in titles:
        if _appendix_title_prefix_matches(title, appendix_title):
            return True
    return False


def _appendix_title_prefix_matches(title: str, appendix_title: str) -> bool:
    """Match an appendix term without accepting a longer Latin word prefix."""
    if not title.casefold().startswith(appendix_title.casefold()):
        return False
    suffix = title[len(appendix_title) :]
    if not suffix:
        return True
    if appendix_title.isascii():
        return not (suffix[0].isalpha() or suffix[0] == "_")
    return True


def protect_markdown(text: str) -> ProtectedMarkdown:
    """Replace non-translatable Markdown structures with opaque tokens."""
    builder = _ProtectionBuilder(text)
    ranges: list[_ProtectionRange] = []
    front_matter = _front_matter_range(text)
    if front_matter is not None:
        ranges.append((*front_matter, "METADATA"))
    ranges.extend(_typed_ranges(_fenced_code_ranges(text), "CODE"))
    ranges.extend(_typed_ranges(_inline_code_ranges(text), "CODE"))
    ranges.extend(_typed_ranges(_backslash_math_ranges(text), "MATH"))
    ranges.extend(_typed_ranges(_dollar_math_ranges(text), "MATH"))
    ranges.extend(_typed_ranges(_footnote_ranges(text), "FOOTNOTE"))
    ranges.extend(_typed_ranges(_reference_suffix_ranges(text), "REF"))
    ranges.extend(_typed_ranges(_inline_destination_ranges(text), "LINK"))
    ranges.extend(_typed_ranges(_regex_ranges(text, _AUTOLINK_RE), "URL"))
    ranges.extend(_typed_ranges(_reference_definition_ranges(text), "REF"))
    ranges.extend(_typed_ranges(_regex_ranges(text, _BARE_URL_RE), "URL"))
    ranges.extend(_typed_ranges(_table_structure_ranges(text), "TABLE"))

    definition_ids = _reference_definition_ids(text)
    protected = builder.replace_ranges(text, ranges)
    protected = _insert_shortcut_reference_tokens(
        protected,
        builder,
        definition_ids,
    )
    protected = _replace_collapsed_reference_tokens(protected, builder)
    return ProtectedMarkdown(
        text=protected,
        tokens=builder.tokens,
        shortcut_tokens=builder.shortcut_tokens,
        collapsed_tokens=builder.collapsed_tokens,
    )


def restore_markdown(text: str, protected: ProtectedMarkdown) -> str:
    """Restore all protected tokens and reject missing or duplicated tokens."""
    missing_tokens: list[str] = []
    duplicate_tokens: list[str] = []
    for token in protected.tokens:
        occurrences = text.count(token)
        if occurrences == 0:
            missing_tokens.append(token)
        elif occurrences > 1:
            duplicate_tokens.append(token)
    if missing_tokens or duplicate_tokens:
        raise ProtectedTokenValidationError(missing_tokens, duplicate_tokens)

    restored = text
    for token, value in protected.tokens.items():
        position = restored.find(token)
        replacement = value
        original_markup = protected.shortcut_tokens.get(token)
        if original_markup is not None and restored[:position].endswith(original_markup):
            replacement = ""
        collapsed = protected.collapsed_tokens.get(token)
        if collapsed is not None:
            original_markup, target = collapsed
            replacement = (
                value if restored[:position].endswith(original_markup) else target
            )
        restored = restored[:position] + replacement + restored[position + len(token) :]
    return restored


def math_span_ranges(text: str) -> list[tuple[int, int]]:
    """Return math span ranges that are not covered by code blocks or code spans."""
    blocked = _normalize_ranges(
        [*_fenced_code_ranges(text), *_inline_code_ranges(text)],
        len(text),
    )
    spans = _normalize_ranges(
        [*_backslash_math_ranges(text), *_dollar_math_ranges(text)],
        len(text),
    )
    return [
        (start, end)
        for start, end in spans
        if not _overlaps_any_range(blocked, start, end)
    ]


def _overlaps_any_range(
    ranges: Sequence[tuple[int, int]],
    start: int,
    end: int,
) -> bool:
    """Return whether one character range intersects any sorted range."""
    return any(
        start < range_end and range_start < end for range_start, range_end in ranges
    )


def _line_content(line: str) -> str:
    """Remove only a line ending while retaining other whitespace."""
    return line.rstrip("\r\n")


def _fence_marker(content: str) -> str | None:
    """Return a valid opening fence marker for one Markdown line."""
    match = _FENCE_OPEN_RE.match(content)
    if match is None:
        return None
    marker = match.group(1)
    if marker.startswith("`") and "`" in match.group(2):
        return None
    return marker


def _is_fence_close(content: str, marker_char: str, minimum: int) -> bool:
    """Return whether a line closes the active Markdown code fence."""
    pattern = rf"^ {{0,3}}{re.escape(marker_char)}{{{minimum},}}[ \t]*$"
    return re.match(pattern, content) is not None


def _normalize_ranges(
    ranges: Sequence[tuple[int, int]], text_length: int
) -> list[tuple[int, int]]:
    """Sort, validate, and de-duplicate non-overlapping character ranges."""
    normalized: list[tuple[int, int]] = []
    for start, end in sorted(set(ranges), key=lambda item: (item[0], -item[1])):
        if start < 0 or end > text_length or start >= end:
            raise ValueError("invalid Markdown protection range")
        if normalized and start < normalized[-1][1]:
            continue
        normalized.append((start, end))
    return normalized


def _normalize_protection_ranges(
    ranges: Sequence[_ProtectionRange], text_length: int
) -> list[_ProtectionRange]:
    """Sort typed protection ranges and discard overlaps after the first span."""
    normalized: list[_ProtectionRange] = []
    for start, end, token_type in sorted(
        set(ranges), key=lambda item: (item[0], -item[1], item[2])
    ):
        if start < 0 or end > text_length or start >= end:
            raise ValueError("invalid Markdown protection range")
        if normalized and start < normalized[-1][1]:
            continue
        normalized.append((start, end, token_type))
    return normalized


def _typed_ranges(
    ranges: Sequence[tuple[int, int]], token_type: str
) -> list[_ProtectionRange]:
    """Attach one semantic token type to a collection of character ranges."""
    return [(start, end, token_type) for start, end in ranges]


def _front_matter_range(text: str) -> tuple[int, int] | None:
    """Locate a complete YAML front-matter region at the document start."""
    lines = text.splitlines(keepends=True)
    if not lines or _line_content(lines[0]).strip(" \t") != "---":
        return None

    offset = len(lines[0])
    for line in lines[1:]:
        content = _line_content(line)
        content_end = offset + len(content)
        if content.strip(" \t") in {"---", "..."}:
            return (0, content_end)
        offset += len(line)
    return None


def _fenced_code_ranges(text: str) -> list[tuple[int, int]]:
    """Locate complete or unterminated fenced code blocks."""
    ranges: list[tuple[int, int]] = []
    lines = text.splitlines(keepends=True)
    offset = 0
    start: int | None = None
    marker_char = ""
    marker_length = 0

    for line in lines:
        content = _line_content(line)
        if start is None:
            marker = _fence_marker(content)
            if marker is not None:
                start = offset
                marker_char = marker[0]
                marker_length = len(marker)
        elif _is_fence_close(content, marker_char, marker_length):
            ranges.append((start, offset + len(content)))
            start = None
            marker_char = ""
            marker_length = 0
        offset += len(line)

    if start is not None:
        ranges.append((start, len(text)))
    return ranges


def _inline_code_ranges(text: str) -> list[tuple[int, int]]:
    """Locate inline code spans using equal-length backtick delimiters."""
    ranges: list[tuple[int, int]] = []
    position = 0
    while position < len(text):
        if text[position] != "`":
            position += 1
            continue
        run_end = position + 1
        while run_end < len(text) and text[run_end] == "`":
            run_end += 1
        if _is_escaped(text, position):
            position = run_end
            continue
        delimiter_length = run_end - position
        close_start = _find_matching_run(text, run_end, "`", delimiter_length)
        if close_start is None:
            position = run_end
            continue
        close_end = close_start + delimiter_length
        ranges.append((position, close_end))
        position = close_end
    return ranges


def _find_matching_run(
    text: str, start: int, character: str, length: int, allow_newline: bool = True
) -> int | None:
    """Find the next delimiter run whose length exactly matches the opener."""
    position = start
    while position < len(text):
        if not allow_newline and text[position] in "\r\n":
            return None
        if text[position] != character:
            position += 1
            continue
        run_end = position + 1
        while run_end < len(text) and text[run_end] == character:
            run_end += 1
        if run_end - position == length and not _is_escaped(text, position):
            return position
        position = run_end
    return None


def _is_escaped(text: str, position: int) -> bool:
    """Return whether the character at a position has an odd escape count."""
    backslashes = 0
    cursor = position - 1
    while cursor >= 0 and text[cursor] == "\\":
        backslashes += 1
        cursor -= 1
    return backslashes % 2 == 1


def _backslash_math_ranges(text: str) -> list[tuple[int, int]]:
    """Locate LaTeX math spans delimited by backslash brackets or parentheses."""
    return _regex_ranges(text, _BACKSLASH_MATH_RE)


def _dollar_math_ranges(text: str) -> list[tuple[int, int]]:
    """Locate single-line dollar math and multiline double-dollar math."""
    ranges: list[tuple[int, int]] = []
    position = 0
    while position < len(text):
        if text[position] != "$" or _is_escaped(text, position):
            position += 1
            continue
        run_end = position + 1
        while run_end < len(text) and text[run_end] == "$":
            run_end += 1
        run_length = run_end - position
        delimiter_length = 2 if run_length == 2 else 1 if run_length == 1 else 0
        if delimiter_length == 0:
            position = run_end
            continue
        close_start = _find_matching_run(
            text,
            run_end,
            "$",
            delimiter_length,
            allow_newline=delimiter_length == 2,
        )
        if close_start is None:
            position = run_end
            continue
        close_end = close_start + delimiter_length
        ranges.append((position, close_end))
        position = close_end
    return ranges


def _footnote_ranges(text: str) -> list[tuple[int, int]]:
    """Locate footnote definition prefixes and inline reference markers."""
    definitions = _line_regex_ranges(text, _FOOTNOTE_DEFINITION_RE)
    references = _regex_ranges(text, _FOOTNOTE_REFERENCE_RE)
    return definitions + references


def _inline_destination_ranges(text: str) -> list[tuple[int, int]]:
    """Locate balanced inline link and image destination parentheses."""
    ranges: list[tuple[int, int]] = []
    position = 0
    while position < len(text) - 1:
        marker = text.find("](", position)
        if marker < 0:
            break
        open_parenthesis = marker + 1
        depth = 1
        cursor = open_parenthesis + 1
        while cursor < len(text):
            character = text[cursor]
            if character in "\r\n" and depth == 1:
                break
            if character == "(" and not _is_escaped(text, cursor):
                depth += 1
            elif character == ")" and not _is_escaped(text, cursor):
                depth -= 1
                if depth == 0:
                    ranges.append((open_parenthesis, cursor + 1))
                    position = cursor + 1
                    break
            cursor += 1
        else:
            position = open_parenthesis + 1
            continue
        if depth != 0:
            position = open_parenthesis + 1
    return ranges


def _reference_suffix_ranges(text: str) -> list[tuple[int, int]]:
    """Locate reference IDs following translatable link or image labels."""
    return _regex_ranges(text, _REFERENCE_SUFFIX_RE)


def _replace_collapsed_reference_tokens(
    text: str, builder: _ProtectionBuilder
) -> str:
    """Replace collapsed suffixes with tokens tied to their original labels."""
    parts: list[str] = []
    cursor = 0
    for match in _COLLAPSED_REFERENCE_RE.finditer(text):
        label = match.group(2)
        if label.startswith("^"):
            continue
        original_markup = match.group(1)
        parts.append(text[cursor : match.start()])
        parts.append(original_markup)
        parts.append(
            builder.collapsed_token(original_markup, f"[{label}]")
        )
        cursor = match.end()
    if not parts:
        return text
    parts.append(text[cursor:])
    return "".join(parts)


def _insert_shortcut_reference_tokens(
    text: str,
    builder: _ProtectionBuilder,
    definitions: set[str],
) -> str:
    """Add protected targets after shortcut references with known definitions."""
    if not definitions:
        return text

    candidates = re.finditer(r"!?\[([^\]\r\n]+)\]", text)
    insertions: list[tuple[int, str]] = []
    for match in candidates:
        label = match.group(1)
        if label.startswith("^") or _normalize_reference_label(label) not in definitions:
            continue
        if match.start() > 0 and text[match.start() - 1] == "]":
            continue
        following = text[match.end() : match.end() + 1]
        if following in {"(", "[", ":"}:
            continue
        target = f"[{label}]"
        insertions.append(
            (match.end(), builder.shortcut_token(target, match.group(0)))
        )

    if not insertions:
        return text
    parts: list[str] = []
    cursor = 0
    for position, token in insertions:
        parts.append(text[cursor:position])
        parts.append(token)
        cursor = position
    parts.append(text[cursor:])
    return "".join(parts)


def _reference_definition_ids(text: str) -> set[str]:
    """Collect normalized IDs from non-footnote reference definitions."""
    identifiers: set[str] = set()
    for line in text.splitlines():
        match = _REFERENCE_DEFINITION_ID_RE.match(line)
        if match is not None:
            identifiers.add(_normalize_reference_label(match.group(1)))
    return identifiers


def _normalize_reference_label(label: str) -> str:
    """Normalize a Markdown reference label for case-insensitive matching."""
    return " ".join(label.split()).casefold()


def _reference_definition_ranges(text: str) -> list[tuple[int, int]]:
    """Locate reference-link definition lines while excluding footnotes."""
    return _line_regex_ranges(text, _REFERENCE_DEFINITION_RE)


def _table_structure_ranges(text: str) -> list[tuple[int, int]]:
    """Locate delimiter rows and structural pipes in Markdown tables."""
    lines: list[tuple[int, str]] = []
    offset = 0
    for line in text.splitlines(keepends=True):
        content = _line_content(line)
        lines.append((offset, content))
        offset += len(line)

    ranges: list[tuple[int, int]] = []
    for index, (line_offset, content) in enumerate(lines):
        separator = _TABLE_SEPARATOR_RE.match(content)
        if separator is None or index == 0:
            continue
        header_offset, header = lines[index - 1]
        if not _unescaped_pipe_positions(header):
            continue

        ranges.append(
            (line_offset + separator.start(), line_offset + separator.end())
        )
        ranges.extend(_pipe_ranges(header, header_offset))

        data_index = index + 1
        while data_index < len(lines):
            data_offset, data = lines[data_index]
            if not data.strip() or not _unescaped_pipe_positions(data):
                break
            ranges.extend(_pipe_ranges(data, data_offset))
            data_index += 1
    return ranges


def _pipe_ranges(line: str, offset: int) -> list[tuple[int, int]]:
    """Return absolute one-character ranges for unescaped table pipes."""
    return [
        (offset + position, offset + position + 1)
        for position in _unescaped_pipe_positions(line)
    ]


def _unescaped_pipe_positions(line: str) -> list[int]:
    """Find pipe characters that are not escaped by an odd backslash run."""
    return [
        position
        for position, character in enumerate(line)
        if character == "|" and not _is_escaped(line, position)
    ]


def _line_regex_ranges(text: str, pattern: re.Pattern[str]) -> list[tuple[int, int]]:
    """Apply a full-line pattern and return absolute ranges for its matches."""
    ranges: list[tuple[int, int]] = []
    offset = 0
    for line in text.splitlines(keepends=True):
        content = _line_content(line)
        match = pattern.match(content)
        if match is not None:
            ranges.append((offset + match.start(), offset + match.end()))
        offset += len(line)
    return ranges


def _regex_ranges(text: str, pattern: re.Pattern[str]) -> list[tuple[int, int]]:
    """Return all non-overlapping ranges matched by a compiled pattern."""
    return [(match.start(), match.end()) for match in pattern.finditer(text)]
