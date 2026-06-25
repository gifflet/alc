# First Run

A 10-minute path from "never used ALC" to "an agent shipping a verified change" —
with the rough edges called out so you don't trip on them.

## 1. Install

```bash
uv tool install <path-to-the-alc-repo>   # puts `alc` on your PATH (~/.local/bin)
alc --version                            # confirm it's installed: alc X.Y.Z
```

> Iterating on ALC itself? Bump the version before reinstalling — `uv tool install
> --force` silently reuses a cached build when the version is unchanged, so your
> changes won't land.

## 2. Initialize

```bash
cd your-project
alc init        # creates .alc/ — the Operator Layer (your agentic config)
```

The `.alc/` folder is **ALC's layer**, kept separate from your app code *and* from
Claude Code's `.claude/`. `alc lint` validates **this folder** — not your source code,
and not your editor's agents/skills. Right after `init` it's a trivial pass; it earns
its keep once you start editing Blueprints.

## 3. Make it know your stack

The defaults are deliberately generic. Two edits make ALC real for your project:

**Pick a real engine.** In `.alc/manifest.yaml`, change `default_engine: mock` to
`claude-code` (or `gemini`). `mock` is a free no-op for dry runs; the real engines do
the work.

**Set real checks.** Each Blueprint ships placeholder `["true"]` checks. Replace them
with the commands that gate your work:

```yaml
checks:
  - name: build
    command: ["go", "build", "./..."]
  - name: vet
    command: ["go", "vet", "./..."]
```

Two rules that save you pain:

- Checks are judged by **exit code** and run **without a shell**. `go build`, `pytest`,
  `tsc --noEmit` work. `gofmt -l` (exits 0 even when files are unformatted) and anything
  needing pipes or `$(...)` don't.
- **Run each check yourself once first.** A check that already fails on a clean checkout
  makes *every* run fail — the agent can't fix problems that aren't its task.

Re-run `alc lint` — now it's validating *your* Blueprints.

## 4. Prime the context (optional, but worth it)

Don't make the agent explore from scratch. Drop a curated pointer in
`.alc/primers/<name>.md` — where the relevant code lives and the convention to follow —
and pass `--primer <name>`. Small, high-value context beats a giant always-on file.

## 5. Run it

```bash
alc run feature "…a clear task description…" --primer <name>
```

You'll see live progress — each file read/edited, the model in use, the cost — then the
Assurance Loop running your checks (`✓ all checks passed`). A feature with a strong
model takes a couple of minutes; the streaming tells you it's working, not hung.

Two heads-ups:

- The model and cost come from the Blueprint's compute tier (`feature` → `deep` → the
  priciest model). There's no per-run model flag yet — edit the tier to switch.
- Without `--isolate`, edits land in your working tree. If you cancel mid-run, partial
  changes stay — including new, **untracked** files. Check `git status`, not just
  `git diff --stat` (the latter hides untracked files).

## 6. Review — the human gate

ALC guarantees the change **compiles and your checks pass**. It does *not* guarantee the
change is *right*. Read the diff (and any new files via `git status`), judge it, keep or
discard. That's the one step ALC deliberately leaves to you.

---

That's the loop: **init → teach it your stack → prime → run → review.** Thicken your
Operator Layer over time (more Blueprints, Flows, Specialists) and the agent takes on
more of the work — with the guardrails always on.

## Known rough edges

Honest, still-being-smoothed:

- `alc init` doesn't detect your stack — you set checks by hand on each Blueprint.
- No `--tier` flag to pick the model per run (edit the Blueprint's `compute_tier`).
- The run report doesn't list the files it changed (check `git status`).
- The `claude-code` engine runs inside your project, so it inherits your `.claude/`
  hooks/settings — which can add harmless noise to the output.
