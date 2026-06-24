---
name: plan
purpose: Read the task and produce a concise step-by-step plan without writing application code.
compute_tier: deep
checks:
  - name: smoke
    command: ["true"]
    # NOTE: Real plan blueprints replace ["true"] with a check that confirms a written spec
    # file was produced, e.g.: ["test", "-f", "plan.md"]
    # ["true"] is used here so the mock demo is green and hermetic without any
    # project toolchain installed.
report:
  format: json
  schema:
    type: object
    required:
      - plan
    properties:
      plan:
        type: string
        description: The concise step-by-step plan as a numbered list.
---

## Plan Workflow

You are executing a **Single-Mandate plan**: read the task and produce a plan — nothing more.

### Steps

1. **Read** the task stated in the header above. Understand its full scope.

2. **Identify** the relevant files, modules, or components that will be affected.

3. **Produce** a concise, numbered, step-by-step plan describing what must be done.
   Be specific enough that a build stage can follow the plan without guessing.

4. **Do NOT write application code** in this stage. Planning only.

5. **Report** your plan as a JSON object matching the schema:
   ```json
   {
     "plan": "1. Do X\n2. Do Y\n3. Do Z"
   }
   ```

### Rules

- **Single purpose** — planning only. No code edits, no file creation beyond the plan output.
- **Be concrete** — vague plans produce bad builds; name files and functions where known.
- **Emit the report** — the Assurance Loop validates the output; a missing report is a failing check.
