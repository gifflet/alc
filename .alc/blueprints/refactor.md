---
name: refactor
purpose: Simplify the code behavior-preservingly — remove dead or unused surface.
compute_tier: standard
check_set: project
checks:
  # A pack Blueprint must never depend on check_set alone — an empty check_set
  # (no stack tooling on PATH at hire time) would otherwise resolve to zero
  # checks and fail Policy Gate rule 1. This inline check keeps it lint-clean.
  - name: smoke
    command: [ "true" ]
protect: [ "tests/**", "test/**" ]
expect: shrink
report:
  format: json
  schema:
    status: string
    summary: string
archetype: sweeper
---

## Refactor Workflow

1. Find dead or unused code with the stack's real detector: `vulture .`
   (Python), `knip` or `ts-prune` (Node), `staticcheck -unused ./...` (Go), or
   `cargo-udeps` (Rust) — whichever matches this project.
2. Simplify or remove ONE finding (the one named in the task, when given)
   without changing observable behavior — no new features, no API changes.
   Preserve the author's comments unless they became factually wrong: a
   cleanup that deletes someone's notes removes something they wrote on
   purpose, and the diff reviewer may not be a diff reader.
3. Run the checks — including the stack's full check_set, when declared — to
   confirm nothing broke.
4. Output a JSON report matching the schema:
   ```json
   {"status": "ok", "summary": "<one sentence describing what was simplified or removed>"}
   ```
