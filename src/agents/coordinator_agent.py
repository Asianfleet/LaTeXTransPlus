import os
import shutil
import json
from typing import Any, Dict, List, Optional
from pathlib import Path
import sys
import asyncio

base_dir = os.getcwd()
sys.path.append(base_dir)

from .tool_agents.base_tool_agent import BaseToolAgent
from .tool_agents.parser_agent import ParserAgent
from .tool_agents.translator_agent import TranslatorAgent, normalize_translation_mode
from .tool_agents.generator_agent import GeneratorAgent
from .tool_agents.validator_agent import ValidatorAgent
from src.validation_policy import ValidationPolicy
import gc


INITIAL_ERRORS_REPORT_FILENAME = "initial_errors_report.json"


def filter_retryable_reports(reports: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [report for report in reports if report.get("retryable", True)]


def summarize_validation_reports(reports: List[Dict[str, Any]]) -> Dict[str, int]:
    summary = {"warnings": 0, "errors": 0, "total": len(reports)}
    for report in reports:
        severity = report.get("severity", "error")
        if severity == "warning":
            summary["warnings"] += 1
        else:
            summary["errors"] += 1
    return summary


def _validation_report_key(report: Dict[str, Any]) -> Optional[tuple]:
    part = report.get("part")
    identifier = report.get("num_or_ph")
    if part is None or identifier is None:
        return None
    return part, identifier


def merge_validation_reports(
    previous_reports: List[Dict[str, Any]],
    retryable_reports: List[Dict[str, Any]],
    retry_results: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    retried_keys = {
        key for key in (_validation_report_key(report) for report in retryable_reports)
        if key is not None
    }
    preserved_reports = []
    for report in previous_reports:
        key = _validation_report_key(report)
        if key is not None:
            if key not in retried_keys:
                preserved_reports.append(report)
        elif report not in retryable_reports:
            preserved_reports.append(report)
    return preserved_reports + retry_results


def should_generate_pdf_after_validation(
    validation_summary: Dict[str, int],
    generate_pdf_on_error: bool,
) -> bool:
    return validation_summary.get("errors", 0) == 0 or generate_pdf_on_error


def save_initial_validation_report(
    output_dir: Path,
    errors_report: List[Dict[str, Any]],
) -> Path:
    report_path = Path(output_dir) / INITIAL_ERRORS_REPORT_FILENAME
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(errors_report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return report_path


def build_workflow_result(
    project_name: str,
    pdf_path: Optional[str],
    errors_report_path: str,
    validation_summary: Dict[str, int],
    validation_failed: bool,
    error: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "project_name": project_name,
        "ok": not validation_failed and error is None,
        "pdf_path": pdf_path,
        "errors_report_path": errors_report_path,
        "validation_summary": validation_summary,
        "error": error,
    }


def format_translation_result_message(
    system_name: str,
    base_name: str,
    pdf_path: str,
    validation_summary: Optional[Dict[str, int]] = None,
    validation_failed: bool = False,
) -> str:
    validation_summary = validation_summary or {"warnings": 0, "errors": 0, "total": 0}
    errors_report_path = os.path.join(os.path.dirname(pdf_path), "errors_report.json")
    if validation_failed and validation_summary["errors"]:
        return (
            f"🤖❌ {system_name}: PDF generated but validation failed for {base_name}; "
            f"remaining validation errors: {validation_summary['errors']}, "
            f"warnings: {validation_summary['warnings']}. "
            f"PDF: {pdf_path}. Error report: {errors_report_path}."
        )
    if validation_summary["errors"]:
        return (
            f"🤖⚠️ {system_name}: PDF generated with validation errors for {base_name}; "
            f"remaining validation errors: {validation_summary['errors']}, "
            f"warnings: {validation_summary['warnings']}. "
            f"PDF: {pdf_path}. Error report: {errors_report_path}."
        )
    if validation_summary["warnings"]:
        return (
            f"🤖⚠️ {system_name}: PDF generated with validation warnings for {base_name}; "
            f"remaining validation warnings: {validation_summary['warnings']}. "
            f"PDF: {pdf_path}. Error report: {errors_report_path}."
        )
    return f"🤖🎉 {system_name}: Successfully translated {base_name} to {pdf_path}."


class CoordinatorAgent:
    """
    The main orchestrator agent for the translation system.
    It coordinates the workflow of various tool agents based on document format
    and configuration.
    """

    def __init__(self, 
                 config: Dict[str, Any],
                 project_dir: str = None,
                 output_dir: Optional[str] = None
                 ):
        """
        Initializes the CoordinatorAgent.
        """
        self.config = config
        self.name = config.get("sys_name", "LaTeXTrans")
        self.target_language = config.get("target_language", "ch")
        self.source_language = config.get("source_language", "en")
        self.project_dir = project_dir  # Project path for parsing
        self.output_dir = output_dir  # Output directory for parsed files
        self.loop = asyncio.new_event_loop()
        self.mode = normalize_translation_mode(config.get("mode", "plain"))
        self.validation_policy = ValidationPolicy.from_config(config or {})

    def run_async(self, coro):
        """
        Run asynchronous coroutines in the existing event loop
        """
        return self.loop.run_until_complete(coro)

    async def workflow_latextrans_async(self) -> Dict[str, Any]:
        """
        initializes the tool agent based on the provided agent name key.
        """
        base_name = os.path.basename(self.project_dir)
        transed_project_dir = os.path.join(self.output_dir, f"{self.target_language}_{base_name}")

        os.makedirs(transed_project_dir, exist_ok=True)

        parser_agent = ParserAgent(config=self.config,
                                   project_dir=self.project_dir,
                                   output_dir=transed_project_dir)
        parser_agent.execute()  

        translator_agent = TranslatorAgent(config=self.config,
                                           project_dir=self.project_dir,
                                           output_dir=transed_project_dir,
                                           trans_mode=self.mode)
        await translator_agent.execute()  # await
        validator_agent = ValidatorAgent(config=self.config,
                                            project_dir=self.project_dir,
                                            output_dir=transed_project_dir)
        errors_report = validator_agent.execute()
        save_initial_validation_report(Path(transed_project_dir), errors_report)
        retryable_reports = filter_retryable_reports(errors_report)
        max_retries = self.validation_policy.max_attempts()
        retry_count = 0
        if retryable_reports:
            translator_agent.trans_mode = "retry"

        while retryable_reports and retry_count < max_retries:
            translator_agent.errors_report = retryable_reports
            await translator_agent.execute(error_retry_count=retry_count, Maxtry=max_retries)
            retry_results = validator_agent.execute(retryable_reports)
            errors_report = merge_validation_reports(errors_report, retryable_reports, retry_results)
            validator_agent.save_file(Path(transed_project_dir, "errors_report.json"), "json", errors_report)
            retryable_reports = filter_retryable_reports(errors_report)
            retry_count += 1

        validation_summary = summarize_validation_reports(errors_report or [])
        validation_failed = self.validation_policy.should_fail(validation_summary)
        errors_report_path = os.path.join(transed_project_dir, "errors_report.json")

        if not should_generate_pdf_after_validation(
            validation_summary=validation_summary,
            generate_pdf_on_error=self.validation_policy.generate_pdf_on_error(),
        ):
            print(
                f"🤖❌ {self.name}: Validation failed for {base_name}; "
                f"PDF generation skipped. Error report: {errors_report_path}."
            )
            return build_workflow_result(
                project_name=base_name,
                pdf_path=None,
                errors_report_path=errors_report_path,
                validation_summary=validation_summary,
                validation_failed=validation_failed,
            )

        generator_agent = GeneratorAgent(config=self.config,
                                         project_dir=self.project_dir,
                                         output_dir=transed_project_dir)
        try:
        
            PDF_file_path = generator_agent.execute()
        except Exception as e:
            print(f"🤖🚧 {self.name}: Failed to translated {os.path.basename(self.project_dir)}.{e}")
            return build_workflow_result(
                project_name=base_name,
                pdf_path=None,
                errors_report_path=errors_report_path,
                validation_summary=validation_summary,
                validation_failed=True,
                error=str(e),
            )
        
        if PDF_file_path:
            new_PDF_path = os.path.join(transed_project_dir, f"{self.target_language}_{base_name}.pdf")
            shutil.move(PDF_file_path, new_PDF_path)
            print(
                format_translation_result_message(
                    system_name=self.name,
                    base_name=os.path.basename(self.project_dir),
                    pdf_path=new_PDF_path,
                    validation_summary=validation_summary,
                    validation_failed=validation_failed,
                )
            )
            return build_workflow_result(
                project_name=base_name,
                pdf_path=new_PDF_path,
                errors_report_path=errors_report_path,
                validation_summary=validation_summary,
                validation_failed=validation_failed,
            )
        else:
            print(f"🤖🚧 {self.name}: Failed to translated {os.path.basename(self.project_dir)}.")
            return build_workflow_result(
                project_name=base_name,
                pdf_path=None,
                errors_report_path=errors_report_path,
                validation_summary=validation_summary,
                validation_failed=True,
                error="PDF generation returned no output path",
            )


    def workflow_latextrans(self) -> Dict[str, Any]:
        """
        Initialize the tool agent and execute the LaTeX conversion workflow 
        (with event loop security management)
        """

        if hasattr(self, 'loop') and not self.loop.is_closed():
            self.loop.close()  

        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)

        try:
            return self.loop.run_until_complete(self.workflow_latextrans_async())

        finally:
            # Complete all asynchronous resource recycling
            if tasks := asyncio.all_tasks(self.loop):
                self.loop.run_until_complete(
                    asyncio.gather(*tasks, return_exceptions=True)
                )

            # Special handling of asynchronous I/O recycling in Windows
            if sys.platform == "win32":
                self.loop.run_until_complete(
                    self.loop.shutdown_asyncgens()
                )

            self.loop.run_until_complete(self.loop.shutdown_default_executor())
