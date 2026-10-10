import os
import shutil
import json
import re
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
from .tool_agents.terminology_agent import TerminologyAgent
from src.terminology import TerminologyConfig, require_retranslation_inputs
from src.validation_policy import ValidationPolicy
from src.project_metadata import read_project_title_macros, title_from_latex_captions
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
    project_terms_path: Optional[str] = None,
    project_terms_decisions_path: Optional[str] = None,
) -> Dict[str, Any]:
    if error is None and validation_failed:
        error = format_validation_failure_message(
            errors_report_path=errors_report_path,
            validation_summary=validation_summary,
        )
    result = {
        "project_name": project_name,
        "ok": not validation_failed and error is None,
        "pdf_path": pdf_path,
        "errors_report_path": errors_report_path,
        "validation_summary": validation_summary,
        "error": error,
    }
    if project_terms_path is not None:
        result["project_terms_path"] = project_terms_path
    if project_terms_decisions_path is not None:
        result["project_terms_decisions_path"] = project_terms_decisions_path
    return result


def build_pdf_failure_result(
    project_name: str,
    pdf_error: str,
    errors_report_path: str,
    validation_summary: Dict[str, int],
    validation_failed: bool,
    project_terms_path: Optional[str] = None,
    project_terms_decisions_path: Optional[str] = None,
) -> Dict[str, Any]:
    """构建“翻译完成但 PDF 生成失败”的项目结果。

    翻译后的 LaTeX 产物仍然可用，因此 PDF 失败只记录在 ``pdf_error`` 中，
    让项目以完成态进入 UI，并显示黄色警告而不是红色异常。若校验本身已经
    失败（``validation_failed`` 为真），则保留校验错误作为项目错误原因。
    """
    result = build_workflow_result(
        project_name=project_name,
        pdf_path=None,
        errors_report_path=errors_report_path,
        validation_summary=validation_summary,
        validation_failed=validation_failed,
        project_terms_path=project_terms_path,
        project_terms_decisions_path=project_terms_decisions_path,
    )
    result["pdf_error"] = pdf_error
    return result


def format_validation_failure_message(
    errors_report_path: str,
    validation_summary: Dict[str, int],
) -> str:
    """构造校验重试耗尽后的稳定失败摘要。"""
    return (
        "Validation failed after retries; "
        f"remaining validation errors: {validation_summary.get('errors', 0)}, "
        f"warnings: {validation_summary.get('warnings', 0)}. "
        f"Error report: {errors_report_path}."
    )


def should_run_terminology_scan(config: Dict[str, Any]) -> bool:
    return TerminologyConfig.from_config(config or {}).enabled


def build_review_required_result(
    project_name: str,
    project_terms_path: str,
    project_terms_decisions_path: str,
) -> Dict[str, Any]:
    return {
        "project_name": project_name,
        "ok": False,
        "status": "needs_term_review",
        "pdf_path": None,
        "errors_report_path": None,
        "validation_summary": {"warnings": 0, "errors": 0, "total": 0},
        "error": "Project terms generated; review project_terms.csv before translation.",
        "project_terms_path": project_terms_path,
        "project_terms_decisions_path": project_terms_decisions_path,
    }


PDF_ONLY_SOURCE_ERROR = (
    "LaTeX source only embeds external PDF pages via \\includepdf; "
    "no translatable LaTeX body text was found. Provide the real LaTeX source, "
    "or run a PDF/OCR translation workflow instead."
)


def build_unsupported_source_result(
    project_name: str,
    errors_report_path: str,
    error: str,
) -> Dict[str, Any]:
    return {
        "project_name": project_name,
        "ok": False,
        "status": "unsupported_source",
        "pdf_path": None,
        "errors_report_path": errors_report_path,
        "validation_summary": {"warnings": 0, "errors": 1, "total": 1},
        "error": error,
    }


def save_unsupported_source_report(output_dir: Path, error: str) -> Path:
    report_path = Path(output_dir) / "errors_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report = [
        {
            "part": "source",
            "num_or_ph": "project",
            "type": "unsupported_source",
            "severity": "error",
            "retryable": False,
            "message": error,
        }
    ]
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report_path


def read_parsed_latex_maps(output_dir: Path) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    def read_json_list(filename: str) -> List[Dict[str, Any]]:
        path = Path(output_dir) / filename
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return []
        return data if isinstance(data, list) else []

    return (
        read_json_list("sections_map.json"),
        read_json_list("captions_map.json"),
        read_json_list("envs_map.json"),
    )


def _section_ids(section_id: Any) -> set[str]:
    return {part.strip() for part in str(section_id).split("+") if part.strip()}


def _contains_included_pdf(content: str) -> bool:
    return bool(re.search(r"\\includepdf(?:\s*\[[^\]]*\])?\s*\{", content or ""))


def _document_body(content: str) -> str:
    match = re.search(r"\\begin\s*\{document\}", content or "")
    if not match:
        return content or ""
    return content[match.end():]


def _visible_text_without_pdf_includes(content: str) -> str:
    text = re.sub(r"\\includepdf(?:\s*\[[^\]]*\])?\s*\{[^{}]*\}", " ", content or "")
    text = re.sub(r"<PLACEHOLDER_[^>]+>", " ", text)
    text = re.sub(r"\\(?:begin|end)\s*\{[^{}]*\}", " ", text)
    text = re.sub(r"\\[a-zA-Z]+\*?(?:\s*\[[^\]]*\])?(?:\s*\{[^{}]*\})?", " ", text)
    text = re.sub(r"[{}\\$&_^%#~]", " ", text)
    return " ".join(text.split())


def _has_translatable_latex_body(sections: List[Dict[str, Any]], envs: List[Dict[str, Any]]) -> bool:
    for section in sections:
        ids = _section_ids(section.get("section"))
        if ids == {"-1"}:
            continue

        content = section.get("content", "")
        if ids and ids.issubset({"-1", "0"}):
            content = _document_body(content)

        if _visible_text_without_pdf_includes(content):
            return True

    for env in envs:
        if env.get("need_trans") and _visible_text_without_pdf_includes(env.get("content", "")):
            return True

    return False


def is_pdf_only_latex_source(
    sections: List[Dict[str, Any]],
    captions: List[Dict[str, Any]],
    envs: List[Dict[str, Any]],
) -> bool:
    del captions
    if not isinstance(sections, list) or not isinstance(envs, list):
        return False
    combined_source = "\n".join(section.get("content", "") for section in sections)
    combined_source += "\n".join(env.get("content", "") for env in envs)
    return _contains_included_pdf(combined_source) and not _has_translatable_latex_body(sections, envs)


def clear_translated_content(
    sections: List[Dict[str, Any]],
    captions: List[Dict[str, Any]],
    envs: List[Dict[str, Any]],
) -> None:
    for section in sections:
        if str(section.get("section")) in {"-1", "0"}:
            section["trans_content"] = section.get("content", section.get("trans_content", ""))
        else:
            section["trans_content"] = ""
    for caption in captions:
        caption["trans_content"] = ""
    for env in envs:
        env["trans_content"] = ""


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

    def _log(self, message: str, level: str = "info") -> None:
        """将协调器状态写入项目日志，并按配置转发到控制台。"""
        level_labels = {
            "info": "INFO",
            "debug": "DEBUG",
            "warning": "WARNING",
            "error": "ERROR",
        }
        if level not in level_labels:
            raise ValueError(f"Unknown log level: {level}")

        line = f"[CoordinatorAgent] [{level_labels[level]}] {message}"
        log_callback = self.config.get("_project_log_callback")
        if callable(log_callback):
            log_callback(
                {
                    "agent_name": "CoordinatorAgent",
                    "level": level,
                    "message": message,
                    "line": line,
                }
            )
            if self.config.get("_project_log_print_console"):
                print(line)
            return
        print(line)

    def _emit_project_metadata(self, captions: List[Dict[str, Any]], output_dir: str) -> None:
        """解析后立即发送原文标题，重译和后续失败也保留项目识别信息。"""
        callback = self.config.get("_project_metadata_callback")
        if callable(callback):
            callback({
                "type": "project_metadata",
                "project_name": Path(self.project_dir).name,
                "output_dir": output_dir,
                "title": title_from_latex_captions(captions, read_project_title_macros(Path(output_dir))),
            })

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

        sections, captions, envs = read_parsed_latex_maps(Path(transed_project_dir))
        self._emit_project_metadata(captions, transed_project_dir)
        errors_report_path = os.path.join(transed_project_dir, "errors_report.json")
        if is_pdf_only_latex_source(sections, captions, envs):
            save_unsupported_source_report(Path(transed_project_dir), PDF_ONLY_SOURCE_ERROR)
            print(f"🤖❌ {self.name}: {PDF_ONLY_SOURCE_ERROR} Error report: {errors_report_path}.")
            return build_unsupported_source_result(
                project_name=base_name,
                errors_report_path=errors_report_path,
                error=PDF_ONLY_SOURCE_ERROR,
            )

        terminology_config = TerminologyConfig.from_config(self.config or {})
        terminology_result: Dict[str, Any] = {}
        if should_run_terminology_scan(self.config or {}):
            terminology_agent = TerminologyAgent(
                config=self.config,
                project_dir=self.project_dir,
                output_dir=transed_project_dir,
            )
            terminology_result = terminology_agent.execute()
            if terminology_config.review_before_translate:
                print(
                    f"🤖⏸️ {self.name}: Project terms generated for {base_name}. "
                    f"Review {terminology_result['project_terms_path']} and rerun with --retranslate-with-terms."
                )
                return build_review_required_result(
                    project_name=base_name,
                    project_terms_path=terminology_result["project_terms_path"],
                    project_terms_decisions_path=terminology_result["project_terms_decisions_path"],
                )

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
            translator_agent.enable_retranslation()

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
        validation_error = (
            format_validation_failure_message(errors_report_path, validation_summary)
            if validation_failed
            else None
        )
        if validation_error:
            self._log(validation_error, level="error")

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
                error=validation_error,
                project_terms_path=terminology_result.get("project_terms_path"),
                project_terms_decisions_path=terminology_result.get("project_terms_decisions_path"),
            )

        generator_agent = GeneratorAgent(config=self.config,
                                         project_dir=self.project_dir,
                                         output_dir=transed_project_dir)
        try:
        
            PDF_file_path = generator_agent.execute()
        except Exception as e:
            pdf_error = f"Generation failed ({type(e).__name__}): {e}"
            self._log(
                f"{self.name}: PDF generation failed for {os.path.basename(self.project_dir)}. {pdf_error}",
                level="warning",
            )
            return build_pdf_failure_result(
                project_name=base_name,
                pdf_error=pdf_error,
                errors_report_path=errors_report_path,
                validation_summary=validation_summary,
                validation_failed=validation_failed,
                project_terms_path=terminology_result.get("project_terms_path"),
                project_terms_decisions_path=terminology_result.get("project_terms_decisions_path"),
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
                project_terms_path=terminology_result.get("project_terms_path"),
                project_terms_decisions_path=terminology_result.get("project_terms_decisions_path"),
            )
        else:
            pdf_error = "PDF generation returned no output path"
            self._log(
                f"{self.name}: PDF generation failed for {os.path.basename(self.project_dir)}. "
                f"{pdf_error}",
                level="warning",
            )
            return build_pdf_failure_result(
                project_name=base_name,
                pdf_error=pdf_error,
                errors_report_path=errors_report_path,
                validation_summary=validation_summary,
                validation_failed=validation_failed,
                project_terms_path=terminology_result.get("project_terms_path"),
                project_terms_decisions_path=terminology_result.get("project_terms_decisions_path"),
            )

    async def workflow_latextrans_with_existing_terms_async(self) -> Dict[str, Any]:
        base_name = os.path.basename(self.project_dir)
        transed_project_dir = os.path.join(self.output_dir, f"{self.target_language}_{base_name}")
        require_retranslation_inputs(Path(transed_project_dir))

        translator_agent = TranslatorAgent(
            config=self.config,
            project_dir=self.project_dir,
            output_dir=transed_project_dir,
            trans_mode=self.mode,
        )

        sections = translator_agent.read_file(Path(transed_project_dir, "sections_map.json"), "json")
        captions = translator_agent.read_file(Path(transed_project_dir, "captions_map.json"), "json")
        self._emit_project_metadata(captions, transed_project_dir)
        envs = translator_agent.read_file(Path(transed_project_dir, "envs_map.json"), "json")
        errors_report_path = os.path.join(transed_project_dir, "errors_report.json")
        if is_pdf_only_latex_source(sections, captions, envs):
            save_unsupported_source_report(Path(transed_project_dir), PDF_ONLY_SOURCE_ERROR)
            return build_unsupported_source_result(
                project_name=base_name,
                errors_report_path=errors_report_path,
                error=PDF_ONLY_SOURCE_ERROR,
            )

        clear_translated_content(sections, captions, envs)
        translator_agent.save_file(Path(transed_project_dir, "sections_map.json"), "json", sections)
        translator_agent.save_file(Path(transed_project_dir, "captions_map.json"), "json", captions)
        translator_agent.save_file(Path(transed_project_dir, "envs_map.json"), "json", envs)

        await translator_agent.execute()

        validator_agent = ValidatorAgent(
            config=self.config,
            project_dir=self.project_dir,
            output_dir=transed_project_dir,
        )
        errors_report = validator_agent.execute()
        retryable_reports = filter_retryable_reports(errors_report)
        max_retries = self.validation_policy.max_attempts()
        retry_count = 0
        if retryable_reports:
            translator_agent.enable_retranslation()

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
        validation_error = (
            format_validation_failure_message(errors_report_path, validation_summary)
            if validation_failed
            else None
        )
        if validation_error:
            self._log(validation_error, level="error")

        if not should_generate_pdf_after_validation(
            validation_summary=validation_summary,
            generate_pdf_on_error=self.validation_policy.generate_pdf_on_error(),
        ):
            return build_workflow_result(
                project_name=base_name,
                pdf_path=None,
                errors_report_path=errors_report_path,
                validation_summary=validation_summary,
                validation_failed=validation_failed,
                error=validation_error,
            )

        generator_agent = GeneratorAgent(
            config=self.config,
            project_dir=self.project_dir,
            output_dir=transed_project_dir,
        )
        try:
            pdf_file_path = generator_agent.execute()
        except Exception as e:
            pdf_error = f"Generation failed ({type(e).__name__}): {e}"
            self._log(
                f"{self.name}: PDF generation failed for {os.path.basename(self.project_dir)}. {pdf_error}",
                level="warning",
            )
            return build_pdf_failure_result(
                project_name=base_name,
                pdf_error=pdf_error,
                errors_report_path=errors_report_path,
                validation_summary=validation_summary,
                validation_failed=validation_failed,
            )

        if not pdf_file_path:
            pdf_error = "PDF generation returned no output path"
            self._log(
                f"{self.name}: PDF generation failed for {os.path.basename(self.project_dir)}. "
                f"{pdf_error}",
                level="warning",
            )
            return build_pdf_failure_result(
                project_name=base_name,
                pdf_error=pdf_error,
                errors_report_path=errors_report_path,
                validation_summary=validation_summary,
                validation_failed=validation_failed,
            )

        new_pdf_path = os.path.join(transed_project_dir, f"{self.target_language}_{base_name}.pdf")
        shutil.move(pdf_file_path, new_pdf_path)
        print(
            format_translation_result_message(
                system_name=self.name,
                base_name=base_name,
                pdf_path=new_pdf_path,
                validation_summary=validation_summary,
                validation_failed=validation_failed,
            )
        )
        return build_workflow_result(
            project_name=base_name,
            pdf_path=new_pdf_path,
            errors_report_path=errors_report_path,
            validation_summary=validation_summary,
            validation_failed=validation_failed,
        )

    def workflow_latextrans_with_existing_terms(self) -> Dict[str, Any]:
        if hasattr(self, "loop") and not self.loop.is_closed():
            self.loop.close()
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        try:
            return self.loop.run_until_complete(self.workflow_latextrans_with_existing_terms_async())
        finally:
            if tasks := asyncio.all_tasks(self.loop):
                self.loop.run_until_complete(asyncio.gather(*tasks, return_exceptions=True))
            if sys.platform == "win32":
                self.loop.run_until_complete(self.loop.shutdown_asyncgens())
            self.loop.run_until_complete(self.loop.shutdown_default_executor())


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
