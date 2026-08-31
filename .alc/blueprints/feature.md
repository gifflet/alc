---
name: feature
purpose: Implement a new feature.
compute_tier: deep
check_set: project
checks: []
report:
  format: json
  schema:
    status: string
    summary: string
---

## Feature Workflow

1. Understand the requirement stated in the task description.
2. Design the smallest viable approach that satisfies the requirement.
3. Implement the feature following the existing code style and conventions.
4. Verify the implementation by running the checks.
5. Output a JSON report matching the schema:
   ```json
   {"status": "ok", "summary": "<one sentence describing what was implemented>"}
   ```
