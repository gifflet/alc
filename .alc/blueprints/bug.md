---
name: bug
purpose: Diagnose and fix a bug.
compute_tier: standard
checks:
  - name: test
    command: ["uv", "run", "pytest", "-q"]
report:
  format: json
  schema:
    status: string
    root_cause: string
    fix: string
    summary: string
---

## Bug Workflow

1. Reproduce the bug using the information in the task description.
2. Find the root cause — trace it to the smallest possible location.
3. Apply the smallest fix that resolves the root cause without side effects.
4. Validate the fix by running the checks.
5. Output a JSON report matching the schema:
   ```json
   {
     "status": "ok",
     "root_cause": "<what caused the bug>",
     "fix": "<what was changed>",
     "summary": "<one sentence summary>"
   }
   ```
