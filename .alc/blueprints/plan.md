---
name: plan
purpose: Produce a focused implementation plan.
compute_tier: deep
checks:
  # Replace this with your real checks, e.g. ["ruff", "check", "."] and ["pytest", "-q"]
  - name: smoke
    command: ["true"]
report:
  format: json
  schema:
    plan: string
---

## Plan Workflow

1. Read the task description and any relevant files to understand the scope.
2. Produce a concise, numbered step-by-step implementation plan.
3. Each step should be actionable and independently verifiable.
4. Do NOT write application code in this stage — planning only.
5. Output a JSON report matching the schema:
   ```json
   {"plan": "<the full step-by-step plan as text>"}
   ```
