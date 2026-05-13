from typing import List, Dict, Any
import re
import os
import subprocess
from .utils import *

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

        attempted_log_files = []
        for engine in latex_engine_order_for_language(self.target_language):
            print(f"Start compiling with {engine}...⏳")
            compile_out_dir = os.path.join(self.output_latex_dir, f"build_{engine}")
            os.makedirs(compile_out_dir, exist_ok=True)
            self._compile_with_engine(engine, tex_file_to_compile, compile_out_dir)
            pdf_files = [
                os.path.join(compile_out_dir, file)
                for file in os.listdir(compile_out_dir)
                if file.lower().endswith(".pdf")
            ]
            if pdf_files:
                print("✅  Successfully generated PDF file !")
                return pdf_files[0]

            print(f"⚠️  Failed to generate PDF with {engine}.")
            attempted_log_files.extend(
                os.path.join(compile_out_dir, file)
                for file in os.listdir(compile_out_dir)
                if file.lower().endswith(".log")
            )

        if attempted_log_files:
            print(f"📄 Log files: {attempted_log_files}")
        print("⚠️  Failed to generate PDF with all configured engines. Please check the log.")
        return None

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

            output_path = os.path.join(self.output_latex_dir, "success.txt")
            with open(output_path, "w", encoding="utf-8") as f:
                f.write("Compilation successful\n")
                
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

            output_path = os.path.join(self.output_latex_dir, "success.txt")
            with open(output_path, "w", encoding="utf-8") as f:
                f.write("Compilation successful\n")
                
        except subprocess.CalledProcessError as e:
            print(f"⚠️  Somthing went wrong during compiling with lualatex. \n {e}")
