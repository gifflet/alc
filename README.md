<div align="center">

# 🛠️ ALC — Agentic Layer Compiler & Runtime

**Declare how your agents should work once. Run it on any coding engine — with the guardrails built in.**

![python](https://img.shields.io/badge/python-3.12+-blue)
![status](https://img.shields.io/badge/status-experimental-orange)
![engines](https://img.shields.io/badge/engines-claude%20code%20·%20gemini%20·%20mock-8A2BE2)

**English** | [Português](README.pt-BR.md)

</div>

---

ALC is a **control plane for agentic coding**. It keeps the good practices — verification, focus, isolation, review — *outside* the model, in plain deterministic code. The coding engine (Claude Code, Gemini, …) becomes a thin, swappable executor.

The point: best practices stop being discipline you have to remember, and become defaults you can't skip.

## ✨ Highlights

- 🛡️ **Guarantees outside the model** — the Assurance Loop runs your checks and repairs until they pass. Nothing is reported done until it actually is.
- 🔌 **Engine-agnostic** — Claude Code or Gemini. Switch with a flag; the control plane doesn't change.
- 🎯 **One agent, one purpose** — every task is a focused Single Mandate. No context pollution.
- 🧩 **Composable** — Blueprints → Flows → a Conductor that turns a goal into the right Flows.
- 🌙 **Unattended** — drop tasks in a queue; cron's `alc tick` drains them, isolated, while you're away.
- 🧠 **Specialists** — agents that keep a Knowledge File and get better at an area over time.
- 🔒 **Isolated** — `--isolate` runs the work in a throwaway git-worktree branch, so your working tree stays clean.

## 🚀 Quick Start

> New to ALC? The [first-run guide](docs/first-run.md) walks you from install to a verified change, with the rough edges flagged.
>
> If you set up with `uv sync`, prefix the commands below with `uv run` (e.g. `uv run alc lint`).

**Install**

```bash
uv sync                 # dev environment
# — or install the CLI globally —
uv tool install .       # gives you a global `alc`
```

**Set up a project**

```bash
cd your-project
alc init --setup        # scaffold .alc/ + install the editor skill (Claude Code by default)
alc lint                # check the Operator Layer is well-formed
```

**Run**

```bash
# Safe by default: the scaffolded manifest uses the free Mock engine (no model calls).
alc run chore "remove the unused export endpoint"

# Use a real engine when you're ready:
alc run chore "tidy the imports"        --engine claude-code
alc run chore "tidy the imports"        --engine claude-code --tier standard
alc flow ship "add a changelog entry"   --engine claude-code --isolate
alc conduct "the README is stale, refresh the docs" --engine claude-code --parallel
alc primer new my-context               # scaffold a Primer at .alc/primers/my-context.md
alc tick --concurrency 4                # drain the queue 4 tasks at a time
```

## 🧭 Commands

| Command | What it does |
|---|---|
| `alc init [--setup]` | Scaffold a default `.alc/` Operator Layer; detects your stack and writes real checks (and installs the editor skill) |
| `alc lint` | Validate the Operator Layer (your `.alc/`, not your source code) against the Policy Gate |
| `alc run <blueprint> "<task>"` | Run one Blueprint as a verified Single Mandate; `--tier NAME` overrides the compute tier for this invocation |
| `alc flow <flow> "<task>"` | Run a multi-stage pipeline (e.g. plan → build); `--tier NAME` applies to every stage; verify-only stages act as pure Policy Gates (checks only, no engine turn) |
| `alc conduct "<goal>" [--parallel]` | Let ALC pick which Flow(s) to run; `--parallel` dispatches independent units concurrently in isolated worktrees; `--enqueue` to queue instead |
| `alc specialist <name> "<task>"` | Run an area Specialist (Recall → Act → Learn) |
| `alc tick [--concurrency N]` | Drain the task queue — call this from cron; `--concurrency N` processes up to N isolated tasks in parallel |
| `alc primer new <name>` | Scaffold a new Primer file at `.alc/primers/<name>.md` |
| `alc setup [--engine]` | Install/update the user-level editor skill (Claude Code or Gemini) |

Add `--engine claude-code|gemini|mock` to choose the executor, and `--isolate` to contain edits to a git-worktree branch.

Blueprints support `max_repairs` to cap the Assurance Loop repair budget, and `check_set` to reference a reusable named check set declared in the Manifest. Checks run by exit code without a shell by default; add a `shell:` one-liner to a check entry to run it via `sh -c` (note: shell checks still exit-code only — there is no stdout capture).

## 🧱 How it fits together

ALC lives in a ring around your codebase — the **Operator Layer** (`.alc/`), kept separate from your app code:

- **Blueprint** — a template for a class of work (chore, bug, feature…), carrying its own checks and report.
- **Flow** — Blueprints composed into a pipeline; each stage is its own mandate, threading context forward.
- **Conductor** — turns a high-level goal into the right Flows, then runs or queues them.
- **Specialist** — an agent with a Knowledge File for one area, improving as it works.
- **Assurance Loop** — `Act → Verify → Repair`. Your checks are the law.
- **Scorecard** — tracks Span / Passes / Streak / Touch, heading toward hands-off delivery.

## 🪜 Where you are on the ladder

ALC grows with you: **Attended** (you run it) → **Detached** (it runs unattended off the queue) → **Conducted** (a Conductor drives the Flows for you). You don't start at the top — you climb.

## 📚 Documentation

- [Concepts & vocabulary](docs/concepts.md) — the words ALC uses, and the two-plane model
- [Architecture](docs/architecture.md) — the control-plane / execution-plane diagram
- [Engine contract](docs/engine-contract.md) — what it takes to plug in an engine
- [MVP & roadmap](docs/mvp.md)

## 🧪 Status

Experimental, but real: every feature is covered by a hermetic test suite and validated live against Claude Code and Gemini. Python 3.12 + uv, no heavy dependencies.

## 📄 License

Not yet licensed — add a `LICENSE` file before sharing this publicly.
