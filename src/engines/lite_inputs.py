"""Lite-engine PDF input recognition and self-contained project preparation."""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Literal
from urllib.parse import unquote, urlparse

import requests

LiteInputKind = Literal["arxiv", "pdf_url", "local_pdf"]

_ARXIV_ID_PATTERN = re.compile(r"^(?P<identifier>\d{4}\.\d{4,5}(?:v\d+)?)$", re.IGNORECASE)
_SAFE_NAME_CHARACTER_PATTERN = re.compile(r"[^\w.-]", re.UNICODE)


@dataclass(frozen=True)
class LiteInputSpec:
    """Describe one normalized lite-engine source supplied by the user."""

    kind: LiteInputKind
    original: str
    stable_name: str
    url: str | None = None


@dataclass(frozen=True)
class PreparedLiteProject:
    """Expose the self-contained source PDF and metadata for a lite project."""

    project_dir: Path
    source_pdf: Path
    project_name: str
    input_item: str
    input_type: LiteInputKind


class LiteProjectPreparationError(ValueError):
    """Report an acquisition failure together with its retained project directory."""

    def __init__(self, message: str, project_dir: Path) -> None:
        """Store the visible timestamped directory created before the failure."""
        super().__init__(message)
        self.project_dir = Path(project_dir)
        self.project_name = self.project_dir.name


def parse_lite_input(value: str) -> LiteInputSpec:
    """Parse exactly one arXiv, remote PDF, or local PDF input value."""
    original = value.strip()
    if not original:
        raise ValueError("Lite input must not be empty.")
    if "," in original or "\n" in original or "\r" in original:
        raise ValueError("Lite accepts exactly one input item per task.")

    arxiv_id = _parse_arxiv_identifier(original)
    if arxiv_id is not None:
        return LiteInputSpec(
            kind="arxiv",
            original=original,
            stable_name=_safe_stable_name(arxiv_id),
            url=f"https://arxiv.org/pdf/{arxiv_id}.pdf",
        )

    parsed = urlparse(original)
    if parsed.scheme.lower() in {"http", "https"}:
        return LiteInputSpec(
            kind="pdf_url",
            original=original,
            stable_name=_stable_name_from_url(parsed),
            url=original,
        )

    local_path = Path(original)
    if local_path.suffix.lower() != ".pdf":
        raise ValueError("Local lite input must have a PDF suffix.")
    return LiteInputSpec(
        kind="local_pdf",
        original=original,
        stable_name=_safe_stable_name(local_path.stem),
    )


def prepare_lite_project(
    spec: LiteInputSpec,
    output_root: Path,
    http_get: Callable[..., Any] | None = None,
    now: datetime | None = None,
    download_pdf: Callable[[str, Path], Any] | None = None,
) -> PreparedLiteProject:
    """Create one timestamped project directory and place its source at source.pdf."""
    timestamp = now or datetime.now()
    project_dir = _create_project_directory(output_root, spec.stable_name, timestamp)
    source_pdf = project_dir / "source.pdf"

    try:
        if spec.kind == "local_pdf":
            source_path = Path(spec.original)
            if not source_path.is_file():
                raise ValueError(f"Local PDF input must be an existing file: {source_path}")
            if source_path.suffix.lower() != ".pdf":
                raise ValueError(f"Local PDF input must have a PDF suffix: {source_path}")
            shutil.copy2(source_path, source_pdf)
        else:
            if spec.url is None:
                raise ValueError("Remote lite input is missing its download URL.")
            if download_pdf is not None:
                download_pdf(spec.url, source_pdf)
            else:
                _download_pdf(spec.url, source_pdf, http_get or requests.get)
        if not source_pdf.is_file() or source_pdf.stat().st_size == 0:
            raise ValueError("Downloaded or copied PDF source is missing or empty.")
    except ValueError as exc:
        _remove_partial_source(source_pdf)
        raise LiteProjectPreparationError(str(exc), project_dir) from exc
    except (OSError, requests.RequestException) as exc:
        _remove_partial_source(source_pdf)
        action = "copy" if spec.kind == "local_pdf" else "download"
        raise LiteProjectPreparationError(
            f"Failed to {action} lite PDF input: {exc}",
            project_dir,
        ) from exc

    return PreparedLiteProject(
        project_dir=project_dir,
        source_pdf=source_pdf,
        project_name=project_dir.name,
        input_item=spec.original,
        input_type=spec.kind,
    )


def _parse_arxiv_identifier(value: str) -> str | None:
    """Return an arXiv identifier for IDs and arXiv abstract or PDF URLs."""
    direct_match = _ARXIV_ID_PATTERN.fullmatch(value)
    if direct_match:
        return direct_match.group("identifier")

    parsed = urlparse(value)
    if parsed.scheme.lower() not in {"http", "https"}:
        return None
    hostname = (parsed.hostname or "").lower()
    if hostname not in {"arxiv.org", "www.arxiv.org"}:
        return None

    path_parts = [part for part in parsed.path.split("/") if part]
    if len(path_parts) != 2 or path_parts[0].lower() not in {"abs", "pdf"}:
        return None
    identifier = unquote(path_parts[1])
    if path_parts[0].lower() == "pdf" and identifier.lower().endswith(".pdf"):
        identifier = identifier[:-4]
    match = _ARXIV_ID_PATTERN.fullmatch(identifier)
    return match.group("identifier") if match else None


def _stable_name_from_url(parsed_url: Any) -> str:
    """Derive a readable safe stable name from a remote PDF URL path."""
    path_name = Path(unquote(parsed_url.path)).name
    if path_name.lower().endswith(".pdf"):
        path_name = path_name[:-4]
    return _safe_stable_name(path_name or "download")


def _safe_stable_name(value: str) -> str:
    """Return a path-component-safe name while retaining CJK and useful punctuation."""
    normalized = _SAFE_NAME_CHARACTER_PATTERN.sub("_", value.strip())
    normalized = normalized.strip("._")
    if not normalized or normalized in {".", ".."}:
        return "document"
    return normalized


def _create_project_directory(output_root: Path, stable_name: str, timestamp: datetime) -> Path:
    """Create a unique timestamped directory without overwriting an existing project."""
    output_root.mkdir(parents=True, exist_ok=True)
    base_name = f"{_safe_stable_name(stable_name)}_{timestamp.strftime('%Y%m%dT%H%M%S')}"
    candidate = output_root / base_name
    index = 1
    while True:
        try:
            candidate.mkdir()
            return candidate
        except FileExistsError:
            candidate = output_root / f"{base_name}_{index}"
            index += 1


def _download_pdf(url: str, destination: Path, http_get: Callable[..., Any]) -> None:
    """Stream one remote PDF to its destination through an injectable HTTP getter."""
    response = http_get(url, stream=True, timeout=30)
    if hasattr(response, "__enter__"):
        with response as managed_response:
            _write_response(managed_response, destination)
        return
    _write_response(response, destination)


def _write_response(response: Any, destination: Path) -> None:
    """Check an HTTP response and write its nonempty content to a PDF destination."""
    response.raise_for_status()
    with destination.open("wb") as handle:
        for chunk in response.iter_content(8192):
            if chunk:
                handle.write(chunk)


def _remove_partial_source(source_pdf: Path) -> None:
    """Best-effort remove a partially copied or downloaded source PDF."""
    try:
        if source_pdf.exists():
            source_pdf.unlink()
    except OSError:
        pass
