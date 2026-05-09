import argparse
import sys
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Iterator, Optional, TextIO

from src import runtime
from src.formats.latex.prompts import *
from src.runtime import should_exit_with_failure

PROJECT_ROOT = Path(__file__).resolve().parent


class _TeeWriter:
    def __init__(self, *streams: TextIO):
        self._streams = streams

    def write(self, data: str) -> int:
        for stream in self._streams:
            stream.write(data)
        return len(data)

    def flush(self) -> None:
        for stream in self._streams:
            stream.flush()

    def isatty(self) -> bool:
        return any(getattr(stream, "isatty", lambda: False)() for stream in self._streams)


@contextmanager
def _tee_console_to_log(
    log_path: Path,
    stdout: Optional[TextIO] = None,
    stderr: Optional[TextIO] = None,
) -> Iterator[Path]:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    console_stdout = sys.stdout if stdout is None else stdout
    console_stderr = sys.stderr if stderr is None else stderr

    with log_path.open("w", encoding="utf-8", buffering=1) as log_file:
        with redirect_stdout(_TeeWriter(console_stdout, log_file)):
            with redirect_stderr(_TeeWriter(console_stderr, log_file)):
                yield log_path


def _project_output_dir(output_dir: str, target_language: str, project_dir: str) -> Path:
    return Path(output_dir) / f"{target_language}_{Path(project_dir).name}"


def _project_log_path(output_dir: str, target_language: str, project_dir: str) -> Path:
    return _project_output_dir(output_dir, target_language, project_dir) / "latextrans.log"


def main():
    """
    Main function to run the LaTeXTrans application.
    Allows overriding paper_list from command-line arguments.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=str, default="config/default.toml", help="Path to the config TOML file.")
    parser.add_argument("--model", type=str, default="", help="Model for translating.")
    parser.add_argument("--url", type=str, default="", help="Model url.")
    parser.add_argument("--key", type=str, default="", help="Model key.")
    parser.add_argument("--arxiv", nargs="+", default=[], help="arXiv ID(s), comma-separated.")
    parser.add_argument(
        "--project",
        nargs="+",
        default=[],
        help="Local project path(s) or archive path(s), comma-separated.",
    )
    parser.add_argument("--output", type=str, default="", help="output directory.")
    parser.add_argument("--source", type=str, default="", help="tex source directory.")
    parser.add_argument(
        "--all-existing",
        action="store_true",
        help="Process all existing projects under tex source directory when no --arxiv/--project is provided.",
    )
    parser.add_argument(
        "--retranslate-with-terms",
        action="store_true",
        default=None,
        help="Reuse an existing parsed output directory and project_terms.csv, then fully retranslate.",
    )

    args = parser.parse_args()
    arxiv_items = runtime.split_cli_items(args.arxiv)
    project_items = runtime.split_cli_items(args.project)
    config = runtime.load_runtime_config(
        config_path=args.config,
        overrides={
            "url": args.url,
            "model": args.model,
            "key": args.key,
            "source": args.source,
            "output": args.output,
            "retranslate_with_terms": args.retranslate_with_terms,
            "paper_list": arxiv_items,
        },
    )
    projects, config, _projects_dir, output_dir = runtime.prepare_projects(
        config=config,
        project_items=project_items,
        all_existing=args.all_existing,
    )
    target_language = config.get("target_language", "ch")

    @contextmanager
    def project_log_context(idx: int, total: int, project_dir: str) -> Iterator[None]:
        log_path = _project_log_path(output_dir, target_language, project_dir)
        with _tee_console_to_log(log_path):
            print(f"Console log will be saved to: {log_path}")
            yield

    project_status = runtime.run_projects(
        config=config,
        projects=projects,
        output_dir=output_dir,
        project_context=project_log_context,
    )

    if should_exit_with_failure(project_status):
        sys.exit(1)


if __name__ == "__main__":
    main()
