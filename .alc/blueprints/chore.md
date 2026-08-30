---
name: chore
purpose: Apply a low-risk, well-scoped maintenance change.
compute_tier: standard
checks:
  - name: test
    command: ["uv", "run", "pytest", "-q"]
report:
  format: json
  schema:
    status: string
    summary: string
---

## Chore Workflow

1. Read the task description and locate the relevant files.
2. Make the smallest change that satisfies the task; keep it single-purpose.
3. Do not touch files outside the stated scope.
4. Run the checks to verify correctness.
5. Output a JSON report matching the schema:
   ```json
   {"status": "ok", "summary": "<one sentence describing what was done>"}
   ```
