from typing import Any, Callable, Dict, List
import re
import os
import subprocess
from pathlib import Path
from .utils import *


# 日志中可能出现的错误行，用于把整段日志逐条切分成候选错误
LATEX_ERROR_LINE_PATTERNS = [
    re.compile(r"LaTeX Error:", re.IGNORECASE),
    re.compile(r"Undefined control sequence\.", re.IGNORECASE),
    re.compile(r"Emergency stop\.", re.IGNORECASE),
    re.compile(r"Fatal error occurred", re.IGNORECASE),
    re.compile(r"can't write on file", re.IGNORECASE),
]

# LaTeX 会自行忽略、且不影响 PDF 产出的错误；命中时只记警告，不判失败
LATEX_RECOVERABLE_ERROR_PATTERNS = [
    # 例：源文件里的 \newcommand{\theHalgorithm} 与新版 hyperref 重复定义
    re.compile(r"LaTeX Error: Command \\[^\s]+ already defined", re.IGNORECASE),
    # 译文丢失命令导致的未定义控制序列，LaTeX 跳过该命令继续排版
    re.compile(r"Undefined control sequence\.", re.IGNORECASE),
]


class LaTexCompiler:
    def __init__(
        self,
        output_latex_dir: str,
        target_language: str = "ch",
        log_callback: Callable[[Dict[str, Any]], None] | None = None,
        emit_console: bool = True,
    ):
        self.output_latex_dir = output_latex_dir
        self.target_language = target_language
        self.log_callback = log_callback
        self.emit_console = emit_console

    def _log(self, message: str, level: str = "info") -> None:
        """将编译状态写入显式日志回调，并按需保留终端输出。"""
        if self.log_callback is not None:
            self.log_callback(
                {
                    "agent_name": "LaTexCompiler",
                    "level": level,
                    "message": message,
                    "line": message,
                }
            )
        if self.emit_console or self.log_callback is None:
            print(message)

    def compile(self):
        """
        Compile the LaTeX document.
        """
        tex_file_to_compile = find_main_tex_file(self.output_latex_dir)
        if not tex_file_to_compile:
            self._log("⚠️ Warning: There is no main tex file to compile in this directory.", "warning")
            return None

        self._remove_success_marker()
        attempted_log_files = []
        for engine in latex_engine_order_for_language(self.target_language):
            self._log(f"Start compiling with {engine}...⏳")
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
                self._log("✅  Successfully generated PDF file !")
                self._write_success_marker()
                return pdf_files[0]

            if hard_error_logs:
                self._log(f"⚠️  LaTeX hard errors found with {engine}: {hard_error_logs}", "warning")
                self._remove_success_marker()
            self._log(f"⚠️  Failed to generate PDF with {engine}.", "warning")
            attempted_log_files.extend(log_files)

        if attempted_log_files:
            self._log(f"📄 Log files: {attempted_log_files}")
        self._remove_success_marker()
        self._log("⚠️  Failed to generate PDF with all configured engines. Please check the log.", "warning")
        return None

    def _log_error_lines(self, log_file: str) -> List[str]:
        """读取编译日志中的错误行，供致命/可恢复判定复用。"""
        try:
            with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
        except OSError:
            return []

        return [
            line.strip()
            for line in content.splitlines()
            if any(pattern.search(line) for pattern in LATEX_ERROR_LINE_PATTERNS)
        ]

    def _log_has_hard_errors(self, log_file: str) -> bool:
        """判断日志是否包含真正阻断 PDF 产出的致命错误。

        命中 ``LATEX_RECOVERABLE_ERROR_PATTERNS`` 的错误由 LaTeX 自行忽略，
        产物仍然完整，因此只记警告而不判失败。
        """
        for line in self._log_error_lines(log_file):
            if any(pattern.search(line) for pattern in LATEX_RECOVERABLE_ERROR_PATTERNS):
                self._log(f"⚠️  可恢复的 LaTeX 错误（已忽略）：{line}", "warning")
                continue
            return True
        return False

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
        """沿源码引用链准备 include 的辅助目录，避免循环扫描和路径越界。"""
        project_root = Path(tex_file).resolve().parent
        pending = [Path(tex_file).resolve()]
        visited = set()
        while pending:
            source = pending.pop()
            if source in visited:
                continue
            visited.add(source)
            try:
                latex_code = remove_comments(source.read_text(encoding="utf-8", errors="ignore"))
            except OSError:
                continue

            for match in re.finditer(r"\\(input|include)\s*\{([^{}]+)\}", latex_code):
                relative_path = Path(match.group(2).strip())
                if relative_path.is_absolute() or ".." in relative_path.parts:
                    continue
                # 标准 input/include 路径相对于编译工作目录，而非当前子文件。
                referenced = project_root / relative_path
                if not referenced.is_file():
                    referenced = Path(str(referenced) + ".tex")
                referenced = referenced.resolve()
                if not referenced.is_relative_to(project_root):
                    continue
                if match.group(1) == "include":
                    (Path(out_dir) / relative_path.parent).mkdir(parents=True, exist_ok=True)
                pending.append(referenced)

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
            self._log("⚠️ Warning: There is no main tex file to compile in this directory.", "warning")
            return None
        self._log("Start compiling with lualatex...⏳")
        compile_out_dir_lualatex = os.path.join(self.output_latex_dir, "build_lualatex")
        self._compile_with_lualatex(tex_file_to_compile, compile_out_dir_lualatex, engine="lualatex")
        pdf_files = [os.path.join(compile_out_dir_lualatex, file) for file in os.listdir(compile_out_dir_lualatex) if file.lower().endswith('.pdf')]
        if pdf_files:

            self._log("✅  Successfully generated PDF file !")
            return pdf_files[0]
        else:
            self._log("⚠️  Failed to generate PDF with xelatex. Please check the log.", "warning")
            # log_files_xelatex = [os.path.join(compile_out_dir_xelatex, file) for file in os.listdir(compile_out_dir_xelatex) if file.lower().endswith('.log')]
            log_files_lualatex = [os.path.join(compile_out_dir_lualatex, file) for file in os.listdir(compile_out_dir_lualatex) if file.lower().endswith('.log')]
            if log_files_lualatex:
                self._log(f"📄 Log files for pdflatex: {log_files_lualatex}")
            return None

    def compile_source(self, pdf_dir):
        if pdf_dir is None:
            pdf_dir = self.output_latex_dir
        os.makedirs(pdf_dir, exist_ok=True)  # Ensure directory exists

        tex_file_to_compile = find_main_tex_file(self.output_latex_dir)
        if not tex_file_to_compile:
            self._log("⚠️ Warning: No main .tex file found in directory.", "warning")
            return None

        self._log("Start compiling with pdflatex...⏳")
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
            self._log(f"✅ Successfully generated PDF at: {pdf_path}")
            return pdf_path

        # Fallback to xelatex if pdflatex failed
        self._log("⚠️ pdflatex failed. Retrying with xelatex...⏳", "warning")
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
            self._log(f"✅ Successfully generated PDF at: {pdf_path}")
            return pdf_path

        # If both compilers failed
        self._log("⚠️ Failed to generate PDF with both compilers.", "warning")
        log_files = [f for f in os.listdir(pdf_dir) if f.lower().endswith('.log')]
        if log_files:
            self._log("📄 Compilation logs:")
            for log in log_files:
                self._log(f"  - {os.path.join(pdf_dir, log)}")

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
            self._log("✅  Compilation successful!") #compile success!
                
        except subprocess.CalledProcessError as e:
            self._log("⚠️  Somthing went wrong during compiling with pdflatex.", "warning")

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
            self._log("✅  Compilation successful!") #compile success!
        except subprocess.CalledProcessError as e:
            self._log("⚠️  Somthing went wrong during compiling with xelatex.", "warning")


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
            self._log("✅  Compilation successful!") #compile success!
                
        except subprocess.CalledProcessError as e:
            self._log(f"⚠️  Somthing went wrong during compiling with lualatex. \n {e}", "warning")
