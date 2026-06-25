# ALC Overview Primer

ALC (Agentic Layer Compiler & Runtime) enforces agentic best practices in the control
plane so the engine never has to self-police.

**Operator Layer** — the `.alc/` directory: manifest, blueprints, flows, primers.

**Key commands**:
- `alc run <blueprint> "<task>" [--engine NAME]` — Single-Mandate run.
- `alc flow <flow_name> "<task>"` — multi-stage pipeline.
- `alc lint` — Policy Gate conformance check.

**Context Budget moves**: `--primer NAME` trims what enters the context (Primer injection);
`--bundle` / `--from-bundle REF` records and replays prior run summaries (Offload).
