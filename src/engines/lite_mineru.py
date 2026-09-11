"""MinerU SDK boundary adapter for the lite translation engine."""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any


DEFAULT_MINERU_API_KEY_ENV = "MINERU_TOKEN"


def normalize_mineru_api_key_env(value: Any) -> str:
    """Return the configured token environment variable name or the default."""
    if isinstance(value, str) and value.strip():
        return value.strip()
    return DEFAULT_MINERU_API_KEY_ENV


class MineruMarkdownExtractor:
    """Extract one PDF into project-local Markdown and referenced resources."""

    def __init__(self, client_factory: Callable[[str], Any] | None = None) -> None:
        """Configure an optional MinerU client factory for integration tests.

        The factory receives the token environment variable name so injected
        test doubles can avoid reading the real process environment.
        """
        self._client_factory = client_factory or _create_default_mineru_client

    def extract(
        self,
        source_pdf: Path,
        output_dir: Path,
        api_key_env: str = DEFAULT_MINERU_API_KEY_ENV,
    ) -> Path:
        """Extract Markdown from ``source_pdf`` and persist it below ``output_dir``.

        ``api_key_env`` names the environment variable holding the MinerU API
        token; it is resolved by the default SDK client factory.
        """
        env_name = normalize_mineru_api_key_env(api_key_env)
        client = self._client_factory(env_name)
        result = _call_mineru_client(client, source_pdf, env_name)
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
                    # Retain every newly created ancestor so a later write failure cleans all of them.
                    missing_directories: list[Path] = []
                    ancestor = parent
                    while ancestor != output_dir and not ancestor.exists():
                        missing_directories.append(ancestor)
                        ancestor = ancestor.parent
                    parent.mkdir(parents=True, exist_ok=True)
                    created_directories.update(missing_directories)
                written_resources.append(destination)
                destination.write_bytes(_resource_bytes(content))
        except (OSError, TypeError, ValueError):
            _cleanup_partial_output(markdown_path, written_resources, created_directories)
            raise

        return markdown_path


def _missing_token_error(env_name: str) -> ValueError:
    """Build an actionable token error that lists variable names but never values."""
    related_names = sorted(name for name in os.environ if "MINERU" in name.upper())
    if related_names:
        hint = (
            "Visible MINERU-related environment variable names: "
            + ", ".join(related_names)
            + "."
        )
    else:
        hint = "No MINERU-related environment variable is visible to this process."
    return ValueError(
        f"Environment variable '{env_name}' is not set or empty. "
        f"{hint} Set it in the shell that starts the TUI and restart the TUI "
        "afterwards, because a running process keeps the environment it was started with."
    )


def _sanitize_token(raw: str) -> str:
    """Remove shell quoting and a stray ``Bearer`` prefix from a token value.

    Windows ``set VAR="value"`` and PowerShell quoting keep literal quotes in the
    value, and the SDK already adds its own ``Bearer`` prefix.  Both mistakes
    reach MinerU as an invalid token, so they are normalized here.
    """
    token = raw.strip()
    changed = True
    while changed and token:
        changed = False
        if len(token) >= 2 and token[0] == token[-1] and token[0] in {'"', "'"}:
            token = token[1:-1].strip()
            changed = True
        elif token[:7].lower() == "bearer ":
            token = token[7:].strip()
            changed = True
    return token


def _create_default_mineru_client(
    api_key_env: str = DEFAULT_MINERU_API_KEY_ENV,
) -> Any:
    """Lazily construct the MinerU SDK client with the resolved API token."""
    try:
        from mineru import MinerU
    except ImportError as exc:
        raise RuntimeError(
            "Lite PDF extraction requires the optional mineru-open-sdk package."
        ) from exc
    env_name = normalize_mineru_api_key_env(api_key_env)
    token = _sanitize_token(os.environ.get(env_name, ""))
    if not token:
        raise _missing_token_error(env_name)
    return MinerU(token=token)


def _call_mineru_client(
    client: Any,
    source_pdf: Path,
    env_name: str = DEFAULT_MINERU_API_KEY_ENV,
) -> Any:
    """Call the small client protocol isolated from MinerU SDK result types."""
    extract = getattr(client, "extract", None)
    if not callable(extract):
        raise TypeError("MinerU client must provide extract(source_pdf).")
    try:
        return extract(str(source_pdf))
    except Exception as exc:
        status = _http_status(exc)
        if status in (401, 403):
            raise RuntimeError(
                f"MinerU rejected the API token from environment variable '{env_name}' "
                f"(HTTP {status}). Verify it is a valid, complete MinerU API token and "
                "that it has no surrounding quotes or 'Bearer ' prefix."
            ) from exc
        raise


def _http_status(exc: BaseException) -> Any:
    """Return the HTTP status carried by a client exception, when present."""
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    return status if isinstance(status, int) else None


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
    """Validate mapping fakes or SDK image lists as paths and byte content."""
    if resources is None:
        return []
    items: list[tuple[str, Any]] = []
    if isinstance(resources, Mapping):
        for path, content in resources.items():
            if not isinstance(path, str):
                raise TypeError("MinerU resource paths must be strings.")
            items.append((path, content))
        return items
    if not isinstance(resources, list):
        raise TypeError("MinerU resources must be a mapping or SDK image list.")
    for image in resources:
        path = _result_value(image, "path")
        content = _result_value(image, "data")
        if not isinstance(path, str):
            raise TypeError("MinerU SDK image paths must be strings.")
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
