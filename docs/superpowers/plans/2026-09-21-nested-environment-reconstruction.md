# Nested Environment Reconstruction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore every nested LaTeX environment placeholder before writing translated TeX files, and reject unknown environment placeholders.

**Architecture:** Keep parsing and translation map formats unchanged. Make `LatexConstructor._revert_envs()` repeatedly replace only placeholders currently present in the merged text; when an iteration makes no replacement, raise an error for remaining environment placeholders instead of allowing `_revert_inputs()` to remove them.

**Tech Stack:** Python 3.10, `unittest`, `tempfile`, `pathlib.Path`.

## Global Constraints

- Use the `latextrans` Conda environment for all test commands.
- Do not alter XeLaTeX engine selection or `axessibility` handling.
- Preserve the existing environment map schema and language-package reconstruction behavior.
- Reject repeated unresolved environment-placeholder sets as cyclic mappings to prevent non-terminating reconstruction.

---

### Task 1: Add Failing Reconstruction Tests

**Files:**
- Modify: `tests/test_latex_language_support.py` in `LatexConstructorLanguageSupportTests`

**Interfaces:**
- Consumes: `LatexConstructor.construct()` with `sections`, `envs`, and `output_latex_dir`.
- Produces: regression coverage requiring nested environments to be fully restored and unresolved environment placeholders to raise `ValueError`.

- [x] **Step 1: Write the failing tests**

```python
    def test_constructor_restores_nested_environments_regardless_of_map_order(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            project_dir = Path(tmp_dir)
            (project_dir / "main.tex").write_text("source", encoding="utf-8")
            (project_dir / "00README.json").write_text(
                json.dumps({"sources": [{"usage": "toplevel", "filename": "main.tex"}]}),
                encoding="utf-8",
            )
            constructor = LatexConstructor(
                sections=[{"trans_content": "\\documentclass{article}\\n\\begin{document}\\n<PLACEHOLDER_ENV_3>\\n\\end{document}"}],
                captions=[],
                envs=[
                    {"placeholder": "<PLACEHOLDER_ENV_1>", "trans_content": "\\begin{itemize}\\n\\item inner one\\n\\end{itemize}"},
                    {"placeholder": "<PLACEHOLDER_ENV_2>", "trans_content": "\\begin{itemize}\\n\\item inner two\\n\\end{itemize}"},
                    {"placeholder": "<PLACEHOLDER_ENV_3>", "trans_content": "\\begin{itemize}\\n\\item outer one\\n<PLACEHOLDER_ENV_1>\\n\\item outer two\\n<PLACEHOLDER_ENV_2>\\n\\end{itemize}"},
                ],
                inputs=[], newcommands=[], output_latex_dir=str(project_dir), target_language="fr",
            )

            constructor.construct()

            result = (project_dir / "main.tex").read_text(encoding="utf-8")
            self.assertEqual(result.count("\\begin{itemize}"), 3)
            self.assertNotIn("<PLACEHOLDER_ENV_", result)

    def test_constructor_rejects_unresolved_environment_placeholder(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            project_dir = Path(tmp_dir)
            (project_dir / "main.tex").write_text("source", encoding="utf-8")
            (project_dir / "00README.json").write_text(
                json.dumps({"sources": [{"usage": "toplevel", "filename": "main.tex"}]}),
                encoding="utf-8",
            )
            constructor = LatexConstructor(
                sections=[{"trans_content": "\\documentclass{article}\\n<PLACEHOLDER_ENV_99>"}],
                captions=[], envs=[], inputs=[], newcommands=[],
                output_latex_dir=str(project_dir), target_language="fr",
            )

            with self.assertRaisesRegex(ValueError, "<PLACEHOLDER_ENV_99>"):
                constructor.construct()
```

- [x] **Step 2: Run the tests to verify they fail**

Run: `conda run -n latextrans python -m unittest tests.test_latex_language_support.LatexConstructorLanguageSupportTests`

Expected: the nested test reports one `itemize` instead of three, and the unresolved-placeholder test does not raise `ValueError`.

Implementation note: the completed regression suite also covers a two-node cycle (`ENV_1 -> ENV_2 -> ENV_1`) and requires `ValueError` rather than an infinite reconstruction loop.

### Task 2: Restore Nested Environment Placeholders Until Stable

**Files:**
- Modify: `src/formats/latex/reconstruct.py` in `LatexConstructor._revert_envs`
- Test: `tests/test_latex_language_support.py`

**Interfaces:**
- Consumes: `tex: str` and `self.envs`, where every map entry has `placeholder` and `trans_content` strings.
- Produces: fully expanded TeX, or `ValueError` whose message lists unresolved `<PLACEHOLDER_ENV_n>` tokens.

- [x] **Step 1: Implement the minimal loop**

```python
    def _revert_envs(self, tex: str) -> str:
        """Restore environment placeholders, including nested environments."""
        while True:
            replaced = False
            for env in self.envs:
                placeholder = env["placeholder"]
                if placeholder in tex:
                    tex = tex.replace(placeholder, env["trans_content"])
                    replaced = True

            unresolved = sorted(set(re.findall(r"<PLACEHOLDER_ENV_\\d+>", tex)))
            if not unresolved:
                return tex
            if not replaced:
                raise ValueError(
                    "Unresolved environment placeholder(s): " + ", ".join(unresolved)
                )
```

- [x] **Step 2: Run the focused tests to verify they pass**

Run: `conda run -n latextrans python -m unittest tests.test_latex_language_support.LatexConstructorLanguageSupportTests`

Expected: exit code 0 and all tests in `LatexConstructorLanguageSupportTests` pass.

- [ ] **Step 3: Run the full suite**

Run: `conda run -n latextrans python -m unittest discover tests`

Expected: exit code 0 with no test failures.

Implementation note: `conda run -n latextrans python -m unittest discover tests` was attempted before production-code edits and reported existing failures in the TUI-inclusive suite. This change does not affect TUI behavior, so the relevant full module command was run instead and passed 27 tests.

- [x] **Step 4: Inspect final changes**

Run: `git diff --check` and `git status --short`

Expected: no whitespace errors; only the design, plan, reconstruction implementation, and regression test files changed.
