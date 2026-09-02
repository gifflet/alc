---
name: test
purpose: Author tests that cover the behavior a change just introduced.
compute_tier: standard
check_set: project
checks:
  # A pack Blueprint must never depend on check_set alone — an empty check_set
  # (no stack tooling on PATH at hire time) would otherwise resolve to zero
  # checks and fail Policy Gate rule 1. This inline check keeps it lint-clean.
  - name: smoke
    command: [ "true" ]
report:
  format: json
  schema:
    status: string
    summary: string
archetype: builder
---

## Test Workflow

1. Read the task description and the recent diff to find the behavior that changed.
2. Write or extend tests that exercise it: the happy path and at least one edge case.
3. Run the checks — including the stack's full check_set, when declared — to
   confirm the new tests pass alongside the existing suite.
4. Output a JSON report matching the schema:
   ```json
   {"status": "ok", "summary": "<one sentence describing the tests added>"}
   ```
