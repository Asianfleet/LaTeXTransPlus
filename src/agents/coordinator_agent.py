import os
import shutil
from typing import Any, Dict, List, Optional
from pathlib import Path
import sys
import asyncio

base_dir = os.getcwd()
sys.path.append(base_dir)

from .tool_agents.base_tool_agent import BaseToolAgent
from .tool_agents.parser_agent import ParserAgent
from .tool_agents.translator_agent import TranslatorAgent 
from .tool_agents.generator_agent import GeneratorAgent
from .tool_agents.validator_agent import ValidatorAgent
import gc


def format_translation_result_message(
    system_name: str,
    base_name: str,
    pdf_path: str,
    validation_error_count: int = 0,
) -> str:
    if validation_error_count:
        errors_report_path = os.path.join(os.path.dirname(pdf_path), "errors_report.json")
        return (
            f"🤖⚠️ {system_name}: PDF generated with validation warnings for {base_name}; "
            f"remaining validation errors: {validation_error_count}. "
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
        self.mode = config.get("mode", 0)

    def run_async(self, coro):
        """
        Run asynchronous coroutines in the existing event loop
        """
        return self.loop.run_until_complete(coro)

    async def workflow_latextrans_async(self) -> None:
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
        MAX_RETRIES = 3
        retry_count = 0
        if errors_report:
            translator_agent.trans_mode = 1

        while errors_report and retry_count < MAX_RETRIES: # 3 times
            translator_agent.errors_report = errors_report
            await translator_agent.execute(error_retry_count=retry_count, Maxtry=MAX_RETRIES)
            errors_report = validator_agent.execute(errors_report)
            retry_count += 1

        validation_error_count = len(errors_report) if errors_report else 0

        generator_agent = GeneratorAgent(config=self.config,
                                         project_dir=self.project_dir,
                                         output_dir=transed_project_dir)
        try:
        
            PDF_file_path = generator_agent.execute()
        except Exception as e:
            print(f"🤖🚧 {self.name}: Failed to translated {os.path.basename(self.project_dir)}.{e}")
            return
        
        if PDF_file_path:
            new_PDF_path = os.path.join(transed_project_dir, f"{self.target_language}_{base_name}.pdf")
            shutil.move(PDF_file_path, new_PDF_path)
            print(
                format_translation_result_message(
                    system_name=self.name,
                    base_name=os.path.basename(self.project_dir),
                    pdf_path=new_PDF_path,
                    validation_error_count=validation_error_count,
                )
            )
        else:
            print(f"🤖🚧 {self.name}: Failed to translated {os.path.basename(self.project_dir)}.")


    def workflow_latextrans(self) -> None:
        """
        Initialize the tool agent and execute the LaTeX conversion workflow 
        (with event loop security management)
        """

        if hasattr(self, 'loop') and not self.loop.is_closed():
            self.loop.close()  

        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)

        try:
            self.loop.run_until_complete(self.workflow_latextrans_async())

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
