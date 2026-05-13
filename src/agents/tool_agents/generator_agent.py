from typing import Dict, Any, List
from src.agents.tool_agents.base_tool_agent import BaseToolAgent
from pathlib import Path
from contextlib import contextmanager
import sys
import os
import shutil

from src.utils.progress import st
import time

base_dir = os.getcwd()
sys.path.append(base_dir)


@contextmanager
def _suppress_stderr():
    previous_stderr = sys.stderr
    with open(os.devnull, "w", encoding="utf-8") as devnull:
        sys.stderr = devnull
        try:
            yield
        finally:
            sys.stderr = previous_stderr

 
class GeneratorAgent(BaseToolAgent):
    def __init__(self, 
                 config: Dict[str, Any],
                 project_dir: str = None,
                 output_dir: str = None  # Output directory for parsed files
                 ):
        super().__init__(agent_name="GeneratorAgent", config=config)
        self.config = config
        self.project_dir = project_dir
        self.output_dir = output_dir  # Output directory for parsed files

    def execute(self) -> Any:
        with _suppress_stderr():
            self.process_b = st.empty()
            with self.process_b:
                self.progress_bar = st.progress(0)
            self.status_text = st.empty()
        
        self.log(f"🤖💬 Start generating for project...⏳: {os.path.basename(self.project_dir)}.")

        with _suppress_stderr():
            self.status_text.text("🔄 Start generating for project...")
            self.progress_bar.progress(5)

        from src.formats.latex.compile import LaTexCompiler
        from src.formats.latex.reconstruct import LatexConstructor
        target_language = self.config.get("target_language", "ch")

        with _suppress_stderr():
            self.status_text.text("📂 Reading...")
            self.progress_bar.progress(10)
        sections = self.read_file(Path(self.output_dir, "sections_map.json"), "json")
        with _suppress_stderr():
            self.progress_bar.progress(20)
        captions = self.read_file(Path(self.output_dir, "captions_map.json"), "json")
        with _suppress_stderr():
            self.progress_bar.progress(30)
        envs = self.read_file(Path(self.output_dir, "envs_map.json"), "json")
        with _suppress_stderr():
            self.progress_bar.progress(40)
        newcommands = self.read_file(Path(self.output_dir, "newcommands_map.json"), "json")
        with _suppress_stderr():
            self.progress_bar.progress(50)
        inputs = self.read_file(Path(self.output_dir, "inputs_map.json"), "json")
        with _suppress_stderr():
            self.progress_bar.progress(60)
            self.status_text.text("📁 Creating translation project directory ..")

        transed_latex_dir = self._creat_transed_latex_folder(self.project_dir)

        with _suppress_stderr():
            self.progress_bar.progress(70)

        print(transed_latex_dir)

        with _suppress_stderr():
            self.status_text.text("🔨 Refactoring LaTeX document...")
        latex_constructor = LatexConstructor(
                                sections=sections,
                                captions=captions,
                                envs=envs,
                                inputs=inputs,
                                newcommands=newcommands,
                                output_latex_dir=transed_latex_dir,
                                target_language=target_language
        )
        latex_constructor.construct()

        with _suppress_stderr():
            self.progress_bar.progress(80)
            self.status_text.text("🛠️ Compiling PDF document...")

        latex_compiler = LaTexCompiler(
            output_latex_dir=transed_latex_dir,
            target_language=target_language,
        )
        pdf_file = latex_compiler.compile()

        with _suppress_stderr():
            self.progress_bar.progress(90)
        if pdf_file:

            with _suppress_stderr():
                self.status_text.text("✅ Successfully compiled PDF document.")
                self.progress_bar.progress(100)
                st.success(f"✅ Successfully generated for {os.path.basename(self.project_dir)}.")
                time.sleep(2)
                self.process_b.empty()
                self.status_text.empty()

            self.log(f"✅ Successfully generated for {os.path.basename(self.project_dir)}.")
            return pdf_file
        else:
            with _suppress_stderr():
                self.status_text.error("❌ Failed to compile PDF document.")
                self.process_b.empty()
            return None
        
    def _creat_transed_latex_folder(self, src_dir: str) -> str:
        """
        Create a translated folder by copying the source directory and renaming it.
        """
        if not os.path.isdir(src_dir):
            raise NotADirectoryError(f"The path {src_dir} is not a valid directory.")

        base_name = os.path.basename(src_dir)
        dest_dir = os.path.join(self.output_dir, base_name)

        if os.path.exists(dest_dir):
            shutil.rmtree(dest_dir)
        shutil.copytree(src_dir, dest_dir)

        return dest_dir
        
    


# import toml
# import argparse

# parser = argparse.ArgumentParser()
# parser.add_argument("--config", type=str, default="config/default.toml")
# args = parser.parse_args()

# config = toml.load(args.config)
# dir = "D:\code\AutoLaTexTrans\output\ch_arXiv-2504.06261v2/arXiv-2504.06261v2"
# Validator = ValidatorAgent(config=config,
#                           project_dir=config["paths"].get("project_dir", None),
#                           validator_dir=dir
#                           )
# Validator.execute()
