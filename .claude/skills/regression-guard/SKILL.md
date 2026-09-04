---
name: regression-guard
description: Verify the working tree introduced no regressions; if it did, dispatch the Opus regression-fixer agent (KISS, minimal diffs) to resolve them, then commit (English, Conventional Commits) and open an English PR whose title has no type prefix.
---

# Regression Guard

Run this after a batch of changes, before committing/shipping. It has four
phases; never skip one, never reorder them.

## 1. Establish what changed

```bash
git status --short
git diff origin/main...HEAD --stat   # committed work
git diff --stat                      # uncommitted work
```

Read the diff summary so failures in phase 2 can be attributed to a change —
a failure in code nobody touched is an environment problem, not a regression.

## 2. Run the full battery

All of it, even when "only the UI" changed — this repo's surfaces share
behavior:

```bash
uvx ruff@0.15.21 check src tests
uv run pytest -q
cd ui && npx vitest run && npm run build:alc && cd ..
```

If `docs-site/` was touched: `cd docs-site && npm run build && cd ..`.

Capture every failure VERBATIM (test id + assertion output). Never read `$?`
after a pipe; never probe with substrings the scaffold also contains.

## 3. Triage, then fix

Classify each failure:

- **Regression** — the changed code broke a behavior that should still hold.
- **Intended change** — a test pins the OLD behavior the batch deliberately
  reversed. The test gets a reasoned update (comment says what reversed and
  why), never a silent flip. If in doubt, ask the operator; do not guess.
- **Environment** — flaky/external. Re-run once to confirm before ignoring.

For the regressions, dispatch the `regression-fixer` agent (it runs on Opus
and is bound to KISS — minimal diffs, no refactors, no over-engineering):

```
Agent(subagent_type="regression-fixer",
      prompt=<the verbatim failure list, the introducing diff hunks, and the
              exact commands that reproduce each failure>)
```

When the agent reports, re-run phase 2 yourself — its green claim is not
yours until you reproduce it. At most two fixer rounds; still red after that
means stop and report to the operator with the honest state.

## 4. Commit and open the PR

Only when phase 2 is fully green.

**Commit** — English, Conventional Commits:

- `<type>(<scope>): <imperative, lowercase, ≤72 chars, no final period>`
- Body explains the WHY (the diff shows the what); wrap at ~72.
- `git add` by explicit path — never `-A`/`.`. No co-author trailers.

**PR** — English, via `gh pr create` from a dedicated branch:

- **Title**: NO type prefix. A short name that starts with a capital letter
  and reads like a headline — `Quiet loops and honest queue outcomes`, not
  `fix(ui): quiet loops…` and not `Fix the loops`. (Release PRs keep their
  own `Release X.Y.Z — …` format; that is the one exception.)
- **Body**: descriptive and thorough — the reviewer should need no other
  document. Cover, in sections: what changed and why (per finding/feature,
  not per file); what regressions phase 3 found and how each was resolved
  (including intended-change test updates, with their reasoning); what was
  validated and where (test counts, builds, live surfaces — name the device
  when the UI was validated on one); anything deliberately left out of
  scope. End with the repo's standard footer:

  `🤖 Generated with [Claude Code](https://claude.com/claude-code)`

Watch CI (`gh pr checks --watch`) and report the PR URL + CI state to the
operator. Merging stays the operator's call unless they said otherwise.
