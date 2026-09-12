# Lite 附录翻译开关 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 Lite 增加默认开启的附录翻译开关；关闭时保留附录原文并排除其翻译与术语处理。

**Architecture:** 在 `lite_markdown` 集中完成附录标题识别、额外切块和不可翻译标记。Lite 引擎生成一次策略化块列表，翻译器复用 `MarkdownBlock.translatable`，术语代理只读取该策略下的可翻译内容。配置通过已有 Lite runtime fields 和 TUI schema 生效。

**Tech Stack:** Python 3.10+、标准库 `re`/`unittest`、TOML、Textual。

## Global Constraints

- `lite.translate_appendix` 的默认值与缺省行为均为 `true`。
- 仅识别非代码围栏中的 ATX 标题；不将 Supplementary Material 识别为附录。
- 只影响 Lite，Heavy effective config 和设置页面不得得到此字段。
- 关闭后附录标题及其后续 Markdown 均原样保留，且不得发起翻译或术语 LLM 请求。
- 新增函数与方法具有简短 docstring；新增注释使用中文。

## 文件结构

- `src/engines/lite_markdown.py`：识别源语言附录标题、分块和术语可见内容。
- `src/engines/lite.py`：复用一次策略化块列表，记录跳过日志。
- `src/agents/tool_agents/markdown_terminology_agent.py`：排除不可翻译块。
- `src/engines/base.py`、`src/tui/config.py`、`src/tui/config_schema.py`、两个 Lite TOML：配置传递和设置项。
- `tests/test_lite_markdown.py`、`tests/test_lite_engine.py`、`tests/test_markdown_terminology_agent.py`、配置和 TUI 测试：行为回归。
- `README.md`、`README_ZH.md`：配置说明。

---

### Task 1: 附录识别和分块

**Files:**
- Modify: `src/engines/lite_markdown.py`
- Test: `tests/test_lite_markdown.py`

**Interfaces:**
- Produces: `split_markdown(text: str, source_language: str = "en", translate_appendix: bool = True) -> list[MarkdownBlock]`。
- Produces: `translatable_markdown(blocks: Sequence[MarkdownBlock]) -> str`。

- [ ] **Step 1: 写失败测试**

```python
def test_skip_appendix_marks_nested_heading_and_following_blocks(self):
    source = "## Method\nBody\n### Appendix A. Details\nRaw appendix\n## References\nRaw refs"
    blocks = split_markdown(source, source_language="en", translate_appendix=False)
    self.assertEqual([block.translatable for block in blocks], [True, False, False])
    self.assertEqual(blocks[1].text, "### Appendix A. Details\nRaw appendix\n")

def test_appendix_headings_match_supported_source_languages(self):
    cases = (("ch", "附录 A"), ("de", "Anhang A"), ("fr", "Annexe A"), ("ja", "付録 A"), ("ko", "부록 A"))
    for language, heading in cases:
        with self.subTest(language=language):
            blocks = split_markdown(f"## Body\ntext\n## {heading}\nraw", language, False)
            self.assertEqual([block.translatable for block in blocks], [True, False])
```

- [ ] **Step 2: 验证失败**

Run: `conda run -n latextrans python -m unittest tests.test_lite_markdown.MarkdownBlockTests`

Expected: FAIL，当前函数不接受策略参数，也不会标记附录。

- [ ] **Step 3: 最小实现**

```python
def split_markdown(text: str, source_language: str = "en", translate_appendix: bool = True) -> list[MarkdownBlock]:
    """按二级标题与附录起点分块，并按策略标记附录。"""

def translatable_markdown(blocks: Sequence[MarkdownBlock]) -> str:
    """返回术语阶段可见的 Markdown 内容。"""
    return "\n\n".join(block.text for block in blocks if block.translatable)
```

沿用围栏与 front matter 状态机；为任何匹配的附录标题建立边界，关闭时从首个附录块开始设置 `translatable=False`。词表匹配英文 Appendix/Appendices、中文“附录”/“附錄”、德文 Anhang、法文 Annexe、日文“付録”、韩文“부록”，允许编号和副标题。

- [ ] **Step 4: 验证通过并提交**

Run: `conda run -n latextrans python -m unittest tests.test_lite_markdown`

Expected: PASS。提交命令：`git add src/engines/lite_markdown.py tests/test_lite_markdown.py && git commit -m "feat(lite): detect appendix markdown sections"`。

### Task 2: 将块策略接入 Lite 翻译和术语流程

**Files:**
- Modify: `src/engines/lite.py`
- Modify: `src/agents/tool_agents/markdown_terminology_agent.py`
- Test: `tests/test_lite_engine.py`
- Test: `tests/test_markdown_terminology_agent.py`

**Interfaces:**
- Consumes: `split_markdown(source_text, source_language, translate_appendix)` 与 `translatable_markdown(blocks)`。
- Produces: 关闭且命中附录时，Lite 日志包含“Appendix detected”和跳过块数。

- [ ] **Step 1: 写失败测试**

```python
def test_run_marks_appendix_blocks_and_logs_the_policy(self):
    result, logs = self._run_engine(
        root,
        config={"source_language": "en", "target_language": "ch", "translate_appendix": False},
        mineru=_AppendixMineru(),
    )
    self.assertTrue(result["ok"])
    self.assertEqual([block.translatable for block in translator.blocks], [True, False])
    self.assertTrue(any("appendix detected" in str(event["message"]).casefold() for event in logs))

def test_collect_records_excludes_appendix_when_translation_is_disabled(self):
    config = {"source_language": "en", "lite": {"translate_appendix": False}}
    agent = MarkdownTerminologyAgent(config, path, output_dir)
    records = agent._collect_markdown_records("## Method\nCore method\n## Appendix\nAppendix-only term")
    self.assertNotIn("Appendix-only term", " ".join(record["text"] for record in records))
```

- [ ] **Step 2: 验证失败**

Run: `conda run -n latextrans python -m unittest tests.test_lite_engine tests.test_markdown_terminology_agent`

Expected: FAIL，引擎未将配置传入切块，术语代理仍扫描全文。

- [ ] **Step 3: 最小实现**

```python
blocks = split_markdown(
    source_text,
    source_language=str(project_config.get("source_language", "en")),
    translate_appendix=bool(project_config.get("translate_appendix", True)),
)
skipped = sum(not block.translatable for block in blocks)
if skipped:
    self._log(f"Appendix detected; skipped {skipped} Markdown block(s).", "info", result, log_callback)
```

将同一个 `blocks` 交给翻译工厂。术语代理从配置读取开关，使用同一切块函数和 `translatable_markdown` 后执行既有可见文本清理；其标题、摘要上下文仍传入完整 Markdown。

- [ ] **Step 4: 验证通过并提交**

Run: `conda run -n latextrans python -m unittest tests.test_lite_engine tests.test_markdown_terminology_agent tests.test_markdown_translator_agent`

Expected: PASS。提交命令：`git add src/engines/lite.py src/agents/tool_agents/markdown_terminology_agent.py tests/test_lite_engine.py tests/test_markdown_terminology_agent.py && git commit -m "feat(lite): skip appendix translation and terminology"`。

### Task 3: 配置、TUI 与文档

**Files:**
- Modify: `config/default.toml`
- Modify: `config/template.toml`
- Modify: `src/engines/base.py`
- Modify: `src/tui/config.py`
- Modify: `src/tui/config_schema.py`
- Modify: `tests/test_engine_config.py`
- Modify: `tests/test_tui_config.py`
- Modify: `tests/test_tui_config_schema.py`
- Modify: `README.md`
- Modify: `README_ZH.md`

**Interfaces:**
- Produces: `[lite].translate_appendix: bool`，默认 `true`。
- Produces: `ConfigField(("lite", "translate_appendix"), "翻译附录", "switch", "翻译", True)`。

- [ ] **Step 1: 写失败测试**

```python
def test_engine_config_copies_lite_appendix_setting_only_for_lite(self):
    source = {"heavy": {}, "lite": {"translate_appendix": False}}
    self.assertFalse(engine_config(source, "lite")["translate_appendix"])
    self.assertNotIn("translate_appendix", engine_config(source, "heavy"))

def test_lite_appendix_switch_defaults_to_enabled(self):
    field = next(field for field in config_fields_for_engine("lite") if field.path == ("lite", "translate_appendix"))
    self.assertEqual((field.kind, field.default, field.section), ("switch", True, "翻译"))
```

- [ ] **Step 2: 验证失败**

Run: `conda run -n latextrans python -m unittest tests.test_engine_config tests.test_tui_config tests.test_tui_config_schema`

Expected: FAIL，Lite runtime fields、迁移默认值与 TUI schema 均没有该字段。

- [ ] **Step 3: 最小实现**

```python
_ENGINE_RUNTIME_FIELDS["lite"] = (..., "translate_appendix")
lite.setdefault("translate_appendix", True)
ConfigField(("lite", "translate_appendix"), "翻译附录", "switch", "翻译", True)
```

两个 `[lite]` TOML 添加 `translate_appendix = true`。两个 README 的 Lite 配置片段和行为说明写明：关闭后按当前源语言附录标题检测，附录原样保留且不参与术语生成。

- [ ] **Step 4: 验证通过并提交**

Run: `conda run -n latextrans python -m unittest tests.test_engine_config tests.test_tui_config tests.test_tui_config_schema`

Expected: PASS。提交命令：`git add config/default.toml config/template.toml src/engines/base.py src/tui/config.py src/tui/config_schema.py tests/test_engine_config.py tests/test_tui_config.py tests/test_tui_config_schema.py README.md README_ZH.md && git commit -m "feat(config): add lite appendix translation setting"`。

### Task 4: 定向验证与计划收尾

**Files:**
- Modify: `docs/superpowers/plans/2026-09-12-lite-appendix-translation.md`

**Interfaces:**
- Consumes: 前三项的完整实现。
- Produces: 全部步骤状态和每项的 `Implementation note:`。

- [ ] **Step 1: 运行完整相关套件**

Run: `conda run -n latextrans python -m unittest tests.test_lite_markdown tests.test_lite_engine tests.test_markdown_terminology_agent tests.test_markdown_translator_agent tests.test_engine_config tests.test_tui_config tests.test_tui_config_schema`

Expected: PASS。

- [ ] **Step 2: 审查差异**

Run: `git diff --check`，然后运行 `git status --short` 与 `git diff --stat HEAD`。

Expected: 无空白错误，且仅出现本计划列出的 Lite 功能、测试、文档和计划文件。

- [ ] **Step 3: 更新计划并提交**

将每项步骤标记为完成，并在每项任务末尾加入实际实现与验证结果。提交命令：`git add docs/superpowers/plans/2026-09-12-lite-appendix-translation.md && git commit -m "docs: record lite appendix translation implementation"`。
