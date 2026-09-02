---
name: qa
purpose: Verify the change end-to-end against a live instance of the service.
compute_tier: standard
needs_service: true
# e2e evidence: runs once the health poll has already
# proven the service reachable, and writes into $ALC_ARTIFACTS_DIR — ALC
# collects whatever lands there (plus the health-poll log) into the
# RunReport, readable back via `alc artifacts`. Swap for a real screenshot
# tool; this curl is the smallest example that proves the pattern.
capture: curl -sf "$ALC_BASE_URL" -o "$ALC_ARTIFACTS_DIR/health-check.txt"
check_set: project
checks:
  # Hits the live service ALC started for this run ($ALC_BASE_URL) — the inline
  # check that keeps this Blueprint lint-clean even when check_set resolves empty.
  - name: e2e-smoke
    shell: 'curl -sf "$ALC_BASE_URL"'
report:
  format: json
  schema:
    status: string
    summary: string
archetype: builder
---

## QA Workflow

1. Read the task description to understand the user-facing behavior to verify.
2. Exercise it against the live service at $ALC_BASE_URL (the app ALC started
   for this run) — never mock the service.
3. Run the checks to confirm the change behaves correctly end-to-end.
4. Output a JSON report matching the schema:
   ```json
   {"status": "ok", "summary": "<one sentence describing what was verified>"}
   ```
