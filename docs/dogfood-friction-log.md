# Dogfood friction log — alc developing alc

The target user: developing alc itself, in `/Users/guilherme.sousa/git/alc`,
driving the work through alc's own CLI and UI — the UI operated from a physical
Android phone at 411px. This began where the first two friction studies ended:
every previously recorded gap closed, release 0.45.0 out.

## What was exercised, end to end

Wired the repo's own Operator Layer for real (it was scaffold-only — see
finding 1), then ran a genuine task through the whole loop **from the phone**:
StartWork → engine turn → Assurance Loop repair → cancel → Inbox showing
UNVERIFIED → the A1 warning dialog → Land → operator verification on the
device. The task was itself a UI defect found minutes earlier by using the
product: the Problems panel squeezing messages into a strip at phone widths.

Working, observed on real work: the B2 check narration in the run feed; rule
16's warns rendering in the Problems tab with zero UI changes; the A1
unverified badge, reason and confirm dialog; landing from the phone cleaning up
the branch; the D5 `⇱ outside the workdir` marker live in the activity feed.

## Findings

### 1. [dogfood] alc's own Operator Layer did not follow alc's own advice
`alc lint` on this repo reported (via A3) that nothing reached `ui/` or
`docs-site/` — 630 frontend tests invisible to every run — and the commented
lint check pointed at unpinned `ruff` while CI pins `ruff@0.15.21` (the exact
D4 trap). Fixed here: one `project` check_set mirroring CI, including
`--extra ui` on pytest (a plain `uv run` sync in a worktree drops the extra and
tests/ui loses fastapi — learned on this repo during C4).

### 2. [stumble] `alc checks audit` proposes a duplicate of a check it cannot recognise
With the `project` set already running `uv run --extra ui pytest -q`, the audit
proposes creating a NEW `python` set with `uv run pytest -q` — a worse duplicate
(no extra, no pin). The identity test compares exact invocations, so any
argv variation makes an existing check invisible to it.

### 3. [stumble] A missing provision fails with the tool's error, not the cause
With `worktree_provision` absent (operator error, see 6), the isolated run's
Node checks failed with "This is not the tsc command you are looking for" and
ERR_MODULE_NOT_FOUND — npx fetching strays because node_modules did not exist
in the worktree. Nothing connected the failure to its cause. When a shell check
fails inside a worktree and its cwd contains a gitignored, unprovisioned
directory that exists in the main tree, one hint line ("ui/node_modules exists
in your project but is gitignored and not in worktree_provision") would turn a
cryptic wall into a fix. The engine then burned a repair turn on an environment
problem it could never fix.

### 4. [BLOCKER] The UI's Cancel breaks the promise the CLI's Ctrl-C keeps
D2 (998ef9d) made an interrupted isolated run COMMIT its work to the branch and
say so — in the CLI, the UI verdict, and the docs. The UI's Cancel goes through
`ExecManager.cancel`: SIGTERM, then **SIGKILL after 5 seconds**. The worktree's
exit-commit generates its message with an ENGINE call, which takes longer than
5s — so the kill lands mid-generation. Observed result: a leaked worktree, an
empty branch pointing at main (so `merged: true`, invisible in the Inbox), and
the engine's work sitting uncommitted in the leak. The same surface-divergence
shape as the original A1: two paths, one promise, one keeps it.

Fix directions, not exclusive: on the abort path use the static fallback commit
message (an aborted run does not need an engine-authored one — this also makes
CLI Ctrl-C faster and engine-free); and/or have cancel's grace wait for the
exit-commit rather than a wall-clock 5s.

### 5. [stumble] Recovering the orphaned work took git surgery
`git -C <leaked-worktree> commit`, `git worktree remove --force`, then the
Inbox flow. A user who cannot name those commands loses the work the product
promised to keep.

### 6. [note, operator error with a lesson] A careless manifest edit deleted
`worktree_provision` wholesale and nothing said so. Provisions are optional, so
lint stayed green while every future isolated run silently lost its deps. A
coverage-style advisory (A3's shape) could notice: Blueprints whose checks cd
into directories with gitignored dep dirs, and no provision naming them.

### 7. [verified working] The engine's fix needed the operator's eye — by design
The landed change made the message span `shrink-0`: rule on its own line ✓, but
the message became a 1780px single line scrolling inside a 411px panel. vitest
and tsc passed; only measuring on the device caught it. "ALC verified that it
builds and your checks pass; it did not verify that it is right. Read the
diff." The tagline earned its keep; Touch went to 1, honestly.
