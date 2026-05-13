# LaTeX Language Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 根据 `target_language` 为中文、日文、韩文、法文选择合适的 LaTeX 语言宏包与编译引擎，移除无条件 `ctex` 注入。

**Architecture:** 在 `src/formats/latex/utils.py` 集中定义目标语言策略，`LatexConstructor` 负责在写回主 `.tex` 前应用宏包策略，`LaTexCompiler` 负责按同一语言策略选择编译顺序。`GeneratorAgent` 从已有 `config` 读取 `target_language` 并传入这两个 LaTeX 组件。

**Tech Stack:** Python 3.10+、standard library `unittest`、`unittest.mock`、现有 LaTeX helper 模块。

---

## File Structure

- Modify: `src/formats/latex/utils.py`
  - 增加语言代码归一化、目标语言宏包映射、`add_language_support_package()`、编译引擎顺序 helper。
  - 修正 `add_ja_package()` 对 `luatexja` 的重复检查。
- Modify: `src/formats/latex/reconstruct.py`
  - `LatexConstructor.__init__()` 增加 `target_language="ch"`。
  - `_revert_inputs()` 使用 `add_language_support_package()` 替代无条件 `add_ctex_package()`。
- Modify: `src/formats/latex/compile.py`
  - `LaTexCompiler.__init__()` 增加 `target_language="ch"`。
  - `compile()` 根据目标语言引擎顺序循环尝试。
- Modify: `src/agents/tool_agents/generator_agent.py`
  - 从 `self.config` 读取 `target_language` 并传给 `LatexConstructor` 和 `LaTexCompiler`。
- Create: `tests/test_latex_language_support.py`
  - 覆盖语言宏包策略、构造器写回、编译引擎顺序、GeneratorAgent 参数传递。

## Task 1: Add failing tests for package policy

**Files:**
- Create: `tests/test_latex_language_support.py`
- Test target: `src/formats/latex/utils.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_latex_language_support.py` with this initial content:

```python
import unittest

from src.formats.latex.utils import add_language_support_package


BASE_TEX = "\\documentclass{article}\n\\begin{document}\nHello\n\\end{document}\n"


class LatexLanguagePackageTests(unittest.TestCase):
    def test_chinese_targets_insert_ctex(self):
        for language in ("ch", "cn", "zh"):
            with self.subTest(language=language):
                result = add_language_support_package(BASE_TEX, language)

                self.assertIn("\\usepackage[UTF8]{ctex}", result)
                self.assertLess(
                    result.index("\\documentclass{article}"),
                    result.index("\\usepackage[UTF8]{ctex}"),
                )

    def test_japanese_targets_insert_luatexja_without_ctex(self):
        for language in ("ja", "jp"):
            with self.subTest(language=language):
                result = add_language_support_package(BASE_TEX, language)

                self.assertIn("\\usepackage{luatexja}", result)
                self.assertNotIn("\\usepackage[UTF8]{ctex}", result)

    def test_korean_target_inserts_kotex_without_ctex(self):
        result = add_language_support_package(BASE_TEX, "ko")

        self.assertIn("\\usepackage{kotex}", result)
        self.assertNotIn("\\usepackage[UTF8]{ctex}", result)

    def test_french_target_does_not_insert_cjk_packages(self):
        result = add_language_support_package(BASE_TEX, "fr")

        self.assertNotIn("\\usepackage[UTF8]{ctex}", result)
        self.assertNotIn("\\usepackage{luatexja}", result)
        self.assertNotIn("\\usepackage{kotex}", result)
        self.assertEqual(result, BASE_TEX)

    def test_unknown_target_does_not_insert_cjk_packages(self):
        result = add_language_support_package(BASE_TEX, "de")

        self.assertNotIn("\\usepackage[UTF8]{ctex}", result)
        self.assertNotIn("\\usepackage{luatexja}", result)
        self.assertNotIn("\\usepackage{kotex}", result)
        self.assertEqual(result, BASE_TEX)

    def test_existing_target_package_is_not_duplicated(self):
        tex = "\\documentclass{article}\n\\usepackage{luatexja}\n\\begin{document}\n本文\n\\end{document}\n"

        result = add_language_support_package(tex, "ja")

        self.assertEqual(result.count("\\usepackage{luatexja}"), 1)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the new test file and verify it fails**

Run:

```powershell
python -m unittest tests.test_latex_language_support
```

Expected: FAIL or ERROR because `add_language_support_package` does not exist yet.

- [ ] **Step 3: Commit the failing test**

Run:

```powershell
git add tests/test_latex_language_support.py
git commit -m "test(latex): 覆盖目标语言宏包策略"
```

## Task 2: Implement language package policy

**Files:**
- Modify: `src/formats/latex/utils.py`
- Test: `tests/test_latex_language_support.py`

- [ ] **Step 1: Add focused helpers in `utils.py`**

In `src/formats/latex/utils.py`, add these constants and helpers near the existing `add_ctex_package()` function:

```python
LANGUAGE_PACKAGE_BY_TARGET = {
    "ch": "\\usepackage[UTF8]{ctex}",
    "cn": "\\usepackage[UTF8]{ctex}",
    "zh": "\\usepackage[UTF8]{ctex}",
    "ja": "\\usepackage{luatexja}",
    "jp": "\\usepackage{luatexja}",
    "ko": "\\usepackage{kotex}",
}


def normalize_target_language(target_language):
    if target_language is None:
        return ""
    return str(target_language).strip().lower()


def add_package_after_documentclass(latex_code, package_line):
    if not package_line or package_line in latex_code:
        return latex_code

    documentclass_pattern = get_command_pattern(r"documentclass")
    match = documentclass_pattern.search(latex_code)
    if not match:
        return latex_code

    position = match.end()
    return latex_code[:position] + "\n" + package_line + "\n" + latex_code[position:]


def add_language_support_package(latex_code, target_language):
    package_line = LANGUAGE_PACKAGE_BY_TARGET.get(normalize_target_language(target_language))
    return add_package_after_documentclass(latex_code, package_line)
```

- [ ] **Step 2: Refactor existing package helpers to use the shared inserter**

Replace the bodies of `add_ctex_package()` and `add_ja_package()` with:

```python
def add_ctex_package(latex_code):
    return add_package_after_documentclass(latex_code, "\\usepackage[UTF8]{ctex}")


def add_ja_package(latex_code):
    return add_package_after_documentclass(latex_code, "\\usepackage{luatexja}")
```

This keeps existing public helpers available while fixing the `luatex-ja` versus `luatexja` mismatch.

- [ ] **Step 3: Run package policy tests**

Run:

```powershell
python -m unittest tests.test_latex_language_support
```

Expected: PASS for `LatexLanguagePackageTests`.

- [ ] **Step 4: Commit the implementation**

Run:

```powershell
git add src/formats/latex/utils.py
git commit -m "fix(latex): 按目标语言注入宏包"
```

## Task 3: Add failing tests for constructor package application

**Files:**
- Modify: `tests/test_latex_language_support.py`
- Test target: `src/formats/latex/reconstruct.py`

- [ ] **Step 1: Extend the test file with constructor integration tests**

Append these imports and test class to `tests/test_latex_language_support.py`:

```python
import json
import tempfile
from pathlib import Path

from src.formats.latex.reconstruct import LatexConstructor
```

Add this class below `LatexLanguagePackageTests`:

```python
class LatexConstructorLanguageSupportTests(unittest.TestCase):
    def _construct_project(self, target_language):
        with tempfile.TemporaryDirectory() as tmp_dir:
            project_dir = Path(tmp_dir)
            main_tex = project_dir / "main.tex"
            main_tex.write_text(
                "\\documentclass{article}\n\\begin{document}\nOriginal\n\\end{document}\n",
                encoding="utf-8",
            )
            (project_dir / "00README.json").write_text(
                json.dumps({"sources": [{"usage": "toplevel", "filename": "main.tex"}]}),
                encoding="utf-8",
            )

            constructor = LatexConstructor(
                sections=[
                    {
                        "trans_content": "\\documentclass{article}\n\\begin{document}\n本文\n\\end{document}"
                    }
                ],
                captions=[],
                envs=[],
                inputs=[],
                newcommands=[],
                output_latex_dir=str(project_dir),
                target_language=target_language,
            )
            constructor.construct()

            return main_tex.read_text(encoding="utf-8")

    def test_constructor_uses_japanese_package_without_ctex(self):
        result = self._construct_project("ja")

        self.assertIn("\\usepackage{luatexja}", result)
        self.assertNotIn("\\usepackage[UTF8]{ctex}", result)

    def test_constructor_does_not_add_cjk_package_for_french(self):
        result = self._construct_project("fr")

        self.assertNotIn("\\usepackage[UTF8]{ctex}", result)
        self.assertNotIn("\\usepackage{luatexja}", result)
        self.assertNotIn("\\usepackage{kotex}", result)
```

If the imports are already present after earlier edits, keep one copy only.

- [ ] **Step 2: Run constructor tests and verify they fail**

Run:

```powershell
python -m unittest tests.test_latex_language_support.LatexConstructorLanguageSupportTests
```

Expected: ERROR because `LatexConstructor.__init__()` does not accept `target_language`, or FAIL because it still inserts `ctex`.

- [ ] **Step 3: Commit the failing constructor tests**

Run:

```powershell
git add tests/test_latex_language_support.py
git commit -m "test(latex): 覆盖构造器目标语言宏包"
```

## Task 4: Wire package policy into LatexConstructor

**Files:**
- Modify: `src/formats/latex/reconstruct.py`
- Test: `tests/test_latex_language_support.py`

- [ ] **Step 1: Add `target_language` to `LatexConstructor`**

In `src/formats/latex/reconstruct.py`, change the constructor signature and assignments to include:

```python
                 output_latex_dir: str,
                 target_language: str = "ch"
                 ):
```

and:

```python
        self.target_language = target_language
```

- [ ] **Step 2: Replace unconditional ctex injection**

Replace:

```python
        tex = add_ctex_package(tex) # zh
        # tex = add_ja_package(tex)  # ja
```

with:

```python
        tex = add_language_support_package(tex, self.target_language)
```

- [ ] **Step 3: Run constructor tests**

Run:

```powershell
python -m unittest tests.test_latex_language_support.LatexConstructorLanguageSupportTests
```

Expected: PASS.

- [ ] **Step 4: Run all language support tests**

Run:

```powershell
python -m unittest tests.test_latex_language_support
```

Expected: PASS.

- [ ] **Step 5: Commit constructor wiring**

Run:

```powershell
git add src/formats/latex/reconstruct.py
git commit -m "fix(latex): 构造器按目标语言应用宏包"
```

## Task 5: Add failing tests for compiler engine order

**Files:**
- Modify: `tests/test_latex_language_support.py`
- Test target: `src/formats/latex/compile.py` and `src/formats/latex/utils.py`

- [ ] **Step 1: Add engine order tests**

Add this import:

```python
from unittest.mock import patch

from src.formats.latex.compile import LaTexCompiler
from src.formats.latex.utils import latex_engine_order_for_language
```

Add this class:

```python
class LatexCompilerLanguageTests(unittest.TestCase):
    def test_engine_order_for_supported_languages(self):
        self.assertEqual(latex_engine_order_for_language("ch"), ["xelatex", "pdflatex"])
        self.assertEqual(latex_engine_order_for_language("zh"), ["xelatex", "pdflatex"])
        self.assertEqual(latex_engine_order_for_language("ja"), ["lualatex", "xelatex"])
        self.assertEqual(latex_engine_order_for_language("jp"), ["lualatex", "xelatex"])
        self.assertEqual(latex_engine_order_for_language("ko"), ["xelatex", "pdflatex"])
        self.assertEqual(latex_engine_order_for_language("fr"), ["pdflatex", "xelatex"])
        self.assertEqual(latex_engine_order_for_language("de"), ["pdflatex", "xelatex"])

    def test_compile_uses_target_language_engine_order(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            project_dir = Path(tmp_dir)
            (project_dir / "main.tex").write_text(
                "\\documentclass{article}\n\\begin{document}\n本文\n\\end{document}\n",
                encoding="utf-8",
            )

            calls = []

            def fake_compile(tex_file, out_dir, engine):
                calls.append((engine, Path(out_dir).name))
                if engine == "lualatex":
                    (Path(out_dir) / "main.pdf").write_bytes(b"%PDF")

            compiler = LaTexCompiler(str(project_dir), target_language="ja")

            with patch.object(compiler, "_compile_with_lualatex", side_effect=fake_compile), \
                    patch.object(compiler, "_compile_with_xelatex", side_effect=fake_compile), \
                    patch.object(compiler, "_compile_with_pdflatex", side_effect=fake_compile), \
                    patch("builtins.print"):
                pdf_path = compiler.compile()

        self.assertEqual(calls, [("lualatex", "build_lualatex")])
        self.assertTrue(pdf_path.endswith("main.pdf"))

    def test_compile_falls_back_to_next_language_engine(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            project_dir = Path(tmp_dir)
            (project_dir / "main.tex").write_text(
                "\\documentclass{article}\n\\begin{document}\n本文\n\\end{document}\n",
                encoding="utf-8",
            )

            calls = []

            def fake_compile(tex_file, out_dir, engine):
                calls.append((engine, Path(out_dir).name))
                if engine == "xelatex":
                    (Path(out_dir) / "main.pdf").write_bytes(b"%PDF")

            compiler = LaTexCompiler(str(project_dir), target_language="ja")

            with patch.object(compiler, "_compile_with_lualatex", side_effect=fake_compile), \
                    patch.object(compiler, "_compile_with_xelatex", side_effect=fake_compile), \
                    patch.object(compiler, "_compile_with_pdflatex", side_effect=fake_compile), \
                    patch("builtins.print"):
                pdf_path = compiler.compile()

        self.assertEqual(
            calls,
            [("lualatex", "build_lualatex"), ("xelatex", "build_xelatex")],
        )
        self.assertTrue(pdf_path.endswith("main.pdf"))
```

If `tempfile`, `Path`, or `patch` were already imported for constructor tests, keep one import only.

- [ ] **Step 2: Run compiler tests and verify they fail**

Run:

```powershell
python -m unittest tests.test_latex_language_support.LatexCompilerLanguageTests
```

Expected: ERROR because `latex_engine_order_for_language` does not exist, or ERROR because `LaTexCompiler.__init__()` does not accept `target_language`.

- [ ] **Step 3: Commit the failing compiler tests**

Run:

```powershell
git add tests/test_latex_language_support.py
git commit -m "test(latex): 覆盖目标语言编译顺序"
```

## Task 6: Implement compiler engine policy

**Files:**
- Modify: `src/formats/latex/utils.py`
- Modify: `src/formats/latex/compile.py`
- Test: `tests/test_latex_language_support.py`

- [ ] **Step 1: Add engine order helper in `utils.py`**

In `src/formats/latex/utils.py`, add:

```python
ENGINE_ORDER_BY_TARGET = {
    "ch": ["xelatex", "pdflatex"],
    "cn": ["xelatex", "pdflatex"],
    "zh": ["xelatex", "pdflatex"],
    "ja": ["lualatex", "xelatex"],
    "jp": ["lualatex", "xelatex"],
    "ko": ["xelatex", "pdflatex"],
    "fr": ["pdflatex", "xelatex"],
}


def latex_engine_order_for_language(target_language):
    return ENGINE_ORDER_BY_TARGET.get(
        normalize_target_language(target_language),
        ["pdflatex", "xelatex"],
    )
```

- [ ] **Step 2: Update `LaTexCompiler.__init__()`**

In `src/formats/latex/compile.py`, change:

```python
    def __init__(self, output_latex_dir: str):
        self.output_latex_dir = output_latex_dir
```

to:

```python
    def __init__(self, output_latex_dir: str, target_language: str = "ch"):
        self.output_latex_dir = output_latex_dir
        self.target_language = target_language
```

- [ ] **Step 3: Replace `compile()` with loop-based fallback**

Replace the current `compile()` body with:

```python
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
```

Add this helper method inside `LaTexCompiler`:

```python
    def _compile_with_engine(self, engine: str, tex_file: str, out_dir: str):
        if engine == "pdflatex":
            self._compile_with_pdflatex(tex_file, out_dir, engine=engine)
        elif engine == "xelatex":
            self._compile_with_xelatex(tex_file, out_dir, engine=engine)
        elif engine == "lualatex":
            self._compile_with_lualatex(tex_file, out_dir, engine=engine)
        else:
            raise ValueError(f"Unsupported LaTeX engine: {engine}")
```

- [ ] **Step 4: Run compiler tests**

Run:

```powershell
python -m unittest tests.test_latex_language_support.LatexCompilerLanguageTests
```

Expected: PASS.

- [ ] **Step 5: Run all language support tests**

Run:

```powershell
python -m unittest tests.test_latex_language_support
```

Expected: PASS.

- [ ] **Step 6: Commit compiler policy**

Run:

```powershell
git add src/formats/latex/utils.py src/formats/latex/compile.py
git commit -m "fix(latex): 按目标语言选择编译引擎"
```

## Task 7: Add failing test for GeneratorAgent language propagation

**Files:**
- Modify: `tests/test_latex_language_support.py`
- Test target: `src/agents/tool_agents/generator_agent.py`

- [ ] **Step 1: Add GeneratorAgent propagation test**

Add this import:

```python
from src.agents.tool_agents.generator_agent import GeneratorAgent
```

Add this class:

```python
class GeneratorAgentLanguagePropagationTests(unittest.TestCase):
    def test_generator_passes_target_language_to_constructor_and_compiler(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            source_dir = root / "paper"
            source_dir.mkdir()
            (source_dir / "main.tex").write_text(
                "\\documentclass{article}\n\\begin{document}\nOriginal\n\\end{document}\n",
                encoding="utf-8",
            )

            output_dir = root / "output"
            output_dir.mkdir()
            for filename, data in {
                "sections_map.json": [{"trans_content": "\\documentclass{article}\n\\begin{document}\n本文\n\\end{document}"}],
                "captions_map.json": [],
                "envs_map.json": [],
                "newcommands_map.json": [],
                "inputs_map.json": [],
            }.items():
                (output_dir / filename).write_text(json.dumps(data), encoding="utf-8")

            constructor_languages = []
            compiler_languages = []

            class FakeConstructor:
                def __init__(self, **kwargs):
                    constructor_languages.append(kwargs["target_language"])

                def construct(self):
                    return None

            class FakeCompiler:
                def __init__(self, output_latex_dir, target_language):
                    compiler_languages.append(target_language)

                def compile(self):
                    return str(root / "paper.pdf")

            with patch("src.formats.latex.reconstruct.LatexConstructor", FakeConstructor), \
                    patch("src.formats.latex.compile.LaTexCompiler", FakeCompiler), \
                    patch("src.agents.tool_agents.generator_agent.st"), \
                    patch("time.sleep"), \
                    patch("builtins.print"):
                agent = GeneratorAgent(
                    config={"target_language": "ja"},
                    project_dir=str(source_dir),
                    output_dir=str(output_dir),
                )
                result = agent.execute()

        self.assertEqual(result, str(root / "paper.pdf"))
        self.assertEqual(constructor_languages, ["ja"])
        self.assertEqual(compiler_languages, ["ja"])
```

- [ ] **Step 2: Run propagation test and verify it fails**

Run:

```powershell
python -m unittest tests.test_latex_language_support.GeneratorAgentLanguagePropagationTests
```

Expected: FAIL or ERROR because `GeneratorAgent` does not pass `target_language` to `LatexConstructor` and `LaTexCompiler`.

- [ ] **Step 3: Commit the failing propagation test**

Run:

```powershell
git add tests/test_latex_language_support.py
git commit -m "test(agent): 覆盖生成器目标语言传递"
```

## Task 8: Pass target language through GeneratorAgent

**Files:**
- Modify: `src/agents/tool_agents/generator_agent.py`
- Test: `tests/test_latex_language_support.py`

- [ ] **Step 1: Read target language once in `execute()`**

In `GeneratorAgent.execute()`, before constructing `LatexConstructor`, add:

```python
        target_language = self.config.get("target_language", "ch")
```

- [ ] **Step 2: Pass language into `LatexConstructor`**

Change the constructor call to include:

```python
                                output_latex_dir=transed_latex_dir,
                                target_language=target_language
```

- [ ] **Step 3: Pass language into `LaTexCompiler`**

Change:

```python
        latex_compiler = LaTexCompiler(output_latex_dir=transed_latex_dir)
```

to:

```python
        latex_compiler = LaTexCompiler(
            output_latex_dir=transed_latex_dir,
            target_language=target_language,
        )
```

- [ ] **Step 4: Run propagation test**

Run:

```powershell
python -m unittest tests.test_latex_language_support.GeneratorAgentLanguagePropagationTests
```

Expected: PASS.

- [ ] **Step 5: Run all language support tests**

Run:

```powershell
python -m unittest tests.test_latex_language_support
```

Expected: PASS.

- [ ] **Step 6: Commit generator wiring**

Run:

```powershell
git add src/agents/tool_agents/generator_agent.py
git commit -m "fix(agent): 传递目标语言到 LaTeX 生成流程"
```

## Task 9: Final verification and cleanup

**Files:**
- Verify all modified files.

- [ ] **Step 1: Inspect working tree**

Run:

```powershell
git status --short
```

Expected: no uncommitted changes, or only expected task-related changes if commits were intentionally deferred.

- [ ] **Step 2: Run targeted language support suite**

Run:

```powershell
python -m unittest tests.test_latex_language_support
```

Expected: all tests pass.

- [ ] **Step 3: Run full unit test suite**

Run:

```powershell
python -m unittest discover tests
```

Expected: all tests pass.

- [ ] **Step 4: Review final diff if commits were deferred**

Run:

```powershell
git diff --stat
git diff -- src/formats/latex/utils.py src/formats/latex/reconstruct.py src/formats/latex/compile.py src/agents/tool_agents/generator_agent.py tests/test_latex_language_support.py
```

Expected: diff only contains target-language package policy, compiler engine order, GeneratorAgent propagation, and tests.

- [ ] **Step 5: Commit remaining changes if any**

If `git status --short` shows remaining task-related changes, run:

```powershell
git add src/formats/latex/utils.py src/formats/latex/reconstruct.py src/formats/latex/compile.py src/agents/tool_agents/generator_agent.py tests/test_latex_language_support.py
git commit -m "fix(latex): 完成目标语言支持策略"
```

Expected: commit succeeds and `git status --short` is clean.

## Self-Review

- Spec coverage: Tasks 1-4 cover language package injection and removal of unconditional `ctex`; Tasks 5-6 cover language-specific engine order; Tasks 7-8 cover `GeneratorAgent` data flow; Task 9 covers full verification.
- Scope check: The plan covers only Chinese, Japanese, Korean, French, and default behavior for other languages. RTL and Russian support remain outside this implementation.
- Type consistency: `target_language` is passed as `str`; `LatexConstructor` and `LaTexCompiler` both default to `"ch"`; helper names are consistently `add_language_support_package()`, `normalize_target_language()`, and `latex_engine_order_for_language()`.
