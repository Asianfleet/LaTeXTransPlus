from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


PROJECT_TERMS_FILENAME = "project_terms.csv"
PROJECT_TERMS_DECISIONS_FILENAME = "project_terms_decisions.json"
TERM_CSV_HEADER = ("Source Term", "Target Translation")
NORMALIZED_TERM_CSV_HEADER = tuple(value.casefold() for value in TERM_CSV_HEADER)
CASEFOLD_LANGUAGES = {"en", "de", "fr", "es", "it", "pt", "ru"}


@dataclass(frozen=True)
class TerminologyConfig:
    enabled: bool = True
    review_before_translate: bool = False
    max_llm_candidates: int = 30

    @classmethod
    def from_config(cls, config: dict | None) -> "TerminologyConfig":
        config = config or {}
        terminology = config.get("terminology") or {}
        enabled = terminology.get("enabled", True)
        review_before_translate = terminology.get("review_before_translate", False)
        max_llm_candidates = terminology.get("max_llm_candidates", 30)

        if not isinstance(enabled, bool):
            raise ValueError("terminology.enabled must be a bool")
        if not isinstance(review_before_translate, bool):
            raise ValueError("terminology.review_before_translate must be a bool")
        if (
            isinstance(max_llm_candidates, bool)
            or not isinstance(max_llm_candidates, int)
            or max_llm_candidates < 0
        ):
            raise ValueError("terminology.max_llm_candidates must be a non-negative int")

        return cls(
            enabled=enabled,
            review_before_translate=review_before_translate,
            max_llm_candidates=max_llm_candidates,
        )


@dataclass(frozen=True)
class TermCsvLoadResult:
    terms: dict[str, str]
    warnings: list[str]


@dataclass(frozen=True)
class RetranslationInputs:
    sections_path: Path
    captions_path: Path
    envs_path: Path
    inputs_path: Path
    newcommands_path: Path
    project_terms_path: Path


def project_terms_path(output_dir: Path) -> Path:
    return output_dir / PROJECT_TERMS_FILENAME


def project_terms_decisions_path(output_dir: Path) -> Path:
    return output_dir / PROJECT_TERMS_DECISIONS_FILENAME


def casefold_language(term: str, source_language: str | None) -> str:
    if source_language and source_language.lower() in CASEFOLD_LANGUAGES:
        return term.casefold()
    return term


def load_term_csv(path: Path, *, source_language: str) -> TermCsvLoadResult:
    terms: dict[str, str] = {}
    seen: set[str] = set()
    warnings: list[str] = []

    with path.open("r", encoding="utf-8", newline="") as file:
        reader = csv.reader(file)
        rows = list(reader)

    if rows and _normalize_header_row(rows[0]) == NORMALIZED_TERM_CSV_HEADER:
        rows = rows[1:]

    for row in rows:
        if not row or all(not value.strip() for value in row):
            continue
        if len(row) != 2:
            warnings.append(f"Skipping bad term CSV row: {','.join(row)}")
            continue

        source = row[0].strip()
        target = row[1].strip()
        if not source or not target:
            warnings.append(f"Skipping bad term CSV row: {','.join(row)}")
            continue

        normalized = casefold_language(source, source_language)
        if normalized in seen:
            continue
        seen.add(normalized)
        terms[source] = target

    return TermCsvLoadResult(terms=terms, warnings=warnings)


def _normalize_header_row(row: list[str]) -> tuple[str, ...]:
    return tuple(value.strip().removeprefix("\ufeff").strip().casefold() for value in row)


def merge_term_pairs(
    *term_sources: Iterable[tuple[str, str]], source_language: str
) -> dict[str, str]:
    merged: dict[str, str] = {}
    seen: set[str] = set()

    for term_source in term_sources:
        for source, target in term_source:
            source = source.strip()
            target = target.strip()
            if not source or not target:
                continue
            normalized = casefold_language(source, source_language)
            if normalized in seen:
                continue
            seen.add(normalized)
            merged[source] = target

    return merged


def write_project_terms_csv(path: Path, terms: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(TERM_CSV_HEADER)
        writer.writerows(terms.items())


def require_retranslation_inputs(output_dir: Path) -> RetranslationInputs:
    inputs = RetranslationInputs(
        sections_path=output_dir / "sections_map.json",
        captions_path=output_dir / "captions_map.json",
        envs_path=output_dir / "envs_map.json",
        inputs_path=output_dir / "inputs_map.json",
        newcommands_path=output_dir / "newcommands_map.json",
        project_terms_path=project_terms_path(output_dir),
    )

    for path in [
        inputs.sections_path,
        inputs.captions_path,
        inputs.envs_path,
        inputs.inputs_path,
        inputs.newcommands_path,
        inputs.project_terms_path,
    ]:
        if not path.is_file():
            raise FileNotFoundError(path)

    return inputs
