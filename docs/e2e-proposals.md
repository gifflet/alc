# Proposals from the E2E friction log

Twenty-two findings, from installing 0.44.2 with the published command and then
using alc to change alc. Full log: [e2e-friction-log.md](e2e-friction-log.md).

Ordered by what they cost a user, not by effort.

---

## A. The verdict can be wrong (findings 14, 19, 6, 2, 5, 22)

These are one problem wearing four hats: **something says work is verified when
it is not.** Everything else on this list is comfort by comparison.

### A1 — The Inbox must not offer to Land unverified work

**DONE** — `4a27239`, `8cf4aca`.
*Findings 14, 19. Blocker.*

A run I interrupted, whose only check failed, committed to a branch and appeared
in the Inbox as "run work ready to land" with a Land button — identical to a
branch that passed. The Run Detail view for the same work already says
"ABORTED — Stopped before finishing. Nothing was reported as done."

**The signal exists on disk.** `cli.py:886` archives `<branch>.report.json` only
`if report.success`. A branch with no report beside it never passed.

Proposal: `service.list_branches` reports whether a report exists for each
branch. The Inbox and Branch Review use it — an unverified branch is labelled
"never passed its checks", its action is Review or Discard, and Land requires
going through the diff first. Not a new concept; wiring what is already there.

Cost: small. Risk: low — it only ever adds a warning.

### A2 — Detect stacks below the repo root

**DONE** — `57c9656`.
*Finding 2. Blocker.*

`scaffold._marker_present` tests `project_root / marker` only. This repo has
`ui/package.json` and `docs-site/package.json` with 603 tests between them, and
`alc init` scaffolded pytest alone. Any project with its frontend in a
subdirectory gets checks covering half of itself.

Proposal: search one or two levels down for marker files, and scaffold a check
per stack found, with its working directory. Keep it bounded — do not walk
`node_modules`. Where a subdirectory stack is found, say so in the init output
by name, so the user can see what was and was not covered.

Cost: medium. Risk: medium — more checks means slower runs, so the init output
must make the trade visible rather than silently tripling run time.

### A3 — `alc lint` should report check COVERAGE, not just layer shape

**DONE** — `9381347`.
*Findings 5, 22.*

Lint said "No violations found. Operator Layer is conformant." about a layer
whose checks cannot see half the repo. Conformant is about shape; a reader takes
it as "my setup is sound".

Proposal: add a coverage note to lint — which stacks are present, which have a
check, which do not. It does not have to fail; it has to be said. This is the
measurement that makes the Start card's promise honest.

### A4 — A check that cannot pass in isolation should be caught at init

**DONE** — `6c7ef62`.
*Finding 6. Blocker.*

`init` wrote `uv run pytest -q`. In an isolated worktree that builds a fresh venv
without the `ui` extra and fails on a missing `fastapi`, every time, for reasons
unrelated to any change. My first real run burned ~7 minutes of repair turns and
real money chasing it. `worktree_provision` fixes it in two lines and init never
writes it.

Proposal, in order of value:
1. When a gitignored virtualenv is detected, scaffold `worktree_provision`.
2. Read the project's own CI for the command it uses (`uv sync --extra ui`)
   rather than guessing `uv run pytest`.
3. Failing both: after init, offer to dry-run the checks in a throwaway worktree
   and report if they cannot pass there. Better to find out in ten seconds than
   in a repair loop.

---

## B. The tool goes quiet when it matters (findings 8, 9, 10, 13, 21)

### B1 — Put the JSON behind a flag
*Findings 8, 13, 21. Highest value per line changed.*

Every `alc run` prints ~35 lines of serialised model after its four-line summary.
`alc run --help` offers no `--json` and no `--quiet`; it is the only mode. The
one actionable sentence a run produces — "Isolated changes committed on branch:
… (review and merge from …)" — is printed under all of it.

`alc audit` already prints five clean lines and no JSON. The good pattern is in
the codebase.

Proposal: human summary by default, `--json` for the full report. One flag, one
conditional.

### B2 — Say something while a check runs
*Finding 9.*

`→ Verify (1 check(s))…` then 100 seconds of nothing. With a real engine, Act is
minutes of silence too. I could not tell working from hung, which is why I killed
my first real run at ten minutes.

Proposal: name the check as it starts and print its elapsed time on finish —
`✓ test (100s)`. The events already carry `duration_s`.

### B3 — Truncate engine activity from the left, not the right
*Finding 10.*

    • Read: /private/var/folders/p6/rt1tk2pn37189vrg5y_7kwtc0000gp/T/alc
    • Edit: /private/var/folders/p6/rt1tk2pn37189vrg5y_7kwtc0000gp/T/alc

Four lines, each cut at the same width, all showing the identical worktree
prefix and dropping the filename — the only part that varies.

Proposal: show the path relative to the worktree root. `Edit: install.sh`.

---

## C. The UI shows the wrong things first (findings 12, 15, 16, 17, 18)

### C1 — `alc ui` should open on the project you are standing in
*Finding 12. Blocker for the mental model.*

I ran `alc ui` inside an alc project and it opened listing two unrelated
projects, not that one. Every other command is cwd-scoped; `alc ui` alone is not.

Proposal: when the cwd is an alc project, register it if new and open it. The
global registry stays — this only decides where the tool lands.

### C2 — Surface pending decisions on the Dashboard
*Finding 15.*

Two branches awaited a decision. Six cards on screen, none about them; the only
signal was a "2" on a rail icon. "Mix Health: No stage declared" got a full card.

Proposal: when the Inbox is non-empty, it leads the Dashboard. It is the only
thing on the page that needs a human.

### C3 — Make runs tellable apart
*Finding 16.*

Five rows reading `run 20260830T041713-run-chore-in-d…`, truncated so that the
task text — the only difference — is what gets removed.

Proposal: show the task, with the timestamp as secondary. Same data, other way
round.

### C4 — Explain the numbers, or show fewer
*Findings 17, 18, 11.*

Eight metrics on the Dashboard's most prominent card with no legend; SPAN,
PASSES and STREAK all read 3, inviting the reading that they are one thing.
"No stage declared — 3 runs unjudged" spends a card on a feature not opted into.

Proposal: a tooltip per metric, or drop to the three that change behaviour. And
give Mix Health an empty state that explains what declaring a stage would buy.

---

## D. Smaller, cheap (findings 1, 3, 4, 7, 20)

- **D1** *(1)* — the installer says `Next: alc init` after an upgrade.
  **Already fixed by alc itself during this E2E** — `86a3fe6`.
- **D2** *(20)* — the aborted verdict says edits are "in the working tree"; for
  an isolated run they are on a branch. My copy, my error.
- **D3** *(3)* — "Archetype Packs" arrives in the init output before it can mean
  anything, competing with the actual next step.
- **D4** *(4)* — the lint check is scaffolded commented-out pointing at an
  unpinned `ruff`, while this repo's CI pins `uvx ruff@0.15.21`. Reading the
  project's CI would beat guessing.
- **D5** *(7)* — a repair turn read the HOST project's manifest from inside its
  isolated worktree. Not a violation, but invisible to the operator.

---

## E. The prerequisite comes too late (finding 23)

### E1 — Say what you need BEFORE saying how to install
*Finding 23.*

`installation.mdx` gives the install command at word 35 and mentions that ALC
drives a coding CLI you must already have at word 270. The landing page names
Claude Code and Gemini but never says you need one of them.

Someone with neither installs, runs `alc init`, and gets `default_engine: mock`
— a no-op — then a first run that "succeeds" having changed nothing.

**DONE** — see below.

Proposal: one line above the install block on both the landing and the docs:
what you need on your machine before this is worth installing.

The second half of this proposal was withdrawn. I had asked for init to warn
when it falls back to mock; it already does, in those words, including that runs
will be no-ops. Only the docs and the landing needed changing.

Note: I expected the docs to front-load vocabulary and measured that they do
not (log #24). This is the real gap in that area; jargon in getting-started is
not.

---

## If only five things were fixed

1. ~~**A1** — the Inbox must not offer to Land work that never passed.~~ **done**
2. ~~**A4** — init must not scaffold a check that cannot pass in isolation.~~ **done**
3. ~~**A2** — find stacks below the root, or say plainly that you did not.~~ **done**
4. **B1** — put the JSON behind a flag.
5. **C1** — `alc ui` opens the project you are in.

The first three were the same promise: *verified* has to mean something. A3 went
in with them, because measuring coverage is what makes that promise checkable
rather than asserted. The last two are what makes the tool usable while it keeps
it.

### What building them changed about the proposals

- **A2 shipped narrower than proposed.** I planned live checks for subdirectory
  stacks. This file already had a rule — a check that would fail on a clean
  checkout is written commented — and `cd ui && npm test` needs an install in
  that directory. So they are scaffolded commented, named, with the reason. The
  checks still do not run; the blind spot is now written down instead of felt.
- **A2's instruction was wrong at first.** "Uncomment once dependencies are
  installed" implied one step. `resolve_checks` is a set PLUS a Blueprint's own
  checks, so a Blueprint with no `check_set:` never reaches it. Both steps are
  named now.
- **A3 nearly cried wolf.** Its first version flagged every unreferenced
  check_set, which fires on every project alc creates: the `python` set holds the
  check the Blueprints already declare inline. It now reports a set only when it
  contributes something nothing else runs.
- **A4 was misdiagnosed.** I wrote that init never scaffolds
  `worktree_provision`. It does, and deliberately skipped Python. The real error
  was the key: the block was keyed on the stack when the runner is what settles
  it — once a check reads `uv run`, the project has a `.venv` at its root.
