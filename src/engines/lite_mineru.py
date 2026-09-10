"""MinerU SDK boundary adapter for the lite translation engine."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any


class MineruMarkdownExtractor:
    """Extract one PDF into project-local Markdown and referenced resources."""

    def __init__(self, client_factory: Callable[[], Any] | None = None) -> None:
        """Configure an optional MinerU client factory for integration tests."""
        self._client_factory = client_factory or _create_default_mineru_client

    def extract(self, source_pdf: Path, output_dir: Path) -> Path:
        """Extract Markdown from ``source_pdf`` and persist it below ``output_dir``."""
        client = self._client_factory()
        result = _call_mineru_client(client, source_pdf)
        markdown, resources = _normalize_mineru_result(result)
        if not markdown or not markdown.strip():
            raise ValueError("MinerU did not return usable Markdown.")

        output_dir.mkdir(parents=True, exist_ok=True)
        markdown_path = output_dir / "source.md"
        written_resources: list[Path] = []
        created_directories: set[Path] = set()
        try:
            markdown_path.write_text(markdown, encoding="utf-8")
            for relative_path, content in _resource_items(resources):
                destination = _resource_destination(output_dir, relative_path)
                parent = destination.parent
                if not parent.exists():
                    parent.mkdir(parents=True, exist_ok=True)
                    created_directories.add(parent)
                written_resources.append(destination)
                destination.write_bytes(_resource_bytes(content))
        except (OSError, TypeError, ValueError):
            _cleanup_partial_output(markdown_path, written_resources, created_directories)
            raise

        return markdown_path


def _create_default_mineru_client() -> Any:
    """Lazily construct the MinerU SDK client for a real lite-engine task."""
    try:
        from mineru_open_sdk import MinerUClient
    except ImportError as exc:
        raise RuntimeError(
            "Lite PDF extraction requires the optional mineru-open-sdk package."
        ) from exc
    return MinerUClient()


def _call_mineru_client(client: Any, source_pdf: Path) -> Any:
    """Call the small client protocol isolated from MinerU SDK result types."""
    extract = getattr(client, "extract", None)
    if not callable(extract):
        raise TypeError("MinerU client must provide extract(source_pdf).")
    return extract(source_pdf)


def _normalize_mineru_result(result: Any) -> tuple[str | None, Any]:
    """Normalize dictionary or object SDK results to Markdown and resources."""
    markdown = _result_value(result, "markdown", "markdown_content", "md")
    resources = _result_value(result, "resources", "files", "images")
    if markdown is not None and not isinstance(markdown, str):
        raise TypeError("MinerU Markdown output must be text.")
    return markdown, resources


def _result_value(result: Any, *names: str) -> Any:
    """Read the first matching value from a mapping or SDK result object."""
    if isinstance(result, Mapping):
        for name in names:
            if name in result:
                return result[name]
        return None
    for name in names:
        if hasattr(result, name):
            return getattr(result, name)
    return None


def _resource_items(resources: Any) -> list[tuple[str, Any]]:
    """Validate MinerU resources as a mapping of relative paths to content."""
    if resources is None:
        return []
    if not isinstance(resources, Mapping):
        raise TypeError("MinerU resources must be a mapping of paths to content.")
    items: list[tuple[str, Any]] = []
    for path, content in resources.items():
        if not isinstance(path, str):
            raise TypeError("MinerU resource paths must be strings.")
        items.append((path, content))
    return items


def _resource_destination(output_dir: Path, relative_path: str) -> Path:
    """Return a safe project-local destination for a MinerU resource path."""
    candidate = Path(relative_path)
    if candidate.is_absolute() or candidate.drive or any(part == ".." for part in candidate.parts):
        raise ValueError(f"MinerU resource path is unsafe: {relative_path!r}")
    if not candidate.parts or any(part in {"", "."} for part in candidate.parts):
        raise ValueError(f"MinerU resource path is invalid: {relative_path!r}")
    return output_dir / candidate


def _resource_bytes(content: Any) -> bytes:
    """Convert resource data returned by MinerU into bytes for persistence."""
    if isinstance(content, bytes):
        return content
    if isinstance(content, bytearray):
        return bytes(content)
    if isinstance(content, memoryview):
        return content.tobytes()
    raise TypeError("MinerU resource content must be bytes-like.")


def _cleanup_partial_output(
    markdown_path: Path,
    resources: list[Path],
    directories: set[Path],
) -> None:
    """Remove files and empty directories written before a resource write failure."""
    for path in [markdown_path, *resources]:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
    for directory in sorted(directories, key=lambda item: len(item.parts), reverse=True):
        try:
            directory.rmdir()
        except OSError:
            pass
