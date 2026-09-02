---
name: grow
purpose: Grow the product — strengthen a weak test or improve a tracked metric
  without regressing.
compute_tier: standard
check_set: project
checks:
  # A pack Blueprint must never depend on check_set alone — an empty check_set
  # (no stack tooling on PATH at hire time) would otherwise resolve to zero
  # checks and fail Policy Gate rule 1. This inline check keeps it lint-clean.
  - name: smoke
    command: [ "true" ]
  # OPT-IN — the Grower's own law: a METRIC CHECK. Uncomment this block and
  # replace the command with one that prints YOUR tracked number (bundle
  # size, coverage %, p95 latency, …) as a single number on stdout. The
  # engine never judges the number: the Verifier records it in the metric
  # ledger and FAILS the run when it regresses beyond tolerance_pct vs the
  # last ACCEPTED measurement — direction says which way is better, and a
  # check with no history yet always passes (recorded as the baseline). The
  # series then shows in `alc metrics` and the UI Metrics view. Until one
  # is live, the Grower is conduct/enqueue-driven: route work via
  # `alc conduct "<goal>"` or `alc enqueue`; once measurements accumulate,
  # a Loop with a `regression` replenish can auto-enqueue a fix demand
  # whenever a metric regresses.
  # - name: bundle-size
  #   metric: ["scripts/bundle_size.py"]  # any argv/shell that prints a number
  #   direction: lower_is_better          # or higher_is_better (e.g. coverage)
  #   tolerance_pct: 5.0                  # % slack absorbing benchmark noise
report:
  format: json
  schema:
    status: string
    summary: string
archetype: grower
---

## Grow Workflow

1. Read the task to pick ONE growth target: a coverage gap, a weak or missing
   test, or a tracked metric the task names.
2. Strengthen it — add or harden the tests around that behavior, or make the
   smallest change that improves the metric. No unrelated features.
3. Run the checks — including the stack's full check_set, when declared — to
   confirm the growth holds and nothing regressed.
4. Output a JSON report matching the schema:
   ```json
   {"status": "ok", "summary": "<one sentence describing what was grown or hardened>"}
   ```
