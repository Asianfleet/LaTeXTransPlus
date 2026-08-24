# LLM Custom JSON Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `llm_config.custom_json` as a validated JSON object of additional top-level LLM request fields, applied consistently to Parser, Translator, and Terminology requests.

**Architecture:** Add shared parsing and payload-merging helpers in `src/config.py`. Runtime configuration validates `custom_json` once, while each agent uses the shared merge helper when constructing every request payload. The TUI exposes the value as a JSON textarea and the templates/README document provider-specific examples without provider detection.

**Tech Stack:** Python 3.10+, `json`, TOML, `unittest`, Textual.

## Global Constraints

- `custom_json` is an additional-field JSON object, not a complete request body.
- Empty or whitespace-only `custom_json` disables the feature.
- Arrays, scalars, `null`, and invalid JSON are rejected.
- Custom fields cannot overwrite `model`, `messages`, `temperature`, `max_tokens`, or `max_new_tokens`.
- The feature applies to all Parser, Translator, and Terminology LLM requests, including Translator retries and helper requests.
- Existing behavior must remain unchanged when `custom_json` is absent.
- New functions and classes require concise docstrings.
- Use UTF-8 for Chinese documentation and configuration files.

---

### Task 1: Shared JSON validation and payload merge

**Files:**
- Modify: `src/config.py`
- Test: `tests/test_runtime_config.py`
- Create: `tests/test_llm_config.py`

**Interfaces:**
- Produce `parse_custom_json(value: Any) -> dict[str, Any]`.
- Produce `merge_llm_payload(payload: dict[str, Any], custom_json: dict[str, Any]) -> dict[str, Any]`.
- `load_runtime_config()` must validate `llm_config.custom_json` and retain its parsed dictionary under the same key for agents.

- [ ] **Step 1: Write failing helper and runtime tests**

Add tests for:

```python
def test_parse_custom_json_accepts_object_and_empty_value():
    self.assertEqual(parse_custom_json('{"enable_thinking": true}'), {"enable_thinking": True})
    self.assertEqual(parse_custom_json("  "), {})

def test_parse_custom_json_rejects_non_object_and_invalid_json(self):
    with self.assertRaises(ValueError):
        parse_custom_json("[]")
    with self.assertRaises(ValueError):
        parse_custom_json("{")

def test_merge_llm_payload_adds_custom_fields_without_mutating_input(self):
    payload = {"model": "m", "temperature": 0}
    merged = merge_llm_payload(payload, {"enable_thinking": True})
    self.assertEqual(merged["enable_thinking"], True)
    self.assertNotIn("enable_thinking", payload)

def test_merge_llm_payload_rejects_reserved_field_conflicts(self):
    with self.assertRaises(ValueError):
        merge_llm_payload({"model": "m"}, {"model": "override"})
```

Add a runtime test that loads a TOML file with `custom_json` and asserts the parsed dictionary is present in `config["llm_config"]`.

- [ ] **Step 2: Run focused tests and verify RED**

Run:

```powershell
python -m unittest tests.test_llm_config tests.test_runtime_config
```

Expected: FAIL because the shared functions and `custom_json` validation do not exist.

- [ ] **Step 3: Implement minimal shared helpers**

In `src/config.py`:

- Parse blank values as `{}`.
- Wrap `json.JSONDecodeError` as `ValueError` mentioning `llm_config.custom_json`.
- Require `dict`.
- Merge by copying the base payload, reject any key already present in the base payload, then update with custom fields.
- Validate and replace `llm_config["custom_json"]` in `load_runtime_config()` through the shared parser.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run the same focused command and then:

```powershell
python -m unittest tests.test_runtime_config
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add src/config.py src/runtime.py tests/test_llm_config.py tests/test_runtime_config.py
git commit -m "feat(config): validate custom LLM JSON fields"
```

### Task 2: Apply custom JSON to all LLM agents

**Files:**
- Modify: `src/agents/tool_agents/parser_agent.py`
- Modify: `src/agents/tool_agents/translator_agent.py`
- Modify: `src/agents/tool_agents/terminology_agent.py`
- Test: `tests/test_translator_retry_prompt.py`
- Test: `tests/test_terminology_agent.py`
- Create: `tests/test_llm_request_payloads.py`

**Interfaces:**
- Each agent reads the validated `llm_config.custom_json` dictionary, defaulting to `{}` for direct unit construction.
- Every locally constructed request payload is passed through `merge_llm_payload()` before network submission.

- [ ] **Step 1: Write failing request-payload tests**

Add tests that use the existing fake request/session patterns and assert:

```python
custom = {"enable_thinking": True, "reasoning_effort": "high"}
```

appears at the top level of Parser, Translator, and Terminology request JSON. Add a Translator test for a retry/helper request and assert the same fields are present. Add a test that a direct agent config without `custom_json` produces no extra fields.

- [ ] **Step 2: Run focused request tests and verify RED**

Run:

```powershell
python -m unittest tests.test_llm_request_payloads tests.test_translator_retry_prompt tests.test_terminology_agent
```

Expected: FAIL because current payloads do not include custom fields.

- [ ] **Step 3: Implement payload injection**

Import `merge_llm_payload` in all three agents. Add a small instance helper where useful, such as `_build_llm_payload(payload)`, with a docstring, or call the shared function directly. Apply it to:

- Parser `_request_llm_for_judge`.
- Translator `_request_llm_for_trans`, `_request_llm_for_trans_with_terms`, `_request_llm_for_retrans_error_parts`, `_request_llm_for_extract_terms`, `_request_llm_for_summary`, and `_request_llm_for_refine_summary`.
- Any additional Translator payload literal found by `rg` during implementation.
- Terminology `_request_llm_for_term_batch_decisions`.

Do not alter retry loops, headers, response parsing, or business prompts.

- [ ] **Step 4: Run focused request tests and verify GREEN**

Run:

```powershell
python -m unittest tests.test_llm_request_payloads tests.test_translator_retry_prompt tests.test_terminology_agent
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add src/agents/tool_agents/parser_agent.py src/agents/tool_agents/translator_agent.py src/agents/tool_agents/terminology_agent.py tests/test_llm_request_payloads.py tests/test_translator_retry_prompt.py tests/test_terminology_agent.py
git commit -m "feat(llm): apply custom JSON to agent requests"
```

### Task 3: TUI and configuration templates

**Files:**
- Modify: `src/tui/config_schema.py`
- Modify: `config/template.toml`
- Modify: `README.md`
- Modify: `README_ZH.md`
- Test: `tests/test_tui_app.py`
- Test: `tests/test_tui_config.py`

**Interfaces:**
- Add `ConfigField(("llm_config", "custom_json"), "自定义请求 JSON", "textarea", "LLM", "")`.
- Existing form parsing and TOML preview/save behavior must preserve the string exactly as entered, subject only to normal TextArea handling.

- [ ] **Step 1: Write failing TUI/config tests**

Assert that:

- `CONFIG_FIELDS` contains the `llm_config.custom_json` textarea.
- Form normalization retains a JSON string at that path.
- The settings screen exposes `#config-llm_config-custom_json` as a `TextArea`.
- The template contains `custom_json = ""`.

- [ ] **Step 2: Run focused tests and verify RED**

Run:

```powershell
python -m unittest tests.test_tui_config tests.test_tui_app
```

Expected: FAIL because the field and template entry are absent.

- [ ] **Step 3: Implement TUI/template/documentation changes**

Add the textarea field after the existing LLM endpoint fields. Add an empty TOML value to `config/template.toml`; do not add a secret or enabled thinking behavior by default. Document:

```toml
custom_json = '{"enable_thinking": true}'
```

for SiliconFlow-style requests and:

```toml
custom_json = '{"reasoning_effort": "high"}'
```

for OpenAI-compatible requests. Explain that fields are merged at the top level and reserved field conflicts fail.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run:

```powershell
python -m unittest tests.test_tui_config tests.test_tui_app
```

Expected: PASS, with the real UI config protected according to `AGENTS.md`.

- [ ] **Step 5: Commit**

```powershell
git add src/tui/config_schema.py config/template.toml README.md README_ZH.md tests/test_tui_app.py tests/test_tui_config.py
git commit -m "feat(ui): expose custom LLM JSON configuration"
```

### Task 4: Full verification and plan bookkeeping

**Files:**
- Modify: `docs/superpowers/plans/2026-08-24-llm-custom-json.md`

- [ ] **Step 1: Run the complete test suite**

Run in the `latextrans` conda environment:

```powershell
python -m unittest discover tests
```

Expected: all tests pass.

- [ ] **Step 2: Check formatting and task-only diff**

Run:

```powershell
git diff --check
git status --short
git diff HEAD~3..HEAD --stat
```

Confirm no API keys, generated files, or unrelated modifications are present.

- [ ] **Step 3: Update this plan**

Check off completed tasks and add a short implementation note describing the shared parser/merge helper and the three-agent coverage.

- [ ] **Step 4: Commit bookkeeping**

```powershell
git add docs/superpowers/plans/2026-08-24-llm-custom-json.md
git commit -m "docs: record custom LLM JSON implementation"
```
