from typing import List, Dict, Any
import re
import os
import subprocess
from pathlib import Path
from .utils import *


LATEX_HARD_ERROR_PATTERNS = [
    re.compile(r"LaTeX Error:", re.IGNORECASE),
    re.compile(r"Undefined control sequence\.", re.IGNORECASE),
    re.compile(r"Emergency stop\.", re.IGNORECASE),
    re.compile(r"Fatal error occurred", re.IGNORECASE),
    re.compile(r"can't write on file", re.IGNORECASE),
]


class LaTexCompiler:
    def __init__(self, output_latex_dir: str, target_language: str = "ch"):
        self.output_latex_dir = output_latex_dir
        self.target_language = target_language

    def compile(self):
        """
        Compile the LaTeX document.
        """
        tex_file_to_compile = find_main_tex_file(self.output_latex_dir)
        if not tex_file_to_compile:
            print("⚠️ Warning: There is no main tex file to compile in this directory.")
            return None

        self._remove_success_marker()
        attempted_log_files = []
        for engine in latex_engine_order_for_language(self.target_language):
            print(f"Start compiling with {engine}...⏳")
            compile_out_dir = os.path.join(self.output_latex_dir, f"build_{engine}")
            os.makedirs(compile_out_dir, exist_ok=True)
            self._prepare_include_output_dirs(tex_file_to_compile, compile_out_dir)
            self._compile_with_engine(engine, tex_file_to_compile, compile_out_dir)
            pdf_files = [
                os.path.join(compile_out_dir, file)
                for file in os.listdir(compile_out_dir)
                if file.lower().endswith(".pdf")
            ]
            log_files = [
                os.path.join(compile_out_dir, file)
                for file in os.listdir(compile_out_dir)
                if file.lower().endswith(".log")
            ]
            hard_error_logs = [log_file for log_file in log_files if self._log_has_hard_errors(log_file)]
            if pdf_files and not hard_error_logs:
                print("✅  Successfully generated PDF file !")
                self._write_success_marker()
                return pdf_files[0]

            if hard_error_logs:
                print(f"⚠️  LaTeX hard errors found with {engine}: {hard_error_logs}")
                self._remove_success_marker()
            print(f"⚠️  Failed to generate PDF with {engine}.")
            attempted_log_files.extend(log_files)

        if attempted_log_files:
            print(f"📄 Log files: {attempted_log_files}")
        self._remove_success_marker()
        print("⚠️  Failed to generate PDF with all configured engines. Please check the log.")
        return None

    def _log_has_hard_errors(self, log_file: str) -> bool:
        try:
            with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
        except OSError:
            return False

        return any(pattern.search(content) for pattern in LATEX_HARD_ERROR_PATTERNS)

    def _success_marker_path(self) -> str:
        return os.path.join(self.output_latex_dir, "success.txt")

    def _write_success_marker(self) -> None:
        with open(self._success_marker_path(), "w", encoding="utf-8") as f:
            f.write("Compilation successful\n")

    def _remove_success_marker(self) -> None:
        try:
            os.remove(self._success_marker_path())
        except FileNotFoundError:
            pass

    def _prepare_include_output_dirs(self, tex_file: str, out_dir: str) -> None:
        try:
            with open(tex_file, "r", encoding="utf-8", errors="ignore") as f:
                latex_code = remove_comments(f.read())
        except OSError:
            return

        for match in re.finditer(r"\\include\s*\{([^{}]+)\}", latex_code):
            include_path = Path(match.group(1))
            parent = include_path.parent
            if str(parent) in ("", "."):
                continue
            if include_path.is_absolute() or ".." in parent.parts:
                continue
            os.makedirs(os.path.join(out_dir, *parent.parts), exist_ok=True)

    def _compile_with_engine(self, engine: str, tex_file: str, out_dir: str):
        if engine == "pdflatex":
            self._compile_with_pdflatex(tex_file, out_dir, engine=engine)
        elif engine == "xelatex":
            self._compile_with_xelatex(tex_file, out_dir, engine=engine)
        elif engine == "lualatex":
            self._compile_with_lualatex(tex_file, out_dir, engine=engine)
        else:
            raise ValueError(f"Unsupported LaTeX engine: {engine}")

    def compile_ja(self):
        """
        Compile the LaTeX document .
        """
        tex_file_to_compile = find_main_tex_file(self.output_latex_dir)
        if not tex_file_to_compile:
            print("⚠️ Warning: There is no main tex file to compile in this directory.")
            return None
        print("Start compiling with lualatex...⏳")
        compile_out_dir_lualatex = os.path.join(self.output_latex_dir, "build_lualatex")
        self._compile_with_lualatex(tex_file_to_compile, compile_out_dir_lualatex, engine="lualatex")
        pdf_files = [os.path.join(compile_out_dir_lualatex, file) for file in os.listdir(compile_out_dir_lualatex) if file.lower().endswith('.pdf')]
        if pdf_files:

            print(f"✅  Successfully generated PDF file !") 
            return pdf_files[0]
        else:
            print(f"⚠️  Failed to generate PDF with xelatex. Please check the log.")
            # log_files_xelatex = [os.path.join(compile_out_dir_xelatex, file) for file in os.listdir(compile_out_dir_xelatex) if file.lower().endswith('.log')]
            log_files_lualatex = [os.path.join(compile_out_dir_lualatex, file) for file in os.listdir(compile_out_dir_lualatex) if file.lower().endswith('.log')]
            if log_files_lualatex:
                print(f"📄 Log files for pdflatex: {log_files_lualatex}")
            return None

    def compile_source(self, pdf_dir):
        if pdf_dir is None:
            pdf_dir = self.output_latex_dir
        os.makedirs(pdf_dir, exist_ok=True)  # Ensure directory exists

        tex_file_to_compile = find_main_tex_file(self.output_latex_dir)
        if not tex_file_to_compile:
            print("⚠️ Warning: No main .tex file found in directory.")
            return None

        print("Start compiling with pdflatex...⏳")
        self._compile_with_pdflatex(
            tex_file_to_compile,
            out_dir=pdf_dir,  # Output directly to pdf_dir
            engine="pdflatex"
        )

        pdf_files = [
            f for f in os.listdir(pdf_dir)
            if f.lower().endswith('.pdf') and not f.startswith('._')  # Skip macOS temp files
        ]

        if pdf_files:
            pdf_path = os.path.join(pdf_dir, pdf_files[0])
            print(f"✅ Successfully generated PDF at: {pdf_path}")
            return pdf_path

        # Fallback to xelatex if pdflatex failed
        print("⚠️ pdflatex failed. Retrying with xelatex...⏳")
        self._compile_with_xelatex(
            tex_file_to_compile,
            out_dir=pdf_dir,  # Output directly to pdf_dir
            engine="xelatex"
        )

        pdf_files = [
            f for f in os.listdir(pdf_dir)
            if f.lower().endswith('.pdf') and not f.startswith('._')
        ]

        if pdf_files:
            pdf_path = os.path.join(pdf_dir, pdf_files[0])
            print(f"✅ Successfully generated PDF at: {pdf_path}")
            return pdf_path

        # If both compilers failed
        print("⚠️ Failed to generate PDF with both compilers.")
        log_files = [f for f in os.listdir(pdf_dir) if f.lower().endswith('.log')]
        if log_files:
            print("📄 Compilation logs:")
            for log in log_files:
                print(f"  - {os.path.join(pdf_dir, log)}")

        return None

    def _compile_with_pdflatex(self,
                              tex_file: str, 
                              out_dir: str, 
                              engine: str = "pdflatex"):
        
        os.makedirs(out_dir, exist_ok=True)
        
        cmd = [
            "latexmk",
            f"-{engine}",                
            "-interaction=nonstopmode",   # no stop on errors
            f"-outdir={out_dir}",  
            f"-file-line-error",       
            f"-synctex=1",
            f"-f",                        # force mode
            tex_file
        ]
        cwd = os.path.dirname(tex_file)
        try:
            subprocess.run(cmd, check=True, capture_output=True, cwd=cwd)
            print("✅  Compilation successful!") #compile success!
                
        except subprocess.CalledProcessError as e:
            print("⚠️  Somthing went wrong during compiling with pdflatex.")

    def _compile_with_xelatex(self,
                              tex_file: str, 
                              out_dir: str, 
                              engine: str = "xelatex"):
        
        os.makedirs(out_dir, exist_ok=True)
        
        cmd = [
            "latexmk",
            f"-{engine}",                
            "-interaction=nonstopmode",   # no stop on errors
            f"-outdir={out_dir}",  
            f"-file-line-error",       
            f"-synctex=1",
            f"-f",                        # force mode
            tex_file
        ]
        cwd = os.path.dirname(tex_file)
        try:
            subprocess.run(cmd, check=True, capture_output=True, cwd=cwd)
            print("✅  Compilation successful!") #compile success!
        except subprocess.CalledProcessError as e:
            print("⚠️  Somthing went wrong during compiling with xelatex.")


    def _compile_with_lualatex(self,
                              tex_file: str, 
                              out_dir: str, 
                              engine: str = "lualatex"):
        
        os.makedirs(out_dir, exist_ok=True)
        
        cmd = [
            "latexmk",
            f"-{engine}",                
            "-interaction=nonstopmode",   # no stop on errors
            f"-outdir={out_dir}",  
            f"-file-line-error",       
            f"-synctex=1",
            f"-f",                        # force mode
            tex_file
        ]
        cwd = os.path.dirname(tex_file)
        try:
            subprocess.run(cmd, check=True, capture_output=True, cwd=cwd)
            print("✅  Compilation successful!") #compile success!
                
        except subprocess.CalledProcessError as e:
            print(f"⚠️  Somthing went wrong during compiling with lualatex. \n {e}")
