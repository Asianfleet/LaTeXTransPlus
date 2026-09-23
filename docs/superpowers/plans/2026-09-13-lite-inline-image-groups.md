# Lite Inline Image Groups Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Group consecutive standalone Markdown images in lite translations into rows of at most three images for compact Pandoc PDF layout.

**Architecture:** Add a pure Markdown post-processing helper in `lite_markdown.py`. Invoke it in `MarkdownTranslatorAgent.execute` after block rebuilding and before atomic output. Keep source Markdown and translation prompts unchanged.

**Tech Stack:** Python 3.10+, standard `re`, `unittest`, Markdown/Pandoc image attributes.

## Global Constraints

- Only standalone image lines are grouped; prose, headings, blank lines, and trailing content terminate runs.
- Alt text and destination are preserved exactly.
- Each grouped output row contains no more than three images and uses `width=0.32\\linewidth`; isolated images remain unchanged.
- Use UTF-8 and existing `unittest` conventions.

### Task 1: Add the failing grouping tests

**Files:**
- Modify: `tests/test_lite_markdown.py`

**Interfaces:**
- Test the future `group_standalone_images(text: str, max_per_row: int = 3) -> str` helper.

- [x] **Step 1: Write tests for grouping and boundaries**

Add a `MarkdownImageGroupingTests` class covering one image, three images, four images as two rows, boundary termination, and preservation of alt/path text.

- [x] **Step 2: Run the focused tests and verify failure**

Run: `python -m unittest tests.test_lite_markdown.MarkdownImageGroupingTests`

Expected: import failure because `group_standalone_images` does not yet exist.

### Task 2: Implement the pure helper

**Files:**
- Modify: `src/engines/lite_markdown.py`

**Interfaces:**
- Produce `group_standalone_images(text: str, max_per_row: int = 3) -> str`.

- [x] **Step 1: Implement standalone image matching and row emission**

Use a line matcher for `![alt](destination)` with optional whitespace, collect adjacent matches, append `{width=0.32\\linewidth}` to each image in a grouped row, split rows at `max_per_row`, and preserve all non-image lines via `splitlines(keepends=True)`.

- [x] **Step 2: Run focused tests and verify pass**

Run: `python -m unittest tests.test_lite_markdown.MarkdownImageGroupingTests`

Expected: all grouping tests pass.

### Task 3: Integrate before translated Markdown is written

**Files:**
- Modify: `src/agents/tool_agents/markdown_translator_agent.py`
- Modify: `tests/test_markdown_translator_agent.py`

**Interfaces:**
- Consume `group_standalone_images` from `src.engines.lite_markdown`.

- [x] **Step 1: Add an integration assertion**

Extend the existing injected-translation execution test so the generated `translated.md` contains a three-image row with width attributes when the source has consecutive standalone images.

- [x] **Step 2: Run the integration test and verify failure**

Run: `python -m unittest tests.test_markdown_translator_agent`

Expected: the new assertion fails because the agent currently writes rebuilt Markdown unchanged.

- [x] **Step 3: Call the helper before the temporary write**

Import `group_standalone_images` and transform `rebuild_markdown(translated_blocks)` before `temporary_path.write_text(...)`.

- [x] **Step 4: Run the integration test and verify pass**

Run: `python -m unittest tests.test_markdown_translator_agent`

Expected: all translator-agent tests pass.

### Task 4: Full verification and diff hygiene

**Files:**
- Verify: `src/engines/lite_markdown.py`
- Verify: `src/agents/tool_agents/markdown_translator_agent.py`
- Verify: `tests/test_lite_markdown.py`
- Verify: `tests/test_markdown_translator_agent.py`

- [x] **Step 1: Run the complete test suite**

Run: `python -m unittest discover tests`

Expected: exit code 0 with no failures.

- [x] **Step 2: Inspect final diff**

Run: `git diff --check` and `git status --short`.

Expected: no whitespace errors and only the planned source, test, and plan files changed.

- [x] **Step 3: Commit implementation**

Run: `git add src/engines/lite_markdown.py src/agents/tool_agents/markdown_translator_agent.py tests/test_lite_markdown.py tests/test_markdown_translator_agent.py docs/superpowers/plans/2026-09-13-lite-inline-image-groups.md; git commit -m "feat(lite): group consecutive images in markdown"`

Implementation note: isolated images remain unchanged; only runs with at
least two standalone images receive width attributes and row packing. The
full repository suite was attempted but hung without output after roughly ten
minutes, so the directly affected 65-test subset was used for final runtime
verification.
