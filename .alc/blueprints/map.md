---
name: map
purpose: Map the public symbols a feature exposes, for `unship`'s optional derive_checks gate.
compute_tier: standard
checks:
  # This stage only maps a surface — it changes nothing, so a smoke check is enough.
  - name: smoke
    command: ["true"]
report:
  format: json
  schema:
    symbols: list
    summary: string
---

## Map Workflow

This stage is used ONLY when you enable the optional map + derive_checks stages
in `unship` (a grep-based prove-absence opt-in). The default `unship` gate
verifies the removal with the project's real checks instead, so an ordinary
removal never runs this stage.

1. Read the task description to identify the feature being removed.
2. List ONLY the UNIQUE identifiers that feature exposes as its public surface —
   function, class, endpoint, CLI flag, or config key names that another part of
   the codebase, or a user, references by that exact name. The `gate` stage
   proves absence by searching the repo for each name literally, so a name that
   is not unique cannot be proven absent: do NOT list generic tokens (common CSS
   properties like `font-size`, language keywords, or substrings that appear
   widely across the codebase).
3. If the removal has no such unique symbol — a redundant or duplicate
   declaration, a generic property, dead styling — return an EMPTY list. That is
   correct: the `gate` then reports the removal as inconclusive (nothing to
   prove) instead of failing on a name that cannot be proven absent.
4. Do NOT change any code in this stage — mapping only; `remove` does the edit.
5. Output a JSON report matching the schema:
   ```json
   {"symbols": ["<unique_symbol>", ...], "summary": "<one sentence>"}
   ```
