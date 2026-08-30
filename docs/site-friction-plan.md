# Site friction — verification and plan

A second friction log (`FRICTION_LOG_REPORT.md`) read the **website**: landing,
`/docs`, and the getting-started path. The first one (`docs/e2e-friction-log.md`)
used the **tool**. The overlap is almost nil, which is why finishing the first
batch left this one untouched.

Before planning, every claim was re-checked against the repository as it stands.
Two did not survive that check, one table of counts does not reproduce, and one
of my own verdicts was wrong and is corrected below. They are listed first,
because a plan that fixes a problem the reader described inaccurately fixes the
wrong thing.

---

## Already closed

| # | Finding | Where |
|---|---|---|
| 2 | The engine requirement is discovered after installation | **E1**, `83cb1b1` — the landing now opens "ALC ships no model", and `installation.mdx` carries a `Before you install` section above the command |
| 18 | Scorecard metrics undefined | **C4**, `f130462` — *partially*. The CLI prints a direction legend and the UI defines all eight on hover. The **docs page** still carries the circular "Amount of work delivered per prompt — checks satisfied", and `Passes` was not renamed |

---

## Correction to this document

**#3 was verified WRONG the first time, by me.** I grepped `content/landing.mdx`,
found no `curl`, and reported the finding as not reproducing. The install command
does not live in the MDX — `<Install />` (`components/landing/Install.tsx`)
renders it. Seeing the page proved it:

- **Desktop:** the hero shows `curl -fsSL …/install.sh | sh`; the "Get started"
  section further down shows `uv tool install alc-runtime`. Two different
  commands, no signpost. **The finding is accurate as written.**
- **Mobile:** worse than reported. `<Install />` renders at every width, and
  below it a `sm:hidden` `Terminal` renders the MDX block — so a phone gets
  *both* commands stacked in the hero, then `uv tool install` a third time.

The lesson is the one this project keeps teaching: a content file is not the
page. Everything else in this document was checked against a running site or a
running binary; that one claim was checked against a source file, and it was the
one that was wrong.

**#3 belongs in Tier 2** — it is not a false claim, it is an unsignposted fork on
a stranger's first decision. Label one path primary. The curl-pipe-sh is the one
a cautious developer bounces off, and it is currently the one in the hero.

## Does not reproduce

**#17 — "Terminal output locked inside an image."** The demo is a **video**
(`/demo/alc-run.mp4`), not a raster, and it carries an accessible label ("A
recorded alc run: Act, Verify, and the checks passing"). On narrow screens the
hero already falls back to a **text** `Terminal` component. The substance
survives in a narrower form: that fallback shows the *commands*, and nowhere on
the landing is there selectable text of a run's **output** — the Act/Verify/
Repair lines and a Scorecard.

**#25 — "The slogan is repeated four times."** "on the loop, not in it" appears
in three files — landing, introduction, and `Logo.tsx`, where it is a label, not
prose. Two visible uses of a thesis sentence is not a mantra.

**#8's counts.** The vocabulary load is real, but the table is not. Measured
across `docs-site/content/`, `components/` and `app/`:

| Term | Reported | Actual |
|---|---|---|
| Blueprint | 89 | **124** |
| Assurance Loop | 49 | 27 |
| Policy Gate | 45 | 23 |
| Scorecard | 46 | 21 |
| Mandate | 33 | 15 |
| Operator Layer | 28 | 32 |
| Mix Health | 10 | 10 |

Half are inflated by roughly 2×; the headline term is understated by 40%. The
conclusion holds and is arguably stronger — `Blueprint` is a heavier tax than
reported — but the numbers should not be quoted.

---

## Tier 1 — It misleads (do first)

A reader who catches one overstatement starts discounting the true claims too.
These are the ones that cost credibility, and both are copy.

### T1.1 — Make the guarantee conditional, on the landing
*Findings 6, 7. Verified: both still present.*

The report says the gate "refuses" what it only warns about. Tested on a fresh
scaffold, it is wrong in both halves:

- a Blueprint with **zero** checks is an **error** — `alc lint` exits 1. The
  gate genuinely refuses, and the landing sentence is literally true;
- a Blueprint whose check is the scaffold's `["true"]` placeholder produces **no
  violation at all** — not a warn, nothing.

So "refuses" stays, because it is accurate. The real overstatement is sharper
than reported: the gate refuses an empty list and is silent about a check that
always passes, which is exactly what the scaffold ships.

**Done.** The Problem section now carries the condition 52 words *before* the
promise it qualifies (it was 771 words after, in my first attempt — measuring
caught it), the Gate step names what the gate cannot judge, and Get started
carries the action (`alc onboard`) rather than a second copy of the caveat.

**Follow-up worth considering, not done:** make `alc lint` warn when a
Blueprint's checks are all trivially-passing placeholders. It would put the
truth where the operator is, not only where the reader is. It fires on every
fresh project — which is correct here, unlike the false alarm this was nearly
built as in A3.

### T1.2 — State the cost ceiling in the getting-started path
*Finding 15. Verified: zero mentions of the repair budget in `first-run.mdx`.*

The core mechanic is re-invoking a model until checks pass. `max_repairs`
defaults to 3, so a run makes **up to four turns**, and the `feature` Blueprint
the docs hand you uses the `deep` tier. That number lives only in the Assurance
Loop concepts page.

**Done.** The first-run heads-up now leads with the ceiling and multiplies it by
the tier. The unattended guide says a drain processes *every* pending task, so
a cron pass costs *pending tasks × 4 turns* — bounded by how much you enqueue,
not by the drain.

---

## Tier 2 — It blocks a task

### T2.1 — Answer "what can I run?"
*Finding 13. Verified: no such command among the 34.*

`alc run chore "…"` teaches one Blueprint name and the CLI offers no way to
learn the others. `alc status` reports queue, failures, branches and loops — not
Blueprints. The only answer is `ls .alc/blueprints/`, which the docs never say.

Three options, in ascending cost:

1. Document `ls .alc/blueprints/` on the first-run page. Minutes; not a real fix.
2. Make a bare `alc run` (and an unknown Blueprint name) list what exists.
   Small, and it lands where the question is actually asked.
3. Add `alc blueprints`. A 35th command, consistent with `alc team list`.

**Recommendation: 2, plus 1.** The failure path is where a stranger meets this,
and a "no such Blueprint — you have: chore, bug, feature, plan" message answers
the question at the moment it is asked, without growing the CLI.

**Needs your call** on whether the CLI grows a command.

### T2.2 — `/docs` points at the wrong first page
*Finding 22. Verified: "Start with the installation guide" in `page.tsx`.*

The index is 24 undifferentiated links and one arrow at installation, skipping
the introduction. Less severe than when it was written — E1 put the engine
requirement on the installation page — but the introduction is still where the
product is explained, and people arriving from a link never see it.

**Cost:** one line of copy plus light grouping. **Mine to do.**

---

## Tier 3 — Naming (your decisions, not mine)

These are breaking or doc-wide. I can execute any of them; I should not pick.

### T3.1 — The `Loop` collision *(finding 11)*
`Assurance Loop`, `Autonomous Loop`, `alc loop`, `alc cycle` — and `cycle` runs
one iteration of a `loop` while `loop` repeats `cycle`. Verified: both commands
still exist. This lands squarely on the unattended tier, which is the pitch for
rung 2.

Renaming a CLI verb is a breaking change for anyone with a cron entry. Options:
rename the concept (`Autonomous Loop` → something else) and leave the verbs, or
rename `alc loop` → `alc repeat` with an alias. **Your call.**

### T3.2 — `Blueprint` (124 uses) and `Operator Layer` (32) *(findings 9, 10)*
My honest read, which differs from the report's:

- **Keep `Blueprint`.** It is load-bearing across CLI, UI, manifest keys and
  file paths. At 124 doc uses the rename cost now exceeds the tax, and
  "workflow" collides with `Flow`, which already exists.
- **Demote `Operator Layer`.** The concept is worth naming once; the capitalised
  proper noun on every operational line is not. `alc lint` saying "validates
  `.alc/`, not your source code" is strictly clearer. Keep the term in concepts,
  drop it from operational copy.

### T3.3 — The acronym *(finding 1)*
"Agentic Layer Compiler & Runtime" appears in `landing.mdx` and **nowhere else**
— zero doc pages. The docs open with "a control plane for agentic coding". The
first six words of the site are a name the project abandoned one click later,
and "Compiler" sends readers looking for a compilation step.

Cheapest of the three: drop it from the hero, keep "control plane". **Your call**
on whether the acronym is worth keeping at all.

---

## Tier 4 — Landing craft

### T4.1 — A transcript above the fold *(findings 16, 17 as corrected)*
~200 words of thesis precede any instruction. Not "no demo" — the video is
there — but no **selectable text** of a run's output. Paste a real
Act → Verify → fail → Repair → pass transcript with its Scorecard, as text,
above the fold. It is searchable, copy-pasteable, readable on a phone, and it
removes the need for a caption arguing the video is genuine.

The thesis is well written and earns its place in `introduction.mdx`.

### T4.2 — Papercuts
- **#5** "Three commands to a validated Operator Layer" over a five-line block.
  Verified. Say "four" or drop the number.
- **#4** "Two runtime dependencies" occupies the slot where a real constraint
  should live. "Needs `git`" is worth more.
- **#19** The ladder sells three rungs; concepts admits two need a thick
  Operator Layer first. One clause on the landing turns an overclaim into a
  roadmap.

---

## Tier 5 — Small, and cheap

- **#24** "Known rough edges" has exactly **one** bullet (verified) while real
  ones sit scattered as inline warnings. Collect them.
- **#20** `Mix Health` is used on the Scorecard page before the Archetypes page
  defines it. Verified. One link.
- **#21** `Grower` is marked *Partial* inside the table that introduces the five
  roles, using two more undefined terms. Verified. Move the caveat below the
  table.
- **#14** Optional quickstart step 3 introduces Primer, Trim and Context Budget —
  "the Trim half" implying a half the reader has not met. Verified. Drop the
  clause.
- **#23** Four labels for one referent: "unit of work", "Single Mandate",
  "Mandate", "run", "task".

---

## Suggested order

1. **T1.1, T1.2** — credibility, and both are copy. Half a day.
2. **T2.1, T2.2** — the two questions a stranger asks next.
3. **T3.3** — one line, once you decide about the acronym.
4. **T4.1** — the transcript; needs a recorded run to quote.
5. **T5** — a batch of small edits in one pass.
6. **T3.1, T3.2** — last, deliberately. Breaking changes deserve their own
   release, and the tiers above make the docs honest without touching a name.

Everything in tiers 1, 2, 4 and 5 is validated the same way the first batch was:
build the site, re-measure the specific claim, and check the rendered page in
Chrome and on the device.
