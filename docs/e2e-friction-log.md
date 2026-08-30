# Friction log — using alc 0.44.2 on the alc repo
Persona: experienced developer, first real session with the tool.

## 1. [papercut] Update path ends with advice for a first install
WHERE: `curl ... | sh` output when alc was already installed
WHAT: it upgraded 0.44.1 -> 0.44.2 correctly, then printed
  `Next: alc init   (sets up .alc/ in a project)`
WHY: install and update are deliberately the same command. Someone updating
already has projects; being told to init one reads as if the update did not
recognise the existing install.

## 2. [BLOCKER] Stack detection is root-only, so a monorepo gets half a verdict
WHERE: `alc init` on this repo → "Detected Python — scaffolded real checks (pytest)."
WHAT: the repo has `ui/package.json` (603 tests) and `docs-site/package.json`.
Neither was found. `scaffold._marker_present` only tests `project_root / marker`,
never a subdirectory.
WHY: this is not a cosmetic miss. ALC's whole claim is that checks run before
anything is called done. On this project a change to the web UI would be
"verified" by pytest alone — which never touches it — and the run would report
"this project's checks passed". The one thing the tool must not do.
Any project keeping its frontend in a subfolder gets this, and that is the
common shape.

## 3. [papercut] "Archetype Packs" arrives before it can mean anything
WHERE: `alc init` output, line 4
  "Archetype Packs (test authoring, dead-code sweeps, dependency patrol, …) are
   available via `alc team hire <archetype>`. See: alc team list"
WHAT: three sentences into using the tool, a capitalised proper noun I have no
model for, offered as a next step alongside the actual next step.
WHY: the line competes with "Next: alc run chore ..." for attention, and loses —
but it costs a beat to decide it is not for me yet.

## 4. [stumble] The lint check is commented out, pointing at a different tool than CI
WHERE: `.alc/manifest.yaml` check_sets.python
  `# - name: lint` / `#   command: ["ruff", "check", "."]`
WHAT: correctly commented because `ruff` is not on PATH. But this repo's own CI
runs `uvx ruff@0.15.21 check src tests` — pinned, and no install needed.
WHY: the advice ("install it and uncomment") leads to an unpinned ruff that can
disagree with CI. On a repo that already tells you how it lints, init could read
that instead of guessing.

## 5. [BLOCKER] `alc lint` says "conformant" about a setup that cannot verify the project
WHERE: `alc lint` → "No violations found. Operator Layer is conformant."
WHAT: run immediately after the init in #2, on a layer whose only check is
pytest, in a repo where half the code is TypeScript.
WHY: lint validates the SHAPE of the Operator Layer, never whether the checks
reach the project. A newcomer reads "conformant" as "my setup is sound". There
is no surface anywhere that says "your checks touch 0 of your 603 frontend
tests". The tool's own guarantee depends on coverage it never examines.

## 6. [BLOCKER] The scaffolded check cannot pass in the isolation the tool recommends
WHERE: `alc init` wrote `command: ["uv", "run", "pytest", "-q"]`.
`alc run chore --isolate "..."` on that layer.
WHAT: attempt 0 edited the file and finished ok. The check then failed with
  `ModuleNotFoundError: No module named 'fastapi'`
  `Creating virtual environment at: .venv` / `Installed 18 packages`
In a fresh worktree `uv run` builds a NEW venv with base deps only. This repo's
tests need the `ui` extra; its own CI runs `uv sync --extra ui` first. The check
therefore passes in the main tree and fails in isolation, every time, for
reasons unrelated to the change.
WHY: `--isolate` is what the docs and the UI's beginner path both recommend, and
`init` scaffolds a check that is guaranteed to fail there. The failure is not
the user's change, so the Assurance Loop spends repair turns — real model time
and real money — chasing a phantom. Mine burned ~7 minutes on attempt 1 running
find/grep/ls before I killed it.
NOTE: `worktree_provision` exists for exactly this and `init` never scaffolds
it. Nothing warns that a check which passes here will fail there.

## 7. [stumble] The repair turn left the worktree looking for answers
WHERE: run log, attempt 1
WHAT: among dozens of find/grep calls inside the temp worktree, the engine read
  `/Users/guilherme.sousa/git/alc/.alc/manifest.yaml`
— the HOST project's manifest, outside its isolated copy.
WHY: isolation is sold as "your files stay as they are". Reads escaping the
worktree are not a violation of that, but they mean a repair can be informed by
state the run does not control, and the operator has no way to see that from the
Scorecard.

## 8. [stumble] Every run dumps its full report as JSON, unconditionally
WHERE: `_print_run_report` (cli.py:140) — `print(report.model_dump_json(indent=2))`
WHAT: after a good human summary (Status/Engine/Attempts/Scorecard), ~35 lines
of raw JSON follow. `alc run --help` has no `--json`, no `--quiet`. It is not
opt-in; it is the only mode.
WHY: the useful four lines scroll off the top on any real report. A person
reading their first run has to scan past a serialised Pydantic model to find out
what happened. Machine output belongs behind a flag, not in front of a human.

## 9. [stumble] 100 seconds of silence while a check runs
WHERE: terminal during `→ Verify (1 check(s))…`
WHAT: the report says `duration_s: 100.7` for the single check. During all of it
the terminal shows one line and nothing else. No check name, no elapsed, no dots.
WHY: on a first run with a real engine the Act phase is minutes and Verify is
another one or two, all of it silent. There is no way to tell "working" from
"hung" — I genuinely could not, which is why my first real run got killed at 10
minutes.

## 10. [stumble] Engine activity is shown, but truncated to keep the noise
WITHDRAWN AND REPLACED. My first version of this entry said the CLI hides engine
activity. That was wrong — I had only tested with the mock engine, which has no
activity to report. With a real engine the terminal streams:
    → claude-code working (model=claude-sonnet-4-6)…
      • Read: /private/var/folders/p6/rt1tk2pn37189vrg5y_7kwtc0000gp/T/alc
      • Edit: /private/var/folders/p6/rt1tk2pn37189vrg5y_7kwtc0000gp/T/alc
    → claude-code done (44s, $0.204)
The real defect is the truncation. Every line is cut at the same width, so all
of them show the identical useless prefix — the macOS temp directory — and the
one thing that varies, the filename, is what gets dropped. Four lines that could
have said "Edit: install.sh" all say "/private/var/folders/p6/…/T/alc".
WHY: this is the operator's only live view of what the engine is touching, and
it is truncated from the wrong end.

## 11. [papercut] The Scorecard's four words arrive unexplained on run one
WHERE: `Scorecard: span=1 passes=1 streak=1 touch=0`
WHAT: four invented metrics, no units, no legend, no pointer to what they mean.
WHY: `touch=0` on a run that changed nothing reads as neutral; on a run that
changed something I would not know if high or low is good. A first run is
exactly when a legend is worth its line.

## 12. [BLOCKER] `alc ui` ignores the project you are standing in
WHERE: `alc ui --port 8666`
WHAT: this directory IS an alc project — I ran `alc init` in it minutes ago. The
UI opened listing two unrelated projects registered earlier, and not this one.
To see the project I was in, I would have to open the switcher and type its
absolute path.
WHY: every other command is scoped to the cwd — `alc run`, `alc lint`,
`alc team` all act on the project you are in. `alc ui` alone reads a global
registry and ignores it. "cd into a project and start the tool" is the one
mental model the CLI teaches, and the UI breaks it at the door.
The multi-project registry is a deliberate design and a good one; the gap is
that the current directory is not part of it automatically.

## 13. [papercut] `alc run` succeeded but nothing told me where to review it
WHERE: end of a successful `alc run --isolate`
WHAT: the last line is
  "Isolated changes committed on branch: alc/run-042bb3e8 (review and merge from
   /Users/guilherme.sousa/git/alc)"
— correct and useful. But it is printed BELOW ~35 lines of JSON (#8), so on a
real terminal it is the only line that matters and the hardest to find.
WHY: the JSON dump does not just add noise, it buries the one actionable
sentence the run produces.

## 14. [BLOCKER] The Inbox offers to Land work that was never verified
WHERE: UI → Inbox, and `alc land`
WHAT: I interrupted a run at attempt 1. Its event log ends `run_aborted
{"reason": "interrupted"}` and its only check FAILED. The worktree still
committed 9 lines to `alc/run-bc253dd5`, and the Inbox lists it as
  "alc/run-bc253dd5 — TO LAND — run work ready to land   [Review] [Land] [Discard]"
identical in every way to `alc/run-042bb3e8`, which actually passed.
WHY: this is the exact failure ALC exists to prevent, and it comes with a
destructive button. "Ready to land" is asserted about work whose checks failed
and whose run never finished. An operator clearing an Inbox at speed merges it.
THE SIGNAL ALREADY EXISTS: `.alc/runs/` holds `alc-run-042bb3e8.report.json` and
NO report for bc253dd5 — because cli.py:886 archives the report only
`if report.success`. A branch with no report beside it never passed. The Inbox
does not look.

## 15. [stumble] The Dashboard never mentions the decisions waiting for you
WHERE: UI → Dashboard, with 2 branches awaiting a decision
WHAT: six cards — Scorecard, Engines, Recent runs, Mix Health, Audit, Schedule.
None says work is waiting. The only signal is a small "2" superscript on a rail
icon. "Mix Health: No stage declared" gets a full card; two pending merges get a
badge.
WHY: it is the only state on the screen that needs a human. Everything else is
reporting; this is the thing the human is FOR.

## 16. [stumble] Recent runs are indistinguishable from each other
WHERE: Dashboard → Recent runs
WHAT: five rows, each "run  20260830T041713-run-chore-in-d…  2m ago". The stem
is truncated mid-word and the task text is what got cut. Three of my five runs
were literally the same prefix.
WHY: the list exists to let you find a run. Every row looks the same, and the
part that would tell them apart is the part removed.

## 17. [papercut] Eight unexplained numbers on the Dashboard
WHERE: Scorecard card — SPAN 3, PASSES 3, STREAK 3, TOUCH 0, REPORTS 3, OK 3,
FAILED 0, NET LINES +7
WHAT: no legend, no tooltip, no units. SPAN and PASSES and STREAK are all 3,
which invites the reading that they are the same thing.
WHY: the CLI has the same four (#11) but the UI doubles it to eight and gives
them the most prominent card on the page.

## 18. [papercut] "unjudged" and "No stage declared" explain nothing
WHERE: Mix Health card — "No stage declared — 3 runs unjudged."
WHAT: two pieces of vocabulary, one sentence, no way in. Nothing says what a
stage is, why I would declare one, or what judging would give me.
WHY: it occupies a card on the primary screen to tell me a feature I have not
opted into is not running.

## 19. [BLOCKER — evidence for #14] The product already knows; the wrong view asks
WHERE: UI → Runs → the aborted run
WHAT: that view says exactly the right thing —
  "ABORTED"
  "Stopped before finishing. Nothing was reported as done."
while the Inbox and Branch Review, for the SAME work, say "ready to land" and
offer a Land button.
WHY: this is not missing information. It is information the product has, in a
view three clicks away, that the destructive surface never consults. Fixing #14
is wiring, not research.

## 20. [stumble] The aborted verdict describes the wrong place for isolated runs
WHERE: RunOutcome, aborted branch — "Any edits it had already made are still in
the working tree."
WHAT: this run was `--isolate`. Its edits are on `alc/run-bc253dd5`, not in the
working tree — the working tree was never touched, which is the whole point of
isolation.
WHY: it sends the operator to look in the wrong place, and it undercuts the
promise printed on the Start card two screens away ("Work happens on a separate
branch. Your files stay as they are"). Mine — I wrote this copy earlier in the
session without distinguishing the isolated case.

## 21. [papercut] `alc audit` is clean; `alc run` is not — the good pattern exists
WHERE: `alc audit` output
  Since: 7d ago / Tasks: 3 total, 3 ok, 0 failed / Scorecard (avg): … / Usage: …
WHAT: five readable lines, no JSON. The same tool that dumps a serialised model
after every run (#8) already knows how to print for a person.
WHY: makes #8 an inconsistency rather than a missing feature — the fix is to do
what audit does.

## 22. [BLOCKER — synthesis of #2, #5, #6] The promise is only as true as the checks
WHERE: UI → Start card, first line
  "ALC plans the work, runs it, and runs this project's own checks before
   calling anything done."
WHAT: on this repo those checks are pytest and nothing else, because init looks
only at the repo root (#2) and lint calls that layer "conformant" (#5). The
sentence stays literally true while meaning much less than a reader takes from
it: a change to any of 603 frontend tests' code is "verified" by a suite that
never loads it.
WHY: every other honesty fix in this product — the quarantine flag, the spike
verdict, the derived guarantee — was about not overclaiming. This is the same
class, one level down: the claim is about checks, and nothing measures whether
the checks reach the project.

---
# Measured, not guessed: the docs half

The target-user agent never delivered (five attempts across this session), so
the "read it as a stranger" half is missing. I know the project and cannot
un-know it. These two things are measurable regardless, so they are facts rather
than impressions.

## 23. [stumble] The engine prerequisite arrives 235 words after "install this"
WHERE: `getting-started/installation.mdx`
MEASURED:
  install command      — word 35
  "Pick an engine"     — word 270
  "does not ship a model" — word 274
WHAT: a reader is told to install, and only 235 words later that ALC drives a
coding CLI they must already have. The landing page never says it at all: it
names Claude Code and Gemini, but never that you need one.
WHY: someone installs, types `alc init`, and only then meets the requirement. If
they have neither CLI, init silently picks `mock` — a no-op engine — and their
first run "succeeds" having changed nothing.

## 24. [NOT A FINDING — the hypothesis was wrong]
I expected the getting-started docs to lead with philosophy. Measured, they do
not: words before the first command, and proprietary terms in that stretch —
  installation.mdx    58 words,   0 terms
  first-run.mdx       45 words,   1 term  (Operator Layer)
  checks.mdx          83 words,   2 terms
  introduction.mdx   388 words,   1 term  (Operator Layer)
The onboarding path is restrained. Recording this so the assumption is not
carried into the fixes: whatever else is wrong, jargon-front-loading in
getting-started is not it.
