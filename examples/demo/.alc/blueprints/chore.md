---
name: chore
purpose: Apply a small, single-purpose housekeeping change to the codebase.
compute_tier: standard
checks:
  - name: smoke
    command: ["true"]
    # NOTE: Real blueprints replace ["true"] with meaningful commands such as:
    #   ["ruff", "check", "."]  or  ["pytest", "-q"]
    # ["true"] is used here so the mock demo is green and hermetic without any
    # project toolchain installed.
report:
  format: json
  schema:
    type: object
    required:
      - summary
      - files_changed
    properties:
      summary:
        type: string
        description: One-sentence description of what was done.
      files_changed:
        type: array
        items:
          type: string
        description: List of file paths that were modified.
---

## Chore Workflow

You are executing a **Single-Mandate chore**: one change, one purpose, nothing more.

### Steps

1. **Understand** the task stated in the header above. If the scope is ambiguous, do
   the most conservative interpretation (smallest safe change).

2. **Locate** the relevant code. Do not open files that are not related to the task.

3. **Apply** the change. Follow the existing code style. Keep diffs minimal.

4. **Verify** mentally that you have not changed anything beyond the stated mandate.

5. **Report** your work as a JSON object matching the schema:
   ```json
   {
     "summary": "<one sentence>",
     "files_changed": ["path/to/file.py"]
   }
   ```

### Rules

- **Single purpose** — if you notice another issue, do not fix it here; note it in the
  summary only.
- **Smallest change** — prefer deleting over commenting out; prefer inline over adding
  a helper.
- **Emit the report** — the Assurance Loop validates the output; a missing report is a
  failing check.
