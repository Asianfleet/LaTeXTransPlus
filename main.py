import argparse
import sys
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Iterator, Optional, TextIO

from src import runtime
from src.events import JsonLinesEventSink, build_event
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


@contextmanager
def _redirect_console_to_log(log_path: Path) -> Iterator[Path]:
    """将 stdout 和 stderr 都重定向到项目日志文件。"""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8", buffering=1) as log_file:
        with redirect_stdout(log_file):
            with redirect_stderr(log_file):
                yield log_path


def _project_output_dir(output_dir: str, target_language: str, project_dir: str) -> Path:
    return Path(output_dir) / f"{target_language}_{Path(project_dir).name}"


def _project_log_path(output_dir: str, target_language: str, project_dir: str) -> Path:
    return _project_output_dir(output_dir, target_language, project_dir) / "latextrans.log"


@contextmanager
def _redirect_stdout_to_stderr(enabled: bool) -> Iterator[None]:
    """在 JSON stdout 模式下，将普通 stdout 日志改写到 stderr。"""
    if enabled:
        with redirect_stdout(sys.stderr):
            yield
        return
    yield


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
    parser.add_argument(
        "--project-url",
        nargs="+",
        default=[],
        help="Remote project archive URL(s), comma-separated.",
    )
    parser.add_argument("--output", type=str, default="", help="output directory.")
    parser.add_argument("--source", type=str, default="", help="tex source directory.")
    parser.add_argument("--source_language", type=str, default="", help="Source language code.")
    parser.add_argument("--target_language", type=str, default="", help="Target language code.")
    parser.add_argument(
        "--all-existing",
        action="store_true",
        help="Process all existing projects under tex source directory when no explicit --arxiv, --project, or --project-url input is provided.",
    )
    parser.add_argument(
        "--retranslate-with-terms",
        action="store_true",
        default=None,
        help="Reuse an existing parsed output directory and project_terms.csv, then fully retranslate.",
    )
    parser.add_argument(
        "--json-events",
        choices=["stdout"],
        default="",
        help="Emit JSON Lines events to the selected destination.",
    )
    parser.add_argument(
        "--json-events-file",
        type=str,
        default="",
        help="Write JSON Lines events to this file.",
    )

    args = parser.parse_args()
    emit_json_stdout = args.json_events == "stdout"
    arxiv_items = runtime.split_cli_items(args.arxiv)
    project_items = runtime.split_cli_items(args.project)
    project_url_items = runtime.split_cli_items(args.project_url)
    loaded_config = runtime.load_runtime_config(
        config_path=args.config,
        overrides={
            "url": args.url,
            "model": args.model,
            "key": args.key,
            "source": args.source,
            "output": args.output,
            "source_language": args.source_language,
            "target_language": args.target_language,
            "retranslate_with_terms": args.retranslate_with_terms,
            "paper_list": arxiv_items,
        },
    )
    config = runtime.effective_engine_config(loaded_config, "heavy")
    with _redirect_stdout_to_stderr(emit_json_stdout):
        projects, config, _projects_dir, output_dir = runtime.prepare_projects(
            config=config,
            project_items=project_items,
            project_url_items=project_url_items,
            all_existing=args.all_existing,
        )
    target_language = config.get("target_language", "ch")
    source_language = config.get("source_language", "")
    event_sink = JsonLinesEventSink(
        stdout=emit_json_stdout,
        file_path=args.json_events_file or None,
    )

    @contextmanager
    def project_log_context(idx: int, total: int, project_dir: str) -> Iterator[None]:
        log_path = _project_log_path(output_dir, target_language, project_dir)
        console_context = (
            _redirect_console_to_log(log_path)
            if emit_json_stdout
            else _tee_console_to_log(log_path)
        )
        with console_context:
            print(f"Console log will be saved to: {log_path}")
            yield

    project_status = None
    try:
        event_sink.write(
            build_event(
                "run_start",
                total=len(projects),
                config_path=args.config,
                output_dir=output_dir,
                source_language=source_language,
                target_language=target_language,
            )
        )
        try:
            project_status = runtime.run_projects(
                config=config,
                projects=projects,
                output_dir=output_dir,
                event_callback=lambda event: event_sink.write(
                    build_event(
                        event["type"],
                        **{key: value for key, value in event.items() if key != "type"},
                    )
                ),
                project_context=project_log_context,
            )
        except Exception as exc:
            completed_count = 0
            failed_count = len(projects)
            if project_status is not None:
                completed_count = len(project_status.get("completed_projects", []))
                failed_count = max(
                    len(project_status.get("failed_projects", [])),
                    len(projects) - completed_count,
                )
            event_sink.write(
                build_event(
                    "run_complete",
                    ok=False,
                    total=len(projects),
                    completed=completed_count,
                    failed=failed_count,
                    error=str(exc),
                )
            )
            raise
        event_sink.write(
            build_event(
                "run_complete",
                ok=not should_exit_with_failure(project_status),
                total=len(projects),
                completed=len(project_status.get("completed_projects", [])),
                failed=len(project_status.get("failed_projects", [])),
            )
        )
    finally:
        event_sink.close()

    if project_status is not None and should_exit_with_failure(project_status):
        sys.exit(1)


if __name__ == "__main__":
    main()
