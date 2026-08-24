# Remove Domain-Word Candidate Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task with review checkpoints.

**Goal:** Allow valid terminology candidates from any English paper domain to reach LLM review by removing the hard-coded domain-word gate.

**Architecture:** Keep `_extract_rule_candidates()` and `_is_rule_candidate_valid()` as the existing rule-based candidate pipeline. Remove only the domain vocabulary dependency; preserve the remaining filters and the existing LLM validation contract.

**Tech Stack:** Python 3.10+, `unittest`, `pathlib`, local `latextrans` conda environment.

## Global Constraints

- Use the local `latextrans` conda environment for tests.
- Preserve existing public configuration keys and LLM payload schemas.
- Keep the change limited to terminology candidate extraction and its tests.
- Do not read or modify secrets.

---

### Task 1: Update the candidate-extraction regression tests

**Files:**
- Modify: `tests/test_terminology_agent.py`

**Interfaces:**
- Consumes: `TerminologyAgent._extract_rule_candidates(records)`.
- Produces: Regression coverage proving candidate extraction is not restricted to the former domain vocabulary.

- [x] **Step 1: Add a failing assertion for a non-domain phrase**

Rewrite the existing multi-word candidate extraction test to use phrases such as:

```python
records = [
    {
        "part": "sec",
        "id": "1",
        "text": (
            "Semantic analysis supports formatting evaluation. "
            "Semantic analysis improves evaluation."
        ),
    }
]

candidates = agent._extract_rule_candidates(records)

self.assertIn("semantic analysis", candidates)
self.assertIn("formatting evaluation", candidates)
```

The phrases must not contain any former domain-word entry.

- [x] **Step 2: Run the focused test and verify the expected failure**

Run:

```powershell
conda run -n latextrans python -m unittest tests.test_terminology_agent.TerminologyAgentContextTests.test_english_candidate_extraction_finds_multiword_terms
```

Expected: FAIL because the current validator rejects phrases without a configured domain word.

- [x] **Step 3: Remove obsolete test assumptions**

Delete only assertions whose purpose is to require or document the former hard-coded domain vocabulary. Keep assertions that verify rejection of sentence fragments, notation fragments, parser artifacts, and other noise.

### Task 2: Remove the hard-coded domain gate

**Files:**
- Modify: `src/agents/tool_agents/terminology_agent.py`

**Interfaces:**
- Consumes: normalized phrase tokens from `_is_rule_candidate_valid()`.
- Produces: domain-independent candidate validation with the same remaining rejection rules.

- [x] **Step 1: Remove `DOMAIN_WORDS`**

Delete the module-level `DOMAIN_WORDS` set because no production code should depend on it after this change.

- [x] **Step 2: Remove the domain-word validation branch**

Delete this condition from `_is_rule_candidate_valid()`:

```python
if not any(token in DOMAIN_WORDS for token in phrase_tokens):
    return False
```

Leave all subsequent validation branches unchanged.

- [x] **Step 3: Run the focused terminology tests**

Run:

```powershell
conda run -n latextrans python -m unittest tests.test_terminology_agent
```

Expected: PASS.

### Task 3: Verify the complete change

**Files:**
- Inspect: `src/agents/tool_agents/terminology_agent.py`
- Inspect: `tests/test_terminology_agent.py`
- Inspect: `docs/superpowers/specs/2026-08-24-remove-domain-word-gate-design.md`

- [x] **Step 1: Run the full test suite**

Run:

```powershell
conda run -n latextrans python -m unittest discover tests
```

Expected: PASS with no test failures.

- [x] **Step 2: Check the final diff**

Run:

```powershell
git diff --check
git status --short
git diff -- src/agents/tool_agents/terminology_agent.py tests/test_terminology_agent.py docs/superpowers/specs/2026-08-24-remove-domain-word-gate-design.md docs/superpowers/plans/2026-08-24-remove-domain-word-gate.md
```

Expected: only the requested terminology implementation, related tests, and planning documentation are changed.
