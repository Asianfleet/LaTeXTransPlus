# Remove Domain-Word Candidate Gate

## Goal

Remove the hard-coded domain-word requirement from terminology candidate extraction so that valid multi-word terms from any paper domain can reach the LLM review stage.

## Scope

- Remove the `DOMAIN_WORDS` constant from `src/agents/tool_agents/terminology_agent.py`.
- Remove the corresponding validation branch in `_is_rule_candidate_valid()`.
- Keep the existing English-language guard, 2–5 token window, stop phrases, context-word filtering, LaTeX artifact filtering, generic-word filtering, function-word filtering, noun-phrase ending checks, and other noise filters unchanged.
- Update terminology-agent tests so they verify domain-independent candidates and no longer encode the removed domain-word gate.
- Do not change configuration keys, LLM request formats, candidate limits, or translation behavior.

## Design

Candidate extraction remains a lightweight rule-based prefilter. Its responsibility is to reject obvious sentence fragments and parser artifacts, not to decide whether a phrase belongs to a predefined research domain. The LLM remains responsible for the semantic terminology decision.

The regression test will use phrases that do not contain any former domain-word entry, such as `semantic analysis` and `formatting evaluation`, and will assert that they are extracted while existing noise fragments remain rejected. Existing tests that exercise context, notation, parser-artifact, and clause-boundary filtering remain useful; the former domain-specific positive example is rewritten to use domain-independent phrases.

## Verification

- Run the focused terminology-agent test module.
- Run the full unittest suite in the `latextrans` conda environment.
- Confirm the final diff contains only the terminology implementation, related tests, and this design/plan documentation.
