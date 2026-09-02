# cli.py — argparse entrypoint for ALC.
# Provides subcommands: `alc init` (supports --setup and --stage), `alc onboard`
# (harvest a project's own checks into check_sets), `alc lint`,
# `alc run`, `alc spike`, `alc flow`, `alc tick`, `alc retry`, `alc land`
# (supports --push/--pr), `alc discard`, `alc explore`, `alc compare`,
# `alc adopt`, `alc conduct`, `alc enqueue`, `alc primer`, `alc new`, `alc team`,
# `alc prompts`, `alc cycle`, `alc loop`, `alc specialist`, `alc setup`,
# `alc status`, `alc runs`, `alc audit`, `alc checks`, `alc metrics`,
# `alc schedule`, `alc ui`, `alc signal`, `alc serve`, `alc artifacts`.
from __future__ import annotations

import argparse
import sys
from pathlib import Path


class _ResilientStderr:
    """Wrap a stream so PROGRESS writes never crash the work on a closed reader.

    When ALC runs as a subprocess (the web IDE's exec, a cron drain) and the read
    end of stderr closes mid-run — a cancelled exec, a disconnected client — a
    plain ``print(..., file=sys.stderr)`` raises BrokenPipeError. Unguarded, that
    propagates out of an engine turn and fails the task with a spurious traceback
    (which then becomes a retry's "feedback"). Swallowing the write error keeps a
    broken progress pipe from ever failing the actual work.
    """

    def __init__(self, wrapped: object) -> None:
        self._wrapped = wrapped

    def write(self, s: str) -> int:
        try:
            return self._wrapped.write(s)
        except (BrokenPipeError, OSError):
            return len(s)

    def flush(self) -> None:
        try:
            self._wrapped.flush()
        except (BrokenPipeError, OSError):
            pass

    def __getattr__(self, name: str) -> object:
        return getattr(self._wrapped, name)


def _find_operator_layer() -> Path:
    """Return the .alc/ directory, searching from cwd upward."""
    cwd = Path.cwd()
    for candidate in [cwd, *cwd.parents]:
        alc_dir = candidate / ".alc"
        if alc_dir.is_dir():
            return alc_dir
    # Fall back to cwd/.alc (will fail with a clear error if it does not exist).
    return cwd / ".alc"


def _warn_if_dirty_tree(project_root: Path, allow_dirty: bool, command: str) -> None:
    """Preflight NOTICE for an autonomous run: warn on a dirty tree, then proceed.

    `alc cycle`, `alc loop`, and `alc tick` are SAFE to run on the operator's real,
    dirty repo — the run commits only what IT produces, never the operator's own
    uncommitted work; the tree stays under the operator's sole control. Concretely:
    the plan replenish commits only the planner's own paths, and a serial committing
    demand does not run blindly — it is stopped by the flow-level clean-tree guard,
    which aborts a committing Flow that finds uncommitted non-``.alc/`` work before it
    runs any stage. So a dirty tree can, at worst, make a serial committing demand
    fail VISIBLY; it can never sweep work-in-progress into a commit. (Isolated demands
    — ``isolate: true``, or automatic when ``drain.concurrency > 1`` — run in a
    worktree cut fresh from HEAD and are unaffected either way.)

    Serial NON-committing work (a specialist demand, or a commit-disabled flow) still
    runs in place, so the engine's edits mingle with the operator's WIP in the working
    tree — but that is only interleaving, not a commit-sweep, and it was already the
    behaviour under the prior ``--allow-dirty`` opt-in.

    Because proceeding risks at most a visible failure and never data loss, the old
    hard abort is now a non-blocking warning. ``allow_dirty`` therefore no longer
    changes WHETHER the run happens — it only SUPPRESSES this notice (the name is kept
    for backward compatibility). A future strict ``--require-clean`` opt-in could
    restore a hard block for operators who want one, but that is intentionally out of
    scope here.

    Reuses the ``has_non_alc_changes`` predicate — the SAME one the flow-level guard
    uses — so a change confined to ``.alc/`` (control-plane state) never warns, and an
    off-git workdir is a graceful no-op (no repo means no WIP, so nothing to notice).
    """
    if allow_dirty:
        return

    from alc.commit import has_non_alc_changes

    if not has_non_alc_changes(project_root):
        return

    print(
        f"[WARN] {command}: the working tree has uncommitted changes outside .alc/. "
        "Proceeding — an autonomous run commits only what it produces, never your "
        "uncommitted work; the working tree stays under your control. Serial "
        "committing demands still require a clean tree and will abort themselves; "
        "prefer an isolated drain (drain.concurrency > 1 or isolate: true). Pass "
        "--allow-dirty to silence this notice.",
        file=sys.stderr,
    )


def _validate_tier(manifest, tier: str | None) -> str | None:
    """Validate that *tier* exists in manifest.compute_tiers.

    Returns an error message string when the tier is unknown, or None when
    the tier is valid (or when tier is None, meaning no override was requested).
    """
    if tier is None:
        return None
    if tier not in manifest.compute_tiers:
        available = ", ".join(sorted(manifest.compute_tiers))
        return f"unknown compute tier '{tier}'; available: {available}"
    return None


# "What can I run?" is the first question after a first successful run, and the
# CLI had no answer to it: `alc run` teaches ONE Blueprint name, `alc status`
# reports queue and branches but not Blueprints, and naming one that does not
# exist raised a bare FileNotFoundError traceback. The listing lives here, on the
# failure path, because that is where a stranger asks.
def _list_units(directory: "Path", suffix: str) -> list[tuple[str, str]]:
    """Return ``(name, purpose)`` for every unit file in *directory*, sorted.

    The purpose is read from YAML front-matter (Markdown) or a top-level
    ``purpose:`` key (YAML), best-effort: an unreadable or purpose-less unit
    still lists, with an empty purpose. Discovery must never fail on a malformed
    neighbour.
    """
    if not directory.is_dir():
        return []
    units: list[tuple[str, str]] = []
    for path in sorted(directory.glob(f"*{suffix}")):
        purpose = ""
        try:
            # Blueprints carry `purpose:`, Flows and Specialists `description:`.
            # Both, so one listing serves every kind without a per-kind branch.
            for line in path.read_text().splitlines()[:20]:
                for key in ("purpose:", "description:"):
                    if line.startswith(key):
                        purpose = line.split(":", 1)[1].strip().strip("\"'")
                        break
                if purpose:
                    break
        except (OSError, UnicodeDecodeError):
            # UnicodeDecodeError is a ValueError, not an OSError: a non-UTF-8
            # neighbour would otherwise take the whole listing down with it.
            pass
        units.append((path.stem, purpose))
    return units


def _print_units(kind: str, directory: "Path", suffix: str, *, stream=None) -> None:
    """Print what this project has of *kind*, aligned, with each unit's purpose."""
    out = stream if stream is not None else sys.stdout
    units = _list_units(directory, suffix)
    if not units:
        print(f"This project has no {kind}s. Create one with `alc new {kind} <name>`.", file=out)
        return
    width = max(len(name) for name, _ in units)
    print(f"{kind.capitalize()}s in this project:", file=out)
    for name, purpose in units:
        print(f"  {name.ljust(width)}  {purpose}".rstrip(), file=out)


def _no_such_unit(kind: str, name: str, directory: "Path", suffix: str) -> int:
    """Report an unknown unit by name, then list the ones that exist. Exit code 1.

    Replaces a FileNotFoundError traceback, which named the path it could not
    open and nothing a reader could act on.
    """
    print(f"[ERROR] no such {kind}: '{name}'", file=sys.stderr)
    _print_units(kind, directory, suffix, stream=sys.stderr)
    return 1


# The Scorecard's four words are invented, and a first run is exactly when that
# matters: `touch=0` on a run that changed nothing reads as neutral, and nothing
# on screen says whether high or low is good. One line, under the numbers,
# carrying the part you cannot act without — the direction.
# Direction only, not definitions: what the reader cannot act without is which
# way is good, and the four meanings live in the docs and the UI's own tooltips.
# Kept under 80 columns so it never wraps into the ragged mess it is fixing.
_SCORECARD_LEGEND = "           good: span ↑  passes ↓  streak ↑  touch ↓ (touch 0 is the goal)"


def _print_scorecard(scorecard) -> None:
    """Print the Scorecard line plus its one-line legend."""
    print(
        f"Scorecard: span={scorecard.span} passes={scorecard.passes} "
        f"streak={scorecard.streak} touch={scorecard.touch}"
    )
    print(_SCORECARD_LEGEND)


def _print_run_report(report, as_json: bool = False) -> None:
    """Print a RunReport: the human summary, or the full JSON under `--json`.

    The JSON used to follow the summary unconditionally — about thirty-five lines
    of serialised model after the four that say what happened, with the one
    actionable sentence a run produces ("Isolated changes committed on branch…")
    printed below all of it. `alc audit` already showed the better shape: five
    readable lines and no dump.

    --json REPLACES the summary rather than adding to it, matching `alc lint`
    and `alc land`. The report is also archived to runs/ either way, so nothing
    that wanted the data has lost it.
    """
    if as_json:
        print(report.model_dump_json(indent=2))
        return
    status = "SUCCESS" if report.success else "FAILED"
    print(f"Status:   {status}")
    print(f"Engine:   {report.engine}")
    print(f"Attempts: {report.scorecard.passes}")
    _print_scorecard(report.scorecard)
    if report.changed_files:
        print("Changed files:")
        for path in report.changed_files:
            print(f"  {path}")
    if report.warnings:
        print("Warnings:")
        for w in report.warnings:
            print(f"  [WARN] {w}")


def _print_flow_report(report, as_json: bool = False) -> None:
    """Print a FlowReport: the human summary, or the full JSON under `--json`.

    Same contract as `_print_run_report`.
    """
    if as_json:
        print(report.model_dump_json(indent=2))
        return
    status = "SUCCESS" if report.success else "FAILED"
    print(f"Flow:     {report.flow}")
    print(f"Status:   {status}")
    print(f"Engine:   {report.engine}")
    _print_scorecard(report.scorecard)
    print()
    for stage_report in report.stages:
        stage_status = "SUCCESS" if stage_report.success else "FAILED"
        print(
            f"  {stage_report.blueprint} -> {stage_status} "
            f"(passes={stage_report.scorecard.passes})"
        )
        for w in stage_report.warnings:
            print(f"    [WARN] {w}")


def _print_isolation_result(wt) -> None:
    """Print the post-run isolation summary (committed branch or no-op)."""
    if wt.committed:
        print(
            f"Isolated changes committed on branch: {wt.branch} "
            f"(review and merge from {wt._repo_root})"
        )
    else:
        print("No changes were made; nothing to isolate.")


def _emit_isolation_result(run_log: "Path", wt) -> None:
    """Record which branch the isolated work landed on, into the run's own log.

    The branch name is only known once the worktree has exited, which is after
    the run's own binding closed — so rebind (bind_run_log is reentrant and this
    is the same path) and append. Without this the UI can tell an operator their
    change is committed but not where to read it: the branch is
    ``alc/<label>-<random>``, unguessable from the run alone.
    """
    from alc.events import bind_run_log, emit

    with bind_run_log(run_log):
        emit("isolation_finished", committed=wt.committed, branch=wt.branch if wt.committed else None)


def _print_skill_result(path: "Path", changed: bool, version: str, engine: str) -> None:
    """Print the outcome of an install_skill() call to stdout."""
    if changed:
        print(f"Installed/updated the ALC skill for {engine} at {path} (alc {version})")
    else:
        print(f"ALC skill for {engine} already up to date at {path} (alc {version})")


def _print_variant_table(rows: list[dict]) -> None:
    """Print one block per variant (`alc explore` / `alc compare`): branch, checks,
    scorecard, cost/usage, and diffstat — the shape ``variant_row`` builds.
    """
    for i, row in enumerate(rows, start=1):
        status = "SUCCESS" if row["success"] else "FAILED"
        header = f"Variant {i}  branch={row['branch']}"
        if row["engine"]:
            header += f"  engine={row['engine']}"
        if row["tier"]:
            header += f"  tier={row['tier']}"
        print(header)
        print(f"  Status:    {status}")
        # The Compare surface marks branch liveness (`mark_live`); explore rows omit
        # it. Guarded on key presence (like the `"diff" in row` block below) so
        # explore output is byte-for-byte unchanged. A resolved variant (branch gone)
        # is history, not an error — the State line just says so.
        if "live" in row:
            state = "live" if row["live"] else "resolved (branch gone — adopted or discarded)"
            print(f"  State:     {state}")
        print(f"  Checks:    {row['checks']}")
        sc = row["scorecard"]
        if sc:
            print(
                f"  Scorecard: span={sc['span']} passes={sc['passes']} "
                f"streak={sc['streak']} touch={sc['touch']}"
            )
        usage = row["usage"]
        if usage:
            print(
                f"  Usage:     input={usage['input_tokens']} output={usage['output_tokens']} "
                f"cost_usd={usage['cost_usd']}"
            )
        ds = row["diffstat"]
        if ds:
            print(
                f"  Diffstat:  +{ds['adds']}/-{ds['dels']} ({ds['files_deleted']} file(s) deleted)"
            )
        # The full unified diff, present ONLY under `alc compare --diff` — the key
        # is absent for `explore`/plain `compare`, so those blocks render exactly
        # as before (byte-for-byte; no existing test moves). None = the branch is
        # gone (already adopted/discarded); "" = it exists but changes nothing.
        if "diff" in row:
            print("  Diff:")
            diff_text = row["diff"]
            if diff_text is None:
                print("    (no diff available — branch missing)")
            elif diff_text == "":
                print("    (no changes vs current branch)")
            else:
                print(diff_text.rstrip("\n"))
                if row.get("diff_truncated"):
                    print(f"  [diff truncated at {len(diff_text)} chars]")
        print()


def cmd_setup(args: argparse.Namespace) -> int:
    """Run `alc setup [--engine NAME]`: install/update the user-level editor skill."""
    from alc.setup_skill import _resolve_version, install_skill

    try:
        path, changed = install_skill(engine=args.engine)
    except ValueError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"[ERROR] could not install the ALC skill: {exc}", file=sys.stderr)
        return 1

    _print_skill_result(path, changed, _resolve_version(), args.engine)
    return 0


# Pack combo `alc init --stage NAME` hires — sugar over `alc team hire`, not a
# new install path. `stage` itself has ZERO runtime effect; it only selects
# which packs get hired at init time.
_STAGE_PACKS: dict[str, list[str]] = {
    "pre-pmf": ["prototyper", "builder", "sweeper"],
    "growth": ["builder", "sweeper", "grower", "maintainer"],
    "strong-pmf": ["sweeper", "grower", "maintainer", "builder"],
}


def _install_stage_packs(project_root: Path, stage: str, force: bool) -> None:
    """Hire every pack in `_STAGE_PACKS[stage]`; never hard-fails.

    Additive, mirroring `alc team hire`'s own contract: each pack's MISSING files
    are written and existing ones kept (so a stage that overlaps an already-hired
    pack, or a re-run, tops up new files instead of refusing). `force` overwrites
    ALL of a pack's files. A pack not yet shipped (a later wave) is reported
    plainly and skipped rather than raising.
    """
    from alc.intake import load_manifest
    from alc.packs import PACKS, pack_files, retarget_pack_content, split_pack_files
    from alc.scaffold import detect_stacks

    stacks = detect_stacks(project_root)
    # The scaffold this runs right after always writes a manifest, but this
    # helper "never hard-fails" — a missing/unreadable one just skips the
    # check_set retargeting (None -> no-op), it never blocks the hire.
    try:
        manifest = load_manifest(project_root / ".alc")
    except Exception:
        manifest = None
    check_sets = manifest.check_sets if manifest is not None else None
    print(f"Stage '{stage}':")
    for archetype in _STAGE_PACKS[stage]:
        if archetype not in PACKS:
            print(f"  {archetype}: not available yet (a later wave adds this pack).")
            continue

        if force:
            # The one destructive path: overwrite every pack file.
            files, _ = retarget_pack_content(pack_files(archetype, stacks), check_sets)
            for rel_path, content in sorted(files.items()):
                target = project_root / rel_path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content)
            print(f"  {archetype}: hired ({', '.join(sorted(files))})")
            continue

        missing, present = split_pack_files(
            archetype, stacks, project_root, check_sets=check_sets
        )
        for rel_path in sorted(missing):
            target = project_root / rel_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(missing[rel_path])

        if not missing:
            print(
                f"  {archetype}: already fully hired "
                f"({len(present)} file(s)); nothing to add."
            )
        else:
            line = f"  {archetype}: hired (added {', '.join(sorted(missing))})"
            if present:
                line += f"; kept {len(present)} existing"
            print(line)


def cmd_init(args: argparse.Namespace) -> int:
    """Run `alc init [--force] [--setup] [--stage pre-pmf|growth|strong-pmf]`.

    Scaffolds a default Operator Layer into cwd. `--stage` additionally hires the
    pack combo for that stage's mix (`_STAGE_PACKS`) via the same file-writing
    contract as `alc team hire`. Without it, only a discovery hint is printed —
    no pack is installed unless explicitly asked (opt-in byte-identical `init`).
    """
    from alc.scaffold import (
        detect_ci_config,
        detect_default_engine,
        detect_nested_stacks,
        detect_stack,
        scaffold,
    )

    project_root = Path.cwd()
    try:
        created = scaffold(project_root, force=args.force)
    except FileExistsError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1

    print("Initialised .alc/ (the Operator Layer):")
    for path in created:
        print(f"  {path}")

    # Say which engine init picked (same probe scaffold() used), so nobody
    # discovers a mock no-op run the hard way.
    engine = detect_default_engine()
    if engine == "mock":
        print(
            "Engine: mock — no engine CLI (claude, gemini) found on PATH. Runs are "
            "no-ops until you install one and set `default_engine` in .alc/manifest.yaml."
        )
    else:
        binary = "claude" if engine == "claude-code" else "gemini"
        print(f"Engine: {engine} (`{binary}` found on PATH).")

    stack_label, checks_block = detect_stack(project_root)
    if stack_label is not None:
        # Derive a short description of the real checks from the stack label.
        _stack_checks = {
            "Go": "go build, go vet",
            "Python": "pytest",
            "Node": "npm test",
            "Rust": "cargo check",
            "Ruby": "bundle exec rspec",
            "PHP": "composer test",
            "Maven": "mvn -q test",
            "Gradle": "./gradlew test",
            "Elixir": "mix test",
            ".NET": "dotnet build, dotnet test",
        }
        checks_desc = _stack_checks.get(stack_label, "real checks")
        # detect_stack renders a check whose binary is off PATH COMMENTED OUT (a
        # live check that 127s on a clean checkout cannot be law). Keep the message
        # honest: a smoke fallback in the block means EVERY detected check was off
        # PATH; a lone `# - name:` means some were.
        all_off_path = "- name: smoke" in checks_block
        some_off_path = "# - name:" in checks_block
        if all_off_path:
            # When the project itself can satisfy the gap (a declared dev
            # dependency, or an env manager that is not installed), say exactly
            # that instead of the generic "install them".
            hint = None
            if stack_label == "Python":
                from alc.pydeps import resolve_python_checks, unavailable_hint

                [(_name, command)] = resolve_python_checks(
                    [("test", ["pytest", "-q"])], project_root
                )
                hint = unavailable_hint(project_root, command)
            if hint is not None:
                print(
                    f"Detected {stack_label}, but its checks ({checks_desc}) were not "
                    f"on PATH — scaffolded them commented out with a smoke placeholder. "
                    f"Hint: {hint}, then uncomment in .alc/blueprints/."
                )
            else:
                print(
                    f"Detected {stack_label}, but its checks ({checks_desc}) were not on "
                    "PATH — scaffolded them commented out with a smoke placeholder. "
                    "Install them and uncomment in .alc/blueprints/, or run `alc onboard` "
                    "to adopt the checks your project already declares."
                )
        elif some_off_path:
            print(
                f"Detected {stack_label} — scaffolded real checks ({checks_desc}); "
                "some were not on PATH and were commented out (see .alc/blueprints/)."
            )
        else:
            print(f"Detected {stack_label} — scaffolded real checks ({checks_desc}).")
    else:
        # No stack detected: the scaffold left only the ["true"] smoke placeholder.
        # Say so loudly — ALC's guarantees are only as strong as the checks wired in.
        print(
            "No known stack detected — scaffolded a placeholder smoke check. "
            "ALC verifies only what your checks verify: add real checks to "
            ".alc/manifest.yaml check_sets, then run `alc checks audit` — or run "
            "`alc onboard` to harvest this project's own checks (Makefile targets, "
            "package.json scripts, …) into check_sets."
        )

    # A commented-out check is an instruction to install a tool and uncomment,
    # and that instruction leads to an UNPINNED tool. This repo's own CI runs
    # `uvx ruff@0.15.21`, so following the advice would install a ruff that can
    # disagree with the pipeline that actually gates the project. alc does not
    # parse CI configs (harvest.py keeps that deliberately out of scope), so this
    # names the file and stops — an authoritative source the operator can read
    # beats a guess dressed up as one.
    ci_config = detect_ci_config(project_root)
    if ci_config is not None:
        print(
            f"This project already runs checks in {ci_config} — prefer the commands "
            "it uses (they are usually version-pinned) over the ones scaffolded "
            "above. `alc onboard` adopts the ones ALC can read."
        )

    # A stack one level down is invisible to the root scan, so its code would be
    # "verified" by checks that never load it — the tool's central promise made
    # true only in the letter. The manifest now carries them commented out; this
    # is where the operator finds out they exist.
    nested = detect_nested_stacks(project_root)
    if nested:
        named = ", ".join(f"{label} in {sub}/" for sub, label, _set, _checks in nested)
        print(
            f"Also found {named} — NOT covered by the checks above. "
            "Scaffolded commented-out in .alc/manifest.yaml check_sets; uncomment "
            "once those directories have their dependencies installed."
        )

    if args.stage:
        _install_stage_packs(project_root, args.stage, args.force)
    else:
        # Deferred on purpose, and phrased as deferred. This used to open with
        # a capitalised proper noun three sentences into first contact, offered
        # alongside the real next step — so it competed with `Next:` and lost,
        # but cost a beat to decide it was not for you yet.
        print(
            "Optional, later: alc team list — prebuilt agent teams for test "
            "authoring, dead-code sweeps and dependency patrol."
        )

    if args.setup:
        from alc.setup_skill import _resolve_version, install_skill

        try:
            skill_path, changed = install_skill(engine=args.engine)
        except ValueError as exc:
            print(f"[ERROR] {exc}", file=sys.stderr)
            return 1
        except Exception as exc:
            print(f"[ERROR] could not install the ALC skill: {exc}", file=sys.stderr)
            return 1
        _print_skill_result(skill_path, changed, _resolve_version(), args.engine)

    # ONE concrete next action, always the last line — the golden path is a
    # first real run, or installing an engine when init had to fall back to mock.
    if engine == "mock":
        print(
            "Next: install an engine CLI (claude or gemini), set `default_engine` in "
            '.alc/manifest.yaml, then: alc run chore "<a small, well-scoped task>"'
        )
    else:
        print('Next: alc run chore "<a small, well-scoped task>"')

    return 0


def _isatty() -> bool:
    """Whether stdout is an interactive terminal — a testable seam.

    Isolated so a non-interactive shell (a pipe, the web IDE's exec) is never
    prompted, and so tests can flip interactivity deterministically.
    """
    return sys.stdout.isatty()


def _hired_archetypes(project_root: Path) -> list[str]:
    """The Archetype Packs currently hired (any of their files present on disk).

    A thin wrapper over `packs.hired_archetypes` — the shared membership test also
    used by `_team_roster` and the web UI roster — so `alc onboard`'s stage
    team-hints match exactly what `alc team list` reports.
    """
    from alc.packs import hired_archetypes

    return hired_archetypes(project_root)


def _print_onboard_apply(result) -> int:
    """Print an onboard ApplyResult and return its exit code.

    A blocked apply (validate-before-persist failed, nothing written) prints the
    violations to stderr and returns 1; a clean apply (or no-op) prints what was
    written and returns 0.
    """
    if result.violations:
        print("[ERROR] onboarding blocked — nothing was written:", file=sys.stderr)
        for v in result.violations:
            tag = "[ERROR]" if v.severity == "error" else "[WARN] "
            print(f"{tag} [{v.rule}] {v.message}", file=sys.stderr)
        return 1

    if not result.applied:
        for note in result.notes:
            print(note)
        return 0

    print("Applied:")
    if result.sets_added:
        print(f"  check_sets added: {', '.join(result.sets_added)}")
    if result.blueprints_opted_in:
        print(f"  blueprints opted in: {', '.join(result.blueprints_opted_in)}")
    if result.stage_set:
        print("  stage set")
    for note in result.notes:
        print(f"  note: {note}")
    return 0


def cmd_onboard(args: argparse.Namespace) -> int:
    """Run `alc onboard [--dry-run] [--yes] [--json] [--stage NAME]`.

    The follow-up to `alc init`, not a scaffolder: it HARVESTS the checks this
    project already declares (Makefile targets, package.json scripts, …) and
    PROPOSES adopting them into a `project` check_set — propose-then-approve, so
    nothing is written without approval. Requires an existing `.alc/` operator
    layer (located via `_find_operator_layer`, same as every other command).

    Modes (non-interactive first): `--json` emits the proposal as JSON and writes
    nothing; `--dry-run` prints the preview and writes nothing (also the default
    when stdout is not a TTY and `--yes` was not passed — a non-interactive shell
    is never prompted); `--yes` applies the full proposal non-interactively.
    Interactively (a TTY, no `--yes`) the checks, blueprint opt-ins, and
    stage-and-team sections are each independently approvable — a "no" skips that
    section, never aborts the command.
    """
    from dataclasses import asdict, replace

    from alc.harvest import harvest
    from alc.intake import load_all_blueprints, load_manifest
    from alc.onboard import apply as onboard_apply
    from alc.onboard import build_proposal, render_preview

    operator_layer = _find_operator_layer()
    project_root = operator_layer.parent
    # Precondition: an existing `.alc/`. A missing manifest raises the same
    # FileNotFoundError every other command surfaces — `alc onboard` follows
    # `alc init`, it does not scaffold.
    manifest = load_manifest(operator_layer)
    blueprints = load_all_blueprints(manifest, operator_layer)

    manifest_raw = (operator_layer / "manifest.yaml").read_text()
    blueprints_dir = operator_layer.parent / manifest.blueprints_dir
    blueprints_raw: dict[str, str] = {}
    for bp in blueprints:
        bp_path = blueprints_dir / f"{bp.name}.md"
        if bp_path.is_file():
            blueprints_raw[bp.name] = bp_path.read_text()

    hired = _hired_archetypes(project_root)
    harvest_report = harvest(project_root)

    # --assist (opt-in): spend ONE bounded engine turn to propose the checks the
    # deterministic harvest missed. Never automatic — cost is the operator's choice.
    # A None result (engine unavailable/timeout/unparseable) degrades to harvest-only.
    assist = getattr(args, "assist", False)
    engine_proposal = None
    if assist:
        from alc.onboard import engine_assist

        engine_proposal = engine_assist(project_root, harvest_report, operator_layer)

    proposal = build_proposal(
        manifest,
        project_root,
        blueprints,
        harvest_report,
        stage=args.stage,
        hired_archetypes=hired,
        engine_proposal=engine_proposal,
    )

    # --json: the UI's machine-readable feed. Print the proposal, write nothing.
    if args.json:
        from alc.output import emit_json

        emit_json(asdict(proposal))
        return 0

    # Honest, one-line note about the engine layer. When assist ran but produced
    # nothing, say so and continue harvest-only. When it was NOT used and the
    # harvest came up thin, suggest it — the cost stays opt-in, never automatic.
    if assist and engine_proposal is None:
        print(
            "engine assist unavailable or produced nothing — using harvested "
            "checks only"
        )
    elif not assist and len(harvest_report.checks) < 2:
        print(
            "harvest found little — `alc onboard --assist` can analyze the tree "
            "(spends one engine turn)"
        )

    # Every human mode opens with the same honest preview (diffs + summary +
    # notes/unknowns). render_preview is pure and already phrases everything as
    # ALC's own recommendation (no external source named).
    print(render_preview(proposal, manifest_raw, blueprints_raw))

    # --dry-run, or a non-interactive shell without --yes: preview only.
    if args.dry_run or (not args.yes and not _isatty()):
        return 0

    # --yes: apply the FULL proposal (checks + opt-ins + --stage) non-interactively.
    if args.yes:
        return _print_onboard_apply(onboard_apply(proposal, operator_layer))

    # ---------------------------------------------------------------------
    # Interactive: three independently-approvable sections. A "no" skips that
    # section; it never aborts the command.
    # ---------------------------------------------------------------------
    project_checks = proposal.check_sets.get("project", [])

    checks_approved = False
    if project_checks:
        n = len(project_checks)
        m = sum(1 for c in project_checks if not c.available)
        prompt = (
            f"Add check_set 'project' ({n} check(s)"
            + (f", {m} commented — binary off PATH" if m else "")
            + ")? [y/N]: "
        )
        checks_approved = input(prompt).strip().lower() in ("y", "yes")
    else:
        # An empty harvest never invents checks — say so and point at the manual
        # path (do NOT name any external source).
        print(
            "No checks were harvested from this project — add checks by hand to "
            ".alc/manifest.yaml check_sets (ALC does not invent checks)."
        )

    opt_ins_approved = False
    if proposal.blueprint_opt_ins:
        names = ", ".join(sorted(proposal.blueprint_opt_ins))
        opt_ins_approved = input(
            f"Insert `check_set: project` into {len(proposal.blueprint_opt_ins)} "
            f"smoke-only blueprint(s) ({names})? [y/N]: "
        ).strip().lower() in ("y", "yes")

    # Stage & team — only when --stage was not already given (advisory; a stage
    # never changes execution).
    chosen_stage = args.stage
    if args.stage is None:
        answer = input(
            "Declare a product stage? [pre-pmf/growth/strong-pmf/skip]: "
        ).strip().lower()
        if answer in ("pre-pmf", "growth", "strong-pmf"):
            chosen_stage = answer

    # Build the FINAL proposal from only the approved sections. Opt-ins are kept
    # only when the checks section was ALSO approved — a `check_set: project`
    # line pointing at a set that was declined would dangle.
    final = build_proposal(
        manifest,
        project_root,
        blueprints,
        harvest_report,
        stage=chosen_stage,
        hired_archetypes=hired,
        engine_proposal=engine_proposal,
    )
    final = replace(
        final,
        check_sets=final.check_sets if checks_approved else {},
        blueprint_opt_ins=(
            final.blueprint_opt_ins if (checks_approved and opt_ins_approved) else {}
        ),
    )
    if opt_ins_approved and not checks_approved:
        print(
            "Blueprint opt-ins skipped — the 'project' check_set was not added, so "
            "there is nothing to opt into."
        )

    # When a stage was chosen interactively, surface its team hints as ready
    # `alc team hire` suggestions and offer to hire them now (the existing path).
    if args.stage is None and chosen_stage is not None and final.team_hints:
        print(f"stage '{chosen_stage}' suggests hiring:")
        for archetype in final.team_hints:
            print(f"  alc team hire {archetype}")
        if input("Hire them now? [y/N]: ").strip().lower() in ("y", "yes"):
            _install_stage_packs(project_root, chosen_stage, force=False)

    return _print_onboard_apply(onboard_apply(final, operator_layer))


def cmd_lint(args: argparse.Namespace) -> int:
    """Run `alc lint`: check the Operator Layer for Policy Gate violations."""
    from alc.intake import load_all_blueprints, load_all_loops, load_manifest
    from alc.policy import (
        lint_provision_coverage,
        coverage_report,
        has_errors,
        lint,
        lint_loops,
        validate_provisions,
        validate_prompts,
    )
    from alc.stagepolicy import lint_stage

    operator_layer = _find_operator_layer()
    manifest = load_manifest(operator_layer)
    blueprints = load_all_blueprints(manifest, operator_layer)
    violations = lint(manifest, blueprints)
    violations += validate_prompts(manifest, operator_layer, blueprints)
    violations += validate_provisions(manifest, operator_layer.parent)
    violations += lint_provision_coverage(manifest, blueprints, operator_layer.parent)
    violations += lint_stage(manifest, blueprints)
    violations += lint_loops(manifest, load_all_loops(manifest, operator_layer))

    # Shape and reach are different questions. lint has only ever answered the
    # first, while printing a sentence readers take as an answer to both.
    coverage = coverage_report(manifest, blueprints, operator_layer.parent)

    if getattr(args, "json", False):
        from alc.output import emit_json

        # The array shape is a public contract — `alc lint --json | jq '.[].rule'`
        # is a reasonable thing to have written. Coverage is a human-readable
        # note; wrapping the array to carry it would break that for a feature
        # nobody asked to consume by machine.
        emit_json([
            {"rule": v.rule, "severity": v.severity, "message": v.message}
            for v in violations
        ])
        return 1 if has_errors(violations) else 0

    if not violations:
        if coverage:
            print("No violations found — .alc/ is well-formed.")
            print("But it does not reach all of this project:")
            for line in coverage:
                print(line)
        else:
            print("No violations found — .alc/ is well-formed.")
        return 0

    for v in violations:
        tag = "[ERROR]" if v.severity == "error" else "[WARN] "
        print(f"{tag} [{v.rule}] {v.message}")
    if coverage:
        print("Coverage:")
        for line in coverage:
            print(line)

    if has_errors(violations):
        return 1
    return 0


def _archive_run_report(report_path: Path, blueprint, report, engine: str) -> None:
    """Archive a direct `alc run`'s RunReport as a FlowReport `*.report.json` under
    `runs/`, so `alc audit` and Mix Health — which aggregate the FlowReports in
    `done/` and `runs/` — count INTERACTIVE runs too, not only queue-drained
    (`alc tick`) work. Without this a landed `alc run refactor` (archetype: sweeper)
    still read as "sweeper never exercised". Wrapped as a single-stage FlowReport,
    mirroring the queue's own specialist archive; the stage carries
    `Blueprint.archetype`, so Mix Health buckets it correctly.

    An isolated run names the report after its BRANCH (see
    `branches.run_report_filename`) so `alc discard` can delete it when the branch is
    discarded; a non-isolated run (no branch) names it after its event log. Best-effort:
    a write failure never fails the run. A `spike` is never archived (throwaway) — the
    caller gates on that.
    """
    from alc.models import FlowReport

    flow = FlowReport(
        flow=blueprint.name,
        engine=engine,
        success=report.success,
        stages=[report],
        scorecard=report.scorecard,
    )
    try:
        report_path.write_text(flow.model_dump_json(indent=2))
    except OSError:
        pass


def cmd_run(args: argparse.Namespace) -> int:
    """Run `alc run <blueprint> "<task>" [--engine NAME] [--isolate]`."""
    from alc.bundle import summarize_bundle, write_bundle
    from alc.commitmsg import make_commit_message_provider
    from alc.events import abort_event_on_interrupt, bind_run_log, new_run_log_path
    from alc.intake import load_blueprint, load_manifest
    from alc.primer import load_primer
    from alc.runner import MandateRunner, PolicyViolationError
    from alc.worktree import IsolatedWorktree, git_toplevel, is_git_repo, runtime_provisions

    operator_layer = _find_operator_layer()
    manifest = load_manifest(operator_layer)

    blueprints_dir = operator_layer.parent / manifest.blueprints_dir
    # No Blueprint named: answer "what can I run?" instead of an argparse usage
    # line. This is the discovery path — there is no other command that lists them.
    if args.blueprint is None:
        _print_units("blueprint", blueprints_dir, ".md")
        print('\nRun one with: alc run <blueprint> "<task>"')
        return 0
    if args.task is None:
        print(f"[ERROR] alc run {args.blueprint} needs a task, e.g.", file=sys.stderr)
        print(f'  alc run {args.blueprint} "<a small, well-scoped task>"', file=sys.stderr)
        return 1
    try:
        blueprint = load_blueprint(blueprints_dir, args.blueprint)
    except FileNotFoundError:
        return _no_such_unit("blueprint", args.blueprint, blueprints_dir, ".md")

    # Validate --tier early before any work is done.
    tier_err = _validate_tier(manifest, args.tier)
    if tier_err:
        print(f"[ERROR] {tier_err}", file=sys.stderr)
        return 1

    if args.tier:
        blueprint = blueprint.model_copy(update={"compute_tier": args.tier})

    runner = MandateRunner(manifest=manifest, operator_layer=operator_layer)

    # Per-run event log, resolved against the original project BEFORE any worktree.
    run_log = new_run_log_path(
        operator_layer.parent / manifest.runs_dir, "run", f"{args.blueprint} {args.task}"
    )

    # Build extra_context from --primer and/or --from-bundle before branching.
    parts: list[str] = []
    if args.primer:
        primers_dir = operator_layer.parent / manifest.primers_dir
        try:
            parts.append(f"### Primer: {args.primer}\n" + load_primer(primers_dir, args.primer))
        except FileNotFoundError as exc:
            print(f"[ERROR] {exc}", file=sys.stderr)
            return 1
    if args.from_bundle:
        bundles_dir = operator_layer.parent / manifest.bundles_dir
        ref = Path(args.from_bundle)
        if not ref.exists():
            ref = bundles_dir / f"{args.from_bundle}.jsonl"
        try:
            parts.append(
                "### Prior run (bundle)\n"
                + summarize_bundle(ref, max_output_chars=manifest.bundle_output_chars)
            )
        except (FileNotFoundError, ValueError) as exc:
            print(f"[ERROR] {exc}", file=sys.stderr)
            return 1
    extra_context: str | None = "\n\n".join(parts) if parts else None

    use_isolate = args.isolate
    if blueprint.mode == "spike":
        # The ONE relaxation of the checks gate comes fenced — force
        # isolation regardless of --isolate so a spike's edits are never made
        # directly against the operator's working tree.
        use_isolate = True
    if use_isolate and not is_git_repo(Path.cwd()):
        print("--isolate ignored: not inside a git repository", file=sys.stderr)
        use_isolate = False

    if use_isolate:
        repo_root = git_toplevel(Path.cwd())
        wt = IsolatedWorktree(
            repo_root,
            label="run",
            commit_message=manifest.worktree_commit_message,
            message_provider=make_commit_message_provider(
                manifest=manifest,
                operator_layer=operator_layer,
                workdir=repo_root,
                fallback=manifest.worktree_commit_message,
                engine_override=args.engine,
            ),
            # Provision gitignored runtime deps (node_modules/.env/data) into the
            # worktree so the mandate's checks resolve — before this `alc run
            # --isolate` never provisioned and a Node check 127'd. Empty -> no-op.
            provisions=runtime_provisions(manifest),
        )
        # Use the context manager manually so we can inspect wt after __exit__.
        wt_path = wt.__enter__()
        exc_info = (None, None, None)
        report = None
        try:
            # Guard inside the worktree try so an interrupt emits run_aborted and
            # then unwinds through this except/finally (worktree cleanup) as before.
            with abort_event_on_interrupt(), bind_run_log(run_log):
                report = runner.run(
                    blueprint=blueprint,
                    task=args.task,
                    engine_override=args.engine,
                    workdir=wt_path,
                    extra_context=extra_context,
                )
        except PolicyViolationError as exc:
            print(f"[ERROR] {exc}", file=sys.stderr)
            exc_info = (type(exc), exc, exc.__traceback__)
        except BaseException as exc:
            exc_info = (type(exc), exc, exc.__traceback__)
        finally:
            if blueprint.mode == "spike":
                # The exception must never become a delivery path: never commit,
                # discard the branch regardless of outcome.
                wt.commit_on_exit = False
            wt.__exit__(*exc_info)

        # Re-raise non-PolicyViolation exceptions after cleanup — but say where
        # the work went first. `wt.__exit__` above ran on this path too, so an
        # interrupt COMMITS whatever the engine had already written onto the run
        # branch and removes the worktree. Staying silent leaves that branch to
        # be met later by `alc land` with no record of where it came from, and
        # leaves the UI (which reads isolation_finished) with nothing to name.
        if exc_info[1] is not None and not isinstance(exc_info[1], PolicyViolationError):
            _print_isolation_result(wt)
            _emit_isolation_result(run_log, wt)
            raise exc_info[1]

        if report is None:
            # PolicyViolationError path.
            return 1

        _print_run_report(report, as_json=getattr(args, "json", False))
        _print_isolation_result(wt)
        _emit_isolation_result(run_log, wt)
        if report.success and blueprint.mode != "spike":
            from alc.branches import run_report_filename

            runs_dir = operator_layer.parent / manifest.runs_dir
            # Name the report after the branch when the run committed one, so
            # `alc discard <branch>` can delete it; else after the event log.
            report_path = (
                runs_dir / run_report_filename(wt.branch)
                if wt.committed
                else run_log.with_suffix(".report.json")
            )
            _archive_run_report(
                report_path, blueprint, report, args.engine or manifest.default_engine
            )
        if args.bundle:
            bundles_dir = operator_layer.parent / manifest.bundles_dir
            path = write_bundle(bundles_dir, args.blueprint, args.task, report)
            print(f"Bundle written: {path}")
        return 0 if report.success else 1

    # Non-isolated path (default).
    try:
        with abort_event_on_interrupt(), bind_run_log(run_log):
            report = runner.run(
                blueprint=blueprint,
                task=args.task,
                engine_override=args.engine,
                extra_context=extra_context,
            )
    except PolicyViolationError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1

    _print_run_report(report, as_json=getattr(args, "json", False))
    if report.success and blueprint.mode != "spike":
        _archive_run_report(
            run_log.with_suffix(".report.json"),
            blueprint,
            report,
            args.engine or manifest.default_engine,
        )
    if args.bundle:
        bundles_dir = operator_layer.parent / manifest.bundles_dir
        path = write_bundle(bundles_dir, args.blueprint, args.task, report)
        print(f"Bundle written: {path}")
    return 0 if report.success else 1


def cmd_spike(args: argparse.Namespace) -> int:
    """Run `alc spike "<task>" [--engine NAME]`.

    Sugar over `alc run spike "<task>"`: no blueprint name to remember, no
    isolate/commit ceremony to opt into — the Prototyper pack's `spike`
    Blueprint declares `mode: spike`, which cmd_run itself fences (forced
    isolation, zero repairs, no commit; see runner.py). This wrapper only
    fills in the Blueprint name and the flags `alc run` exposes that a spike
    has no use for.
    """
    args.blueprint = "spike"
    args.isolate = False  # irrelevant: mode: spike forces isolation in cmd_run
    args.primer = None
    args.bundle = False
    args.from_bundle = None
    args.tier = None
    return cmd_run(args)


def _failure_reason(result, queue_dir) -> str:
    """Build a human-readable explanation string for a failed TickResult.

    Extracts the tail of the last executed stage's output_text (up to 400
    characters, prefixed with '…' when truncated) and appends a pointer to
    the Gate report JSON.  Used in cmd_tick to surface WHY a unit failed.

    Args:
        result: A TickResult whose ``success`` is False.
        queue_dir: The queue directory Path (used to build the report pointer).

    Returns:
        A multi-line string with indented tail output and the report pointer.
    """
    report = result.report
    pointer = f"    see: {queue_dir}/done/{Path(result.task_file).stem}.report.json"

    if not report.stages:
        return pointer

    last_stage = report.stages[-1]
    if not last_stage.output_text:
        return pointer

    text = last_stage.output_text
    if len(text) > 400:
        tail = "…" + text[-400:]
    else:
        tail = text

    # Indent every line of the tail by 4 spaces.
    indented = "\n".join("    " + line for line in tail.splitlines())
    return indented + "\n" + pointer


def cmd_tick(args: argparse.Namespace) -> int:
    """Run `alc tick`: drain the task queue (Unattended Mode Trigger).

    Processes every pending *.yaml file in queue_dir once and exits. Designed
    to be called by cron or launchd — cron provides the cadence; this command
    provides one drain pass. Exit code is 0 for all task outcomes (cron-friendly);
    per-task outcomes live in the Gate reports under done/. Exit code is 1 only
    for invalid usage (e.g. --concurrency < 1).
    """
    if args.concurrency < 1:
        print("[ERROR] --concurrency must be >= 1", file=sys.stderr)
        return 1

    from alc.events import abort_event_on_interrupt
    from alc.intake import load_manifest
    from alc.lock import tick_lock
    from alc.queue import process_queue

    operator_layer = _find_operator_layer()

    # Dirty-tree preflight: warn-and-proceed. A drain never sweeps the operator's
    # WIP — committing demands protect themselves (flow-level guard / isolation), so
    # a dirty tree is at most a visible failure, never data loss. Just notify.
    _warn_if_dirty_tree(
        operator_layer.parent, getattr(args, "allow_dirty", False), "tick"
    )

    manifest = load_manifest(operator_layer)

    # A hard --engine override wins over every task's own engine: for this drain.
    # Fail fast on an undeclared engine so a typo doesn't poison every demand and
    # archive the whole queue as engine-error failures instead of running the work.
    engine_override = getattr(args, "engine", None)
    if engine_override is not None and engine_override not in manifest.engines:
        print(
            f"[ERROR] unknown engine '{engine_override}'. "
            f"Available: {', '.join(sorted(manifest.engines))}",
            file=sys.stderr,
        )
        return 1

    queue_dir = operator_layer.parent / manifest.queue_dir
    if not queue_dir.exists():
        print("No pending tasks.")
        return 0

    # Serialise overlapping ticks (e.g. cron firing again before the prior run
    # finished) so a task is never processed twice.
    with tick_lock(queue_dir / ".lock") as acquired:
        if not acquired:
            print("Another tick is already in progress; skipping.")
            return 0
        # A serial drain binds each task's run log in the main context, so an
        # interrupt closes the in-flight run with run_aborted. Parallel workers
        # bind in their own worker context (unseen here) and degrade to staleness.
        with abort_event_on_interrupt():
            # Thread the override through only when set, so a drain WITHOUT --engine
            # calls process_queue exactly as before (the flag is purely additive —
            # this also keeps monkeypatched process_queue doubles byte-compatible).
            drain_kwargs = (
                {"engine_override": engine_override}
                if engine_override is not None
                else {}
            )
            results = process_queue(
                manifest, operator_layer, max_workers=args.concurrency, **drain_kwargs
            )

    if not results:
        print("No pending tasks.")
        return 0

    for result in results:
        status = "SUCCESS" if result.success else "FAILED"
        line = f"{result.task_file}: {result.flow} -> {status}"
        if result.branch:
            line += f" (branch {result.branch})"
        print(line)
        if not result.success:
            print(_failure_reason(result, queue_dir))

    return 0


def cmd_conduct(args: argparse.Namespace) -> int:
    """Run `alc conduct "<goal>" [--engine NAME] [--enqueue] [--strict-stage]`."""
    import sys

    from alc.conduct import conduct
    from alc.intake import load_manifest
    from alc.runner import PolicyViolationError

    operator_layer = _find_operator_layer()
    manifest = load_manifest(operator_layer)

    try:
        report = conduct(
            manifest=manifest,
            operator_layer=operator_layer,
            goal=args.goal,
            engine_override=args.engine,
            enqueue=args.enqueue,
            parallel=args.parallel,
            concurrency=args.concurrency,
            tier=args.tier,
            strict_stage=getattr(args, "strict_stage", False),
        )
    except ValueError as exc:
        print(f"[ERROR] Conductor could not produce a valid plan: {exc}", file=sys.stderr)
        return 1
    except PolicyViolationError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1

    # Summary header.
    print(f"Goal: {report.goal}")
    print()
    print("Plan:")
    for item in report.plan.items:
        print(f"  -> {item.name} ({item.kind}): {item.task}")
    print()
    for warning in report.warnings:
        print(f"[WARN] {warning}", file=sys.stderr)

    if report.mode == "run":
        # Parallel dispatch reports per-unit outcomes; serial reports flow outcomes.
        for unit in report.units:
            status = "SUCCESS" if unit.success else "FAILED"
            print(f"  {unit.name} ({unit.kind}) -> {status}")
        for flow_report in report.flow_reports:
            status = "SUCCESS" if flow_report.success else "FAILED"
            print(f"  {flow_report.flow} -> {status}")
        print()
        print(report.model_dump_json(indent=2))
        return 0 if report.success else 1

    # Enqueue mode.
    n = len(report.enqueued_files)
    files_str = ", ".join(report.enqueued_files)
    print(f"Enqueued {n} task(s): {files_str}")
    print()
    print(report.model_dump_json(indent=2))
    return 0


def _resolve_loop(args: argparse.Namespace):
    """Shared cycle/loop setup: resolve operator layer, manifest, loop def, and paths.

    Returns a (manifest, operator_layer, loop_def, loops, spath, error_code) tuple.
    ``error_code`` is an int exit code when setup failed (loop file missing or a
    Policy Gate violation), else None. When error_code is set, the other fields
    may be partially populated and must not be used.
    """
    from alc.intake import load_loop, load_manifest
    from alc.loop import loops_dir, state_path
    from alc.policy import validate_loop

    operator_layer = _find_operator_layer()
    manifest = load_manifest(operator_layer)
    loops = loops_dir(manifest, operator_layer)

    try:
        loop_def = load_loop(loops, args.name)
    except FileNotFoundError:
        print(f"[ERROR] No loop named '{args.name}' in {loops}", file=sys.stderr)
        return None, None, None, None, None, 1

    violations = validate_loop(manifest, operator_layer, loop_def)
    if violations:
        for v in violations:
            print(f"[ERROR] [{v.rule}] {v.message}", file=sys.stderr)
        return None, None, None, None, None, 1

    return manifest, operator_layer, loop_def, loops, state_path(loops, args.name), None


def cmd_cycle(args: argparse.Namespace) -> int:
    """Run `alc cycle <name>`: run exactly ONE autonomous loop cycle (cron target)."""
    from alc.events import abort_event_on_interrupt
    from alc.loop import (
        format_cycle_summary,
        load_loop_state,
        reset_loop_state,
        run_cycle,
        save_loop_state,
    )

    manifest, operator_layer, loop_def, _loops, spath, err = _resolve_loop(args)
    if err is not None:
        return err

    state = load_loop_state(spath, args.name)

    if args.status:
        if getattr(args, "json", False):
            from alc.output import emit_json

            emit_json(state.model_dump())
            return 0
        print(f"Loop:                    {state.name}")
        print(f"Status:                  {state.status}")
        print(f"Cycle:                   {state.cycle}")
        print(f"Consecutive no-progress: {state.consecutive_no_progress}")
        if state.budget_used:
            used = ", ".join(f"{k}={v}" for k, v in state.budget_used.items())
            print(f"Budget used:             {used}")
        if state.stopped_reason:
            print(f"Stopped reason:          {state.stopped_reason}")
        return 0

    # Dirty-tree preflight: warn-and-proceed. A cycle never sweeps the operator's
    # WIP — committing demands protect themselves (flow-level guard / isolation), so
    # a dirty tree is at most a visible failure, never data loss. Just notify. Placed
    # after the read-only --status path so status can always be inspected.
    _warn_if_dirty_tree(
        operator_layer.parent, getattr(args, "allow_dirty", False), "cycle"
    )

    if args.reset:
        # Reset THEN run: replace the state with a fresh pending one and fall through
        # so this invocation runs one cycle on the fresh state (from pending).
        state = reset_loop_state(spath, args.name)
        print(f"Loop '{args.name}' reset.")

    if state.status == "stopped":
        print(
            f"Loop '{args.name}' already stopped: {state.stopped_reason}. "
            "Use --reset to restart."
        )
        return 0

    # A per-invocation --concurrency > 0 overrides the definition's drain concurrency.
    if args.concurrency and args.concurrency > 0:
        loop_def = loop_def.model_copy(
            update={"drain": loop_def.drain.model_copy(update={"concurrency": args.concurrency})}
        )

    # An interrupt closes the in-flight run (the replenish step's log is bound in
    # the main context) with run_aborted; a parallel drain's worker-context runs
    # are unseen here and degrade to staleness.
    with abort_event_on_interrupt():
        state, record = run_cycle(
            manifest, operator_layer, loop_def, state, engine_override=args.engine
        )
    save_loop_state(spath, state)
    print(format_cycle_summary(record))
    return 0


def cmd_loop(args: argparse.Namespace) -> int:
    """Run `alc loop <name>`: repeat cycles until the loop stops.

    ``--once`` and ``--status`` delegate to ``cmd_cycle``, which is the single
    implementation of one cycle — the merge is at the CLI surface, not a second
    copy of the behaviour.
    """
    import time

    if getattr(args, "once", False) or getattr(args, "status", False):
        return cmd_cycle(args)

    from alc.events import abort_event_on_interrupt
    from alc.loop import (
        format_cycle_summary,
        load_loop_state,
        reset_loop_state,
        run_cycle,
        save_loop_state,
    )

    manifest, operator_layer, loop_def, _loops, spath, err = _resolve_loop(args)
    if err is not None:
        return err

    # Dirty-tree preflight: warn-and-proceed. Each cycle never sweeps the operator's
    # WIP — committing demands protect themselves (flow-level guard / isolation), so
    # a dirty tree is at most a visible failure, never data loss. Just notify.
    _warn_if_dirty_tree(
        operator_layer.parent, getattr(args, "allow_dirty", False), "loop"
    )

    state = load_loop_state(spath, args.name)
    if args.reset:
        # Reset THEN loop: start the repeating drain from a fresh pending state,
        # symmetric with `alc cycle --reset` (both share reset_loop_state).
        state = reset_loop_state(spath, args.name)
        print(f"Loop '{args.name}' reset.")
    if state.status == "stopped":
        print(
            f"Loop '{args.name}' already stopped: {state.stopped_reason}. "
            "Use --reset to restart."
        )
        return 0

    while True:
        # Each cycle's in-flight run (replenish step, main-context log) closes on
        # run_aborted when interrupted; a parallel drain degrades to staleness.
        with abort_event_on_interrupt():
            state, record = run_cycle(
                manifest, operator_layer, loop_def, state, engine_override=args.engine
            )
        save_loop_state(spath, state)
        print(format_cycle_summary(record))
        if state.status == "stopped":
            break
        if args.interval > 0:
            time.sleep(args.interval)

    print(f"Loop '{args.name}' stopped: {state.stopped_reason}")
    return 0


def cmd_primer(args: argparse.Namespace) -> int:
    """Run `alc primer new <name> [--force]`: scaffold a new Primer file."""
    from alc.intake import load_manifest
    from alc.primer import new_primer

    operator_layer = _find_operator_layer()
    manifest = load_manifest(operator_layer)
    primers_dir = operator_layer.parent / manifest.primers_dir

    try:
        path = new_primer(primers_dir, args.name, force=args.force)
    except FileExistsError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1

    print(path)
    return 0


def cmd_new(args: argparse.Namespace) -> int:
    """Run `alc new <kind> <name> [--force] [--from NAME]`: author a unit from a core scaffold.

    ``kind`` is one of blueprint/flow/specialist/loop/primer; the target
    directory comes from the manifest. Refuses to overwrite an existing unit
    without ``--force``. The payload is validated through the collection's real
    loader (same temp-dir trick as ``alc.ui.collections._parse_raw``) BEFORE
    anything is written, so an invalid payload never touches disk — primers have
    no structured loader, so any text is valid for them, same as in the UI.
    ``--from NAME`` clones an existing unit of the same kind, replacing its
    ``name:`` field.
    """
    import re
    import tempfile

    from alc.authoring import scaffold_text
    from alc.intake import (
        load_blueprint,
        load_flow,
        load_loop,
        load_manifest,
        load_specialist,
    )

    dir_attr = {
        "blueprint": "blueprints_dir",
        "flow": "flows_dir",
        "specialist": "specialists_dir",
        "loop": "loops_dir",
        "primer": "primers_dir",
    }[args.kind]
    suffix = ".md" if args.kind in ("blueprint", "primer") else ".yaml"
    loader = {
        "blueprint": load_blueprint,
        "flow": load_flow,
        "specialist": load_specialist,
        "loop": load_loop,
    }.get(args.kind)

    operator_layer = _find_operator_layer()
    manifest = load_manifest(operator_layer)
    directory = operator_layer.parent / getattr(manifest, dir_attr)
    path = directory / f"{args.name}{suffix}"

    if path.exists() and not args.force:
        print(
            f"[ERROR] {args.kind} '{args.name}' already exists: {path}; "
            "pass --force to overwrite",
            file=sys.stderr,
        )
        return 1

    if args.from_name:
        source = directory / f"{args.from_name}{suffix}"
        if not source.is_file():
            print(
                f"[ERROR] no {args.kind} named '{args.from_name}' to clone from",
                file=sys.stderr,
            )
            return 1
        raw = re.sub(
            r"^name:.*$", f"name: {args.name}", source.read_text(), count=1, flags=re.MULTILINE
        )
    else:
        raw = scaffold_text(f"{args.kind}s", args.name)

    if loader is not None:
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / f"{args.name}{suffix}").write_text(raw)
            try:
                loader(Path(td), args.name)
            except Exception as exc:  # noqa: BLE001 — surface any parse/validation error
                print(f"[ERROR] invalid {args.kind} '{args.name}': {exc}", file=sys.stderr)
                return 1

    directory.mkdir(parents=True, exist_ok=True)
    path.write_text(raw)
    print(path)
    return 0


def cmd_team(args: argparse.Namespace) -> int:
    """Run `alc team hire|list|retire|remove|status`: the operator verb over Archetype Packs.

    Packs (``alc.packs``) are the implementation; ``team`` is the only verb an
    operator sees — ``hire`` scaffolds a pack's files then lints, ``list``/
    ``status`` show the hired roster (and the state of any loops a member
    brought), ``retire`` archives a member's loop definition(s) instead of
    deleting them, ``remove`` deletes a member's UNMODIFIED pack files (keeping
    anything the operator customised).
    """
    # Bare `alc team` = the read view: default to `status` (roster + Mix Health)
    # so the command family opens on observation, never a usage error.
    if args.team_action is None:
        args.team_action = "status"
    if args.team_action == "hire":
        return _team_hire(args)
    if args.team_action == "retire":
        return _team_retire(args)
    if args.team_action == "remove":
        return _team_remove(args)
    return _team_roster(args)  # 'list' and 'status' share the same roster output


def _team_hire(args: argparse.Namespace) -> int:
    """`alc team hire <archetype> [--force]`: scaffold a pack's files, then lint.

    Additive by default: writes only the pack files not yet on disk and keeps
    existing ones (so a partially-present or drifted archetype receives the newer
    files ALC now ships, and a re-hire is an idempotent no-op). `--force` is the
    ONE destructive path: it overwrites every pack file. Additive never destroys
    anything, so there is nothing to refuse — the old whole-pack refusal
    protected nothing and contradicted the roster, which already counts a
    partially-present archetype as hired.
    """
    from alc.intake import load_all_blueprints, load_all_loops, load_manifest
    from alc.packs import (
        PACK_NEXT_STEP,
        PACKS,
        pack_files,
        retarget_pack_content,
        split_pack_files,
    )
    from alc.policy import (
        lint_provision_coverage,
        has_errors,
        lint,
        lint_loops,
        validate_prompts,
        validate_provisions,
    )
    from alc.scaffold import detect_stacks
    from alc.stagepolicy import lint_stage

    if args.archetype not in PACKS:
        available = ", ".join(sorted(PACKS)) or "none yet"
        print(
            f"[ERROR] no pack named '{args.archetype}' yet (available: {available})",
            file=sys.stderr,
        )
        return 1

    operator_layer = _find_operator_layer()
    project_root = operator_layer.parent
    manifest = load_manifest(operator_layer)
    stacks = detect_stacks(project_root)

    if args.force:
        # The one destructive path: overwrite every pack file.
        files, retargeted = retarget_pack_content(
            pack_files(args.archetype, stacks), manifest.check_sets
        )
        for rel_path, content in sorted(files.items()):
            target = project_root / rel_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)
        print(f"Hired '{args.archetype}':")
        for rel_path in sorted(files):
            print(f"  {rel_path}")
    else:
        missing, present = split_pack_files(
            args.archetype, stacks, project_root, check_sets=manifest.check_sets
        )
        # Which Blueprints had their stack-named set replaced by a declared one
        # (finding 34) — reported below so the operator learns it happened.
        _, retargeted = retarget_pack_content(
            pack_files(args.archetype, stacks), manifest.check_sets
        )
        retargeted = {rel: t for rel, t in retargeted.items() if rel in missing}
        # Write ONLY the files not yet on disk — additive, never destructive.
        for rel_path in sorted(missing):
            target = project_root / rel_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(missing[rel_path])

        if not missing:
            print(
                f"'{args.archetype}' is already fully hired "
                f"({len(present)} file(s)); nothing to add."
            )
        else:
            print(f"Hired '{args.archetype}' (added {len(missing)} missing file(s)):")
            for rel_path in sorted(missing):
                print(f"  {rel_path}")
            for rel_path in sorted(present):
                # Flag drift so the operator knows --force would reconcile it —
                # present[] carries the pack default, compared to the disk bytes.
                suffix = ""
                if (project_root / rel_path).read_text() != present[rel_path]:
                    suffix = " (differs from the pack default — --force overwrites)"
                print(f"  kept (already on disk): {rel_path}{suffix}")

    if retargeted:
        names = ", ".join(sorted({t for t in retargeted.values()}))
        print(
            f"Pointed {len(retargeted)} Blueprint(s) at your declared check set "
            f"({names}) — the stack default is not declared in this manifest."
        )

    blueprints = load_all_blueprints(manifest, operator_layer)
    violations = lint(manifest, blueprints)
    violations += validate_prompts(manifest, operator_layer, blueprints)
    violations += validate_provisions(manifest, project_root)
    violations += lint_provision_coverage(manifest, blueprints, project_root)
    violations += lint_stage(manifest, blueprints)
    # Hiring the maintainer pack onto a manifest with no env-refresh provision is
    # the exact "existing project adopts a deps loop" moment this rule targets:
    # the deps-refresh Loop it just wrote would run its checks against stale,
    # already-installed packages — warn immediately so the operator adds a refresh.
    violations += lint_loops(manifest, load_all_loops(manifest, operator_layer))

    if not violations:
        print("No violations found — .alc/ is well-formed.")
    else:
        for v in violations:
            tag = "[ERROR]" if v.severity == "error" else "[WARN] "
            print(f"{tag} [{v.rule}] {v.message}")

    # One concrete next action, pack-specific and last — the same golden-path
    # rule init follows. After a hire the roster printed five file paths and
    # stopped; "now what?" was the operator's own problem (dogfood finding 24).
    next_step = PACK_NEXT_STEP.get(args.archetype)
    if next_step:
        print(f"Next: {next_step}")
    return 1 if has_errors(violations) else 0


def _print_mix_health(health) -> None:
    """Print `alc team status`'s Mix Health section.

    `total_runs == 0` renders as "no data yet" — never a division by zero or a
    misleading all-zero table. With no `stage` declared, the breakdown is
    printed but never judged (no core/secondary/off-mix labels).
    """
    print()
    if health.total_runs == 0:
        print(
            "Mix Health: no data yet — drain the queue (`alc tick`) to populate "
            "archived reports."
        )
        return

    if health.stage is None:
        print("Mix Health (no stage declared — breakdown only, not judged):")
    else:
        print(
            f"Mix Health (stage: {health.stage}; "
            f"core={health.core} secondary={health.secondary}):"
        )

    for entry in health.by_archetype:
        label = ""
        if health.stage is not None:
            if entry.archetype in health.core:
                label = "  [core]"
            elif entry.archetype in health.secondary:
                label = "  [secondary]"
            elif entry.archetype is not None:
                label = "  [off-mix]"
        name = entry.archetype or "(none)"
        print(
            f"  {name:<12} runs={entry.runs} span={entry.span} "
            f"cost_usd={entry.cost_usd:.4f} net_lines={entry.net_lines:+d}{label}"
        )

    # A core archetype with zero runs, and the hint the report already derived
    # (hire it, exercise its loop, or route a demand) — never re-derived here so
    # the CLI and the UI can never disagree about what to advise.
    for idle in health.idle_core:
        if idle.hired:
            print(
                f"  {idle.archetype:<12} runs=0 — core archetype hired but never "
                f"exercised; hint: {idle.hint}"
            )
        else:
            print(
                f"  {idle.archetype:<12} runs=0 — core archetype not hired yet; "
                f"hint: {idle.hint}"
            )


def _team_roster(args: argparse.Namespace) -> int:
    """`alc team list|status`: the hired roster and the state of loops each member
    brought. `status` additionally reports Mix Health:
    archived reports' real archetype spend against the declared stage's target
    mix — `list` stays roster-only.
    """
    from alc.intake import load_manifest
    from alc.loop import load_loop_state, loops_dir, state_path
    from alc.packs import PACK_DESCRIPTIONS, PACKS, pack_files, retired_pack_loops
    from alc.scaffold import detect_stacks

    operator_layer = _find_operator_layer()
    project_root = operator_layer.parent
    manifest = load_manifest(operator_layer)
    stacks = detect_stacks(project_root)
    loops_directory = loops_dir(manifest, operator_layer)
    loops_prefix = f"{manifest.loops_dir}/"

    roster = []
    for archetype in sorted(PACKS):
        files = pack_files(archetype, stacks)
        present = sorted(rel for rel in files if (project_root / rel).exists())
        if not present:
            continue  # not hired

        member_loops = []
        # `present`, not `files`: retiring a member MOVES its loop into
        # loops/retired/, and iterating the pack definition kept listing that
        # loop — with a state — for a file no longer there. The roster is meant
        # to report the disk, not the pack it came from.
        for rel_path in sorted(present):
            if rel_path.startswith(loops_prefix) and rel_path.endswith(".yaml"):
                loop_name = Path(rel_path).stem
                state = load_loop_state(state_path(loops_directory, loop_name), loop_name)
                member_loops.append(
                    {
                        "name": state.name,
                        "status": state.status,
                        "cycle": state.cycle,
                        "stopped_reason": state.stopped_reason,
                    }
                )
        roster.append(
            {
                "archetype": archetype,
                "files": present,
                "loops": member_loops,
                # Loops a retire archived: the live file is gone, so
                # `member_loops` cannot see them — but the operator who just
                # clicked/typed retire needs the roster to SAY what happened,
                # not show a member that silently lost its loop line.
                "retired_loops": retired_pack_loops(
                    archetype, stacks, project_root, manifest.loops_dir
                ),
            }
        )

    health = None
    if args.team_action == "status":
        import time

        from alc.stagepolicy import MIX_HEALTH_WINDOW_S, mix_health

        done_dir = project_root / manifest.queue_dir / "done"
        # Map each hired archetype to the loop names its pack brought, so
        # mix_health can hint "run its loop" for a hired-but-idle core (never
        # "hire it" for something already on the team). Built from the roster we
        # already assembled — no extra IO.
        member_roster = {
            m["archetype"]: [lp["name"] for lp in m["loops"]] for m in roster
        }
        health = mix_health(
            done_dir,
            manifest,
            roster=member_roster,
            extra_report_dir=project_root / manifest.runs_dir,
            since_epoch=time.time() - MIX_HEALTH_WINDOW_S,
        )

    if getattr(args, "json", False):
        from dataclasses import asdict

        from alc.output import emit_json

        if health is not None:
            emit_json({"roster": roster, "mix_health": asdict(health)})
        else:
            emit_json(roster)
        return 0

    if not roster:
        # init promises "prebuilt agent teams" behind this exact command, and
        # this used to answer with neither names nor descriptions — choosing an
        # archetype was guesswork (dogfood finding 22).
        print("No members hired yet. Available packs:")
        width = max(len(name) for name in PACKS)
        for name in sorted(PACKS):
            print(f"  {name.ljust(width)}  {PACK_DESCRIPTIONS.get(name, '')}")
        print('Hire one with: alc team hire <name>')
    else:
        print("Hired members:")
        for member in roster:
            print(f"  {member['archetype']}")
            for rel_path in member["files"]:
                print(f"    {rel_path}")
            if member["loops"]:
                for loop in member["loops"]:
                    line = f"    loop {loop['name']}: {loop['status']} (cycle {loop['cycle']})"
                    if loop["status"] == "stopped":
                        line += f", stopped_reason={loop['stopped_reason']}"
                    print(line)
            if member["retired_loops"]:
                names = ", ".join(member["retired_loops"])
                print(f"    loops retired: {names} ({manifest.loops_dir}/retired/)")
            if not member["loops"] and not member["retired_loops"]:
                print("    loops: (none)")

    if health is not None:
        _print_mix_health(health)

    return 0


def _team_retire(args: argparse.Namespace) -> int:
    """`alc team retire <member>`: archive that member's loop definition(s), never delete."""
    from alc.intake import load_manifest
    from alc.loop import loops_dir
    from alc.packs import PACKS, pack_files
    from alc.scaffold import detect_stacks

    if args.member not in PACKS:
        available = ", ".join(sorted(PACKS)) or "none yet"
        print(
            f"[ERROR] no pack named '{args.member}' yet (available: {available})",
            file=sys.stderr,
        )
        return 1

    operator_layer = _find_operator_layer()
    project_root = operator_layer.parent
    manifest = load_manifest(operator_layer)
    loops_prefix = f"{manifest.loops_dir}/"

    files = pack_files(args.member, detect_stacks(project_root))
    loop_files = sorted(
        rel for rel in files if rel.startswith(loops_prefix) and rel.endswith(".yaml")
    )

    retired_dir = loops_dir(manifest, operator_layer) / "retired"
    moved: list[str] = []
    for rel_path in loop_files:
        src = project_root / rel_path
        if not src.exists():
            continue
        retired_dir.mkdir(parents=True, exist_ok=True)
        dest = retired_dir / src.name
        src.rename(dest)
        moved.append(str(dest.relative_to(project_root)))

    if not moved:
        # "Nothing to retire" has two very different causes; a member whose
        # loops were ALREADY archived reads a bare "no loop(s) on disk" as the
        # command being broken (dogfood: the UI's disabled button read the
        # same way). Name the state.
        from alc.packs import retired_pack_loops

        already = retired_pack_loops(args.member, detect_stacks(project_root), project_root, manifest.loops_dir)
        if already:
            names = ", ".join(already)
            print(
                f"'{args.member}' has no live loop(s) to retire — already "
                f"archived in {manifest.loops_dir}/retired/: {names}"
            )
        else:
            print(f"'{args.member}' has no loop(s) on disk to retire.")
        return 0

    print(f"Retired '{args.member}':")
    for rel_path in moved:
        print(f"  {rel_path}")
    return 0


def _team_remove(args: argparse.Namespace) -> int:
    """`alc team remove <member>`: delete the member's UNMODIFIED pack files.

    The missing exit `retire` is not: retire archives loops and the member
    stays hired (membership is "any pack file on disk"), so an operator who
    tried a pack and wants it gone had no path on either surface. Removal is
    scoped so it cannot destroy work: only files byte-identical to what the
    pack would write today are deleted (including a retired loop's archived
    copy); anything customised is kept, listed, and keeps the member on the
    roster. `alc team hire` rewrites exactly what was removed, so the
    operation is reversible.
    """
    from alc.intake import load_manifest
    from alc.packs import PACKS, remove_pack
    from alc.scaffold import detect_stacks

    if args.member not in PACKS:
        available = ", ".join(sorted(PACKS)) or "none yet"
        print(
            f"[ERROR] no pack named '{args.member}' yet (available: {available})",
            file=sys.stderr,
        )
        return 1

    operator_layer = _find_operator_layer()
    project_root = operator_layer.parent
    manifest = load_manifest(operator_layer)

    removed, kept = remove_pack(
        args.member,
        detect_stacks(project_root),
        project_root,
        manifest.loops_dir,
        check_sets=manifest.check_sets,
    )

    if not removed and not kept:
        print(f"'{args.member}' has no pack files on disk — nothing to remove.")
        return 0

    if removed:
        print(f"Removed '{args.member}' ({len(removed)} file(s) matched the pack defaults):")
        for rel_path in removed:
            print(f"  {rel_path}")
    if kept:
        print(f"Kept {len(kept)} customised file(s) — delete by hand if you want them gone:")
        for rel_path in kept:
            print(f"  {rel_path}")
        print(f"'{args.member}' stays on the roster because of the kept file(s).")
    else:
        print(f"'{args.member}' left the roster. Re-hire anytime with: alc team hire {args.member}")
    return 0


def cmd_prompts(args: argparse.Namespace) -> int:
    """Run `alc prompts <action>`: list or eject keyed prompt overrides."""
    from alc.intake import load_manifest
    from alc.prompts import eject_prompt, list_prompts

    operator_layer = _find_operator_layer()
    manifest = load_manifest(operator_layer)

    if args.action == "list":
        entries = list_prompts(operator_layer, manifest)
        if getattr(args, "json", False):
            from dataclasses import asdict

            from alc.output import emit_json

            emit_json([asdict(e) for e in entries])
            return 0
        reserved = [e for e in entries if e.kind == "reserved"]
        free = [e for e in entries if e.kind == "free"]
        print("Reserved prompts:")
        for e in reserved:
            print(f"  {e.name}: {e.source}")
        print("Free prompts:")
        if free:
            for e in free:
                print(f"  {e.name}")
        else:
            print("  (none)")
        return 0

    # action == "eject"
    try:
        path = eject_prompt(args.name, operator_layer, manifest, force=args.force)
    except KeyError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1
    except FileExistsError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1

    print(path)
    return 0


def cmd_specialist(args: argparse.Namespace) -> int:
    """Run `alc specialist <name> "<task>" [--engine NAME]`."""
    from alc.events import bind_run_log, new_run_log_path
    from alc.intake import load_manifest, load_specialist
    from alc.specialist import run_specialist

    operator_layer = _find_operator_layer()
    manifest = load_manifest(operator_layer)

    specialists_dir = operator_layer.parent / manifest.specialists_dir
    try:
        specialist = load_specialist(specialists_dir, args.name)
    except FileNotFoundError:
        return _no_such_unit("specialist", args.name, specialists_dir, ".yaml")

    run_log = new_run_log_path(
        operator_layer.parent / manifest.runs_dir, "specialist", f"{args.name} {args.task}"
    )
    with bind_run_log(run_log):
        report = run_specialist(
            manifest=manifest,
            operator_layer=operator_layer,
            specialist=specialist,
            task=args.task,
            engine_override=args.engine,
        )

    act_status = "SUCCESS" if report.act.success else "FAILED"
    knowledge_status = "yes" if report.knowledge_updated else "no"
    print(f"Specialist: {report.specialist}")
    print(f"Act: {act_status}")
    print(f"Knowledge updated: {knowledge_status}")
    print()
    print(report.model_dump_json(indent=2))

    return 0 if report.act.success else 1


def cmd_flow(args: argparse.Namespace) -> int:
    """Run `alc flow <flow_name> "<task>" [--engine NAME] [--isolate]`."""
    from alc.bundle import summarize_bundle, write_bundle
    from alc.commitmsg import make_commit_message_provider
    from alc.events import bind_run_log, new_run_log_path
    from alc.flow import FlowRunner
    from alc.intake import load_flow, load_manifest
    from alc.primer import load_primer
    from alc.runner import PolicyViolationError
    from alc.worktree import IsolatedWorktree, git_toplevel, is_git_repo, runtime_provisions

    operator_layer = _find_operator_layer()
    manifest = load_manifest(operator_layer)

    flows_dir = operator_layer.parent / manifest.flows_dir
    try:
        flow = load_flow(flows_dir, args.flow_name)
    except FileNotFoundError:
        return _no_such_unit("flow", args.flow_name, flows_dir, ".yaml")

    # Validate --tier early before any work is done.
    tier_err = _validate_tier(manifest, args.tier)
    if tier_err:
        print(f"[ERROR] {tier_err}", file=sys.stderr)
        return 1

    runner = FlowRunner(manifest=manifest, operator_layer=operator_layer)

    # Per-run event log, resolved against the original project BEFORE any worktree.
    run_log = new_run_log_path(
        operator_layer.parent / manifest.runs_dir, "flow", f"{args.flow_name} {args.task}"
    )

    # Build extra_context from --primer and/or --from-bundle before branching.
    parts: list[str] = []
    if args.primer:
        primers_dir = operator_layer.parent / manifest.primers_dir
        try:
            parts.append(f"### Primer: {args.primer}\n" + load_primer(primers_dir, args.primer))
        except FileNotFoundError as exc:
            print(f"[ERROR] {exc}", file=sys.stderr)
            return 1
    if args.from_bundle:
        bundles_dir = operator_layer.parent / manifest.bundles_dir
        ref = Path(args.from_bundle)
        if not ref.exists():
            ref = bundles_dir / f"{args.from_bundle}.jsonl"
        try:
            parts.append(
                "### Prior run (bundle)\n"
                + summarize_bundle(ref, max_output_chars=manifest.bundle_output_chars)
            )
        except (FileNotFoundError, ValueError) as exc:
            print(f"[ERROR] {exc}", file=sys.stderr)
            return 1
    extra_context: str | None = "\n\n".join(parts) if parts else None

    use_isolate = args.isolate
    if use_isolate and not is_git_repo(Path.cwd()):
        print("--isolate ignored: not inside a git repository", file=sys.stderr)
        use_isolate = False

    # A committing flow (flow.commit.enabled) run under worktree isolation is
    # committed ONCE by the worktree exit-commit — using the demand's own
    # rendered message, excluding `.alc/` — instead of also firing the
    # FlowRunner's terminal commit (skip_commit=True below reconciles the two).
    # This mirrors the committing-demand path `queue.py` already runs in
    # production (queue.py:345-424). A flow with no commit block takes the
    # `else` branch below, byte-identical to before.
    is_committing_demand = use_isolate and flow.commit is not None and flow.commit.enabled
    demand_message = manifest.worktree_commit_message
    if is_committing_demand:
        try:
            demand_message = flow.commit.message.format(
                name=flow.name,
                task=(args.task.splitlines()[0] if args.task else ""),
            )
        except (KeyError, IndexError, ValueError):
            demand_message = f"chore(cycle): {flow.name}"

    if use_isolate:
        repo_root = git_toplevel(Path.cwd())
        wt = IsolatedWorktree(
            repo_root,
            label="flow",
            commit_message=demand_message,
            exclude_paths=((".alc/",) if is_committing_demand else ()),
            message_provider=make_commit_message_provider(
                manifest=manifest,
                operator_layer=operator_layer,
                workdir=repo_root,
                fallback=demand_message,
                engine_override=args.engine,
            ),
            # Provision gitignored runtime deps into the worktree so the flow's
            # stages run the real app/checks — parity with the queue drain. Empty
            # worktree_provision -> no-op, byte-identical to before.
            provisions=runtime_provisions(manifest),
        )
        wt_path = wt.__enter__()
        exc_info = (None, None, None)
        report = None
        try:
            with bind_run_log(run_log):
                report = runner.run(
                    flow=flow,
                    task=args.task,
                    engine_override=args.engine,
                    workdir=wt_path,
                    extra_context=extra_context,
                    tier_override=args.tier,
                    skip_commit=is_committing_demand,
                )
        except PolicyViolationError as exc:
            print(f"[ERROR] {exc}", file=sys.stderr)
            exc_info = (type(exc), exc, exc.__traceback__)
        except BaseException as exc:
            exc_info = (type(exc), exc, exc.__traceback__)
        finally:
            # For a committing demand the worktree owns the single commit: keep
            # it only on flow SUCCESS, otherwise discard the branch (a failed or
            # exception-raising run leaves report None/unsuccessful -> discard).
            # A non-committing isolate flow leaves commit_on_exit at its True
            # default -> today's behavior (commit iff changes).
            if is_committing_demand:
                wt.commit_on_exit = report is not None and report.success
            wt.__exit__(*exc_info)

        if exc_info[1] is not None and not isinstance(exc_info[1], PolicyViolationError):
            raise exc_info[1]

        if report is None:
            return 1

        _print_flow_report(report, as_json=getattr(args, "json", False))
        _print_isolation_result(wt)
        _emit_isolation_result(run_log, wt)
        if args.bundle:
            bundles_dir = operator_layer.parent / manifest.bundles_dir
            path = write_bundle(bundles_dir, args.flow_name, args.task, report)
            print(f"Bundle written: {path}")
        return 0 if report.success else 1

    # Non-isolated path (default).
    try:
        with bind_run_log(run_log):
            report = runner.run(
                flow=flow,
                task=args.task,
                engine_override=args.engine,
                extra_context=extra_context,
                tier_override=args.tier,
            )
    except PolicyViolationError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1

    _print_flow_report(report, as_json=getattr(args, "json", False))
    if args.bundle:
        bundles_dir = operator_layer.parent / manifest.bundles_dir
        path = write_bundle(bundles_dir, args.flow_name, args.task, report)
        print(f"Bundle written: {path}")
    return 0 if report.success else 1


def _retry_one(stem: str, manifest, operator_layer: Path) -> int:
    """Re-enqueue one failed task by its done/ filename stem; return an exit code.

    Reads the archived task + report under ``<queue_dir>/done/``, appends the
    failing stage's output to the task, and writes a new pending queue file.
    Shared by the single-stem (`alc retry <stem>`) and `--all` paths.
    """
    import yaml

    from alc.models import FlowReport, QueueTask
    from alc.queue import build_retry_task, failure_feedback, write_retry_task

    done_dir = operator_layer.parent / manifest.queue_dir / "done"

    for suffix in (".report.json", ".yaml"):
        if stem.endswith(suffix):
            stem = stem[: -len(suffix)]

    task_file = done_dir / f"{stem}.yaml"
    report_file = done_dir / f"{stem}.report.json"
    if not task_file.exists() or not report_file.exists():
        print(
            f"[ERROR] no archived task + report for '{stem}' under {done_dir}",
            file=sys.stderr,
        )
        return 1

    qt = QueueTask.model_validate(yaml.safe_load(task_file.read_text()))
    report = FlowReport.model_validate_json(report_file.read_text())
    if report.success:
        print(f"[ERROR] task '{stem}' succeeded; nothing to retry.", file=sys.stderr)
        return 1

    queue_dir = operator_layer.parent / manifest.queue_dir
    retry_qt = build_retry_task(qt, failure_feedback(report))
    path = write_retry_task(retry_qt, queue_dir, stem)
    print(
        f"Re-enqueued '{stem}' as {path.name} (attempt {retry_qt.retries}) with the "
        f"failure feedback. Run 'alc tick' or 'alc cycle <name>' to execute it."
    )
    return 0


def cmd_retry(args: argparse.Namespace) -> int:
    """Run `alc retry [stem] [--all]`: retry failed tasks carrying their feedback.

    - ``<stem>`` given: re-enqueue that single archived failure (unchanged).
    - ``--all`` (no stem): re-enqueue every outstanding failure at once.
    - neither: LIST the outstanding failures (unresolved lineages) so an operator
      doesn't have to know the opaque stem.

    Run `alc tick` / `alc cycle <name>` afterwards to execute re-enqueued tasks.
    """
    from alc.intake import load_manifest
    from alc.queue import outstanding_failures

    operator_layer = _find_operator_layer()
    manifest = load_manifest(operator_layer)

    done_dir_early = operator_layer.parent / manifest.queue_dir / "done"
    if getattr(args, "dismiss", False):
        # Close the lineage WITHOUT re-running — the missing exit for a failure
        # whose goal already happened (finding 32). Retry stays the default verb.
        if not args.stem:
            print("[ERROR] --dismiss needs the failure's stem.", file=sys.stderr)
            return 1
        from alc.queue import dismiss_failure

        try:
            root = dismiss_failure(done_dir_early, args.stem)
        except FileNotFoundError as exc:
            print(f"[ERROR] {exc}", file=sys.stderr)
            return 1
        print(f"Dismissed '{root}' — it will no longer appear as an outstanding failure.")
        print(f"Nothing was deleted; remove {manifest.queue_dir}/done/{root}.dismissed to reopen.")
        return 0

    # Single-stem path — the original behavior, unchanged.
    if args.stem:
        return _retry_one(args.stem, manifest, operator_layer)

    done_dir = operator_layer.parent / manifest.queue_dir / "done"
    failures = outstanding_failures(done_dir)

    # --all path — re-enqueue every outstanding failure (even if none, harmless).
    if args.all:
        if not failures:
            print("No failed tasks to retry.")
            return 0
        for failure in failures:
            _retry_one(failure.stem, manifest, operator_layer)
        return 0

    # List path — machine-readable (--json) or human-readable (default).
    if getattr(args, "json", False):
        from dataclasses import asdict

        from alc.output import emit_json

        emit_json([asdict(f) for f in failures])
        return 0

    if not failures:
        print("No failed tasks to retry.")
        return 0
    # One clean block per outstanding failure (most recent first).
    for failure in failures:
        print(f"{failure.stem}   (attempt {failure.retries})")
        print(f"  {failure.title}")
        print(f"  {failure.reason}")
        print()
    print("Run: alc retry <stem>   (or: alc retry --all)")
    return 0


def _enqueue_entries_from_file(path: Path) -> list[dict]:
    """Read batch entries for `alc enqueue --from-file`.

    A ``.jsonl`` file holds one JSON object per line (``task`` required; ``kind``,
    ``name``, ``id``, ``depends_on``, ``touches`` optional — each entry falls back
    to the CLI's own flags when absent). Any other extension is plain text, one
    task per line; blank lines and ``#`` comments are skipped.
    """
    import json

    if not path.is_file():
        raise FileNotFoundError(f"no such file: {path}")

    lines = path.read_text().splitlines()
    if path.suffix == ".jsonl":
        entries: list[dict] = []
        for lineno, raw_line in enumerate(lines, start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{lineno}: invalid JSON: {exc}") from exc
            if not isinstance(entry, dict) or "task" not in entry:
                raise ValueError(f"{path}:{lineno}: missing 'task' key")
            entries.append(entry)
        return entries

    return [
        {"task": line.strip()}
        for line in lines
        if line.strip() and not line.strip().startswith("#")
    ]


def cmd_enqueue(args: argparse.Namespace) -> int:
    """Run `alc enqueue <name> "<task>" [--kind flow|specialist] [--engine NAME] \
[--isolate/--no-isolate] [--id ID] [--depends-on ID] [--touches PATH] \
[--priority N] [--from-file PATH] [--json]`.

    Writes queue task file(s) straight to disk — no planner turn. Each item's
    target unit is validated (``load_flow`` / ``load_specialist``) BEFORE
    anything is written, so a typo never leaves a half-written batch behind.
    Delegates to ``dispatch_enqueue`` (``conduct.py:488``), which already applies
    ``derive_dependencies`` (serializing units whose ``touches`` overlap).

    ``--from-file`` batches multiple tasks: a ``.jsonl`` file supplies one item
    per line (each may override ``kind``/``name``/``id``/``depends_on``/
    ``touches``); any other extension is plain text, one task per line, against
    the single ``--kind``/``<name>``/``--id``/``--depends-on``/``--touches``
    given on the command line.
    """
    from pydantic import ValidationError

    from alc.conduct import dispatch_enqueue
    from alc.intake import load_blueprint, load_flow, load_manifest, load_specialist
    from alc.models import ConductorPlan, PlannedUnit

    operator_layer = _find_operator_layer()
    manifest = load_manifest(operator_layer)

    if args.from_file:
        try:
            entries = _enqueue_entries_from_file(Path(args.from_file))
        except (FileNotFoundError, ValueError) as exc:
            print(f"[ERROR] {exc}", file=sys.stderr)
            return 1
    else:
        if not args.task:
            print("[ERROR] TASK is required unless --from-file is given", file=sys.stderr)
            return 1
        entries = [{"task": args.task}]

    try:
        items = [
            PlannedUnit(
                kind=entry.get("kind", args.kind),
                name=entry.get("name", args.name),
                task=entry["task"],
                id=entry.get("id", args.id),
                depends_on=entry.get("depends_on", list(args.depends_on)),
                touches=entry.get("touches", list(args.touches)),
            )
            for entry in entries
        ]
    except ValidationError as exc:
        print(f"[ERROR] invalid enqueue entry: {exc}", file=sys.stderr)
        return 1

    flows_dir = operator_layer.parent / manifest.flows_dir
    specialists_dir = operator_layer.parent / manifest.specialists_dir
    blueprints_dir = operator_layer.parent / manifest.blueprints_dir
    for item in items:
        try:
            if item.kind == "specialist":
                load_specialist(specialists_dir, item.name)
            elif item.kind == "run":
                # Dogfood finding 8: the first task anyone drops in a queue is
                # chore-sized, and queueing one used to require a wrapper flow.
                load_blueprint(blueprints_dir, item.name)
            else:
                load_flow(flows_dir, item.name)
        except FileNotFoundError as exc:
            print(f"[ERROR] {exc}", file=sys.stderr)
            return 1

    files = dispatch_enqueue(
        ConductorPlan(items=items),
        manifest,
        operator_layer,
        engine_override=args.engine,
        isolate=args.isolate,
        prefix="enqueue",
        priority=getattr(args, "priority", 0),
    )

    if getattr(args, "json", False):
        from alc.output import emit_json

        emit_json(files)
        return 0

    print(f"Enqueued {len(files)} task(s):")
    for f in files:
        print(f"  {f}")
    print("Run: alc tick")
    return 0


def cmd_signal(args: argparse.Namespace) -> int:
    """Run `alc signal <action>`: dispatch to `ingest` or `list`."""
    if args.signal_action == "list":
        return _signal_list(args)
    return _signal_ingest(args)


def _signal_ingest(args: argparse.Namespace) -> int:
    """`alc signal ingest --kind K --source S --title T [--body B] [--from-file PATH] [--json]`.

    Writes one typed signal JSON file into ``manifest.signals_dir`` via
    ``alc.signals.ingest``. This only records the signal — it never enqueues
    anything itself; a signal becomes a demand once the ``signals`` replenish
    kind consumes it.

    ``--from-file`` reads an already-formed JSON object instead of the
    ``--kind``/``--source``/``--title``/``--body`` flags — the path the
    webhook and integration scripts use (later waves). A ``ts`` missing from
    either source defaults to now — ``Signal.ts``'s own default, not
    duplicated here (``alc serve --webhook``'s ``/signal`` route relies on
    the same default).
    """
    import json

    from pydantic import ValidationError

    from alc.intake import load_manifest
    from alc.models import Signal
    from alc.output import emit_json
    from alc.signals import ingest

    operator_layer = _find_operator_layer()
    manifest = load_manifest(operator_layer)
    signals_dir = operator_layer.parent / manifest.signals_dir

    if args.from_file:
        from_file = Path(args.from_file)
        if not from_file.is_file():
            print(f"[ERROR] no such file: {from_file}", file=sys.stderr)
            return 1
        try:
            raw = json.loads(from_file.read_text())
        except json.JSONDecodeError as exc:
            print(f"[ERROR] invalid JSON in {from_file}: {exc}", file=sys.stderr)
            return 1
        if not isinstance(raw, dict):
            print("[ERROR] --from-file must contain a single JSON object", file=sys.stderr)
            return 1
        data = dict(raw)
    else:
        if not args.kind or not args.source or not args.title:
            print(
                "[ERROR] --kind, --source and --title are required unless "
                "--from-file is given",
                file=sys.stderr,
            )
            return 1
        data = {
            "kind": args.kind,
            "source": args.source,
            "title": args.title,
            "body": args.body or "",
        }

    try:
        signal = Signal.model_validate(data)
    except ValidationError as exc:
        print(f"[ERROR] invalid signal: {exc}", file=sys.stderr)
        return 1

    path = ingest(signals_dir, signal)

    if getattr(args, "json", False):
        emit_json({"path": str(path)})
        return 0

    print(f"Signal ingested: {path.name}")
    return 0


def _signal_list(args: argparse.Namespace) -> int:
    """`alc signal list [--json]`: show the pending (not yet archived) signals.

    Never writes — sibling read-only action to `ingest`, same convention as
    `alc checks audit`/`alc checks history`.
    """
    from datetime import datetime, timezone

    from alc.intake import load_manifest
    from alc.output import emit_json
    from alc.signals import read_signals

    operator_layer = _find_operator_layer()
    manifest = load_manifest(operator_layer)
    signals_dir = operator_layer.parent / manifest.signals_dir

    pending = read_signals(signals_dir)

    if getattr(args, "json", False):
        emit_json(
            [{"path": str(p.path), **p.signal.model_dump()} for p in pending]
        )
        return 0

    if not pending:
        print("No pending signals — `alc signal ingest` writes one.")
        return 0

    for p in pending:
        ts = (
            datetime.fromtimestamp(p.signal.ts, tz=timezone.utc)
            .isoformat()
            .replace("+00:00", "Z")
        )
        print(f"[{p.signal.kind}] {p.signal.source} — {p.signal.title}  ({ts})")

    return 0


def _resolve_delivery(args: argparse.Namespace):
    """Resolve the effective DeliverySpec for `alc land`: CLI flags override the
    manifest's declared default (same override relationship as `--tier` over
    `manifest.plan_tier`).

    Never raises: `alc land` works with no Operator Layer at all (test_land.py) —
    an unreadable/missing manifest just falls back to `DeliverySpec()`'s own
    default (mode: local), so `--push`/`--pr` still work standalone off git alone.
    """
    from alc.intake import load_manifest
    from alc.models import DeliverySpec

    try:
        manifest = load_manifest(_find_operator_layer())
        delivery = manifest.delivery or DeliverySpec()
    except Exception:
        delivery = DeliverySpec()

    if getattr(args, "pr", False):
        delivery = delivery.model_copy(update={"mode": "pr"})
    elif getattr(args, "push", False):
        delivery = delivery.model_copy(update={"mode": "push"})
    return delivery


def _deliver(repo_root: Path, delivery, report) -> None:
    """The last mile: push the landed branch, optionally
    open a PR. No-op for ``mode: "local"``. NEVER raises and NEVER changes
    `alc land`'s exit code — a push/PR failure is warned about, not fatal,
    because the local land this runs after already succeeded.
    """
    from alc.delivery import build_pr_body, changed_files, current_branch, open_pr, push_branch

    branch = current_branch(repo_root)
    if branch is None:
        print("[land] could not resolve the current branch; skipping delivery.", file=sys.stderr)
        return

    ok, message = push_branch(repo_root, delivery.remote, branch)
    print(f"[land] {message}", file=sys.stdout if ok else sys.stderr)
    if not ok or delivery.mode != "pr":
        return

    files = changed_files(repo_root, delivery.base, branch)
    body = build_pr_body(report, files)
    ok, message = open_pr(repo_root, delivery.base, branch, f"alc land: {branch}", body)
    print(f"[land] {message}", file=sys.stdout if ok else sys.stderr)


def cmd_land(args: argparse.Namespace) -> int:
    """Run `alc land [branch...] [--all] [--json] [--push|--pr]`: thin shell over
    auto_merge_branches, plus the optional remote last mile (DeliverySpec).

    - No branch names and no ``--all``: LIST the unmerged ``alc/*`` branches,
      same listing convention as ``alc retry`` with no stem.
    - ``--all``: integrate every unmerged ``alc/*`` branch.
    - Explicit branch names: each must carry the ``alc/`` prefix — validated
      before anything is touched.
    - ``--push``/``--pr`` (or a manifest ``delivery: {mode: push|pr}``): after a
      successful local merge, push the current branch to the delivery remote,
      and for ``--pr`` also open a PR via `gh`. Additive only — with neither
      flag AND no non-default `delivery` declared, behavior is byte-identical
      to before this existed. A push failure or a missing `gh` never changes
      the exit code below (see `_deliver`).

    Prints ``MergeReport.summary()`` and exits 1 when anything conflicted (0
    otherwise). Outside a git repository this is a clear error, exit 1.
    """
    from alc.branches import branch_verified, list_alc_branches
    from alc.intake import load_manifest
    from alc.merge import auto_merge_branches
    from alc.worktree import git_toplevel, is_git_repo

    if args.branch:
        invalid = [b for b in args.branch if not b.startswith("alc/")]
        if invalid:
            print(f"[ERROR] not an alc/ branch: {', '.join(invalid)}", file=sys.stderr)
            return 1

    if not is_git_repo(Path.cwd()):
        print("[ERROR] not inside a git repository", file=sys.stderr)
        return 1
    repo_root = git_toplevel(Path.cwd())

    # A committed branch is not a verified one: an interrupted run whose checks
    # failed still commits its worktree. `branch_verified` names that case so the
    # listing and --all stop treating it as finished work.
    try:
        _ol = _find_operator_layer()
        _runs_dir = _ol.parent / load_manifest(_ol).runs_dir
    except (OSError, ValueError, SystemExit):
        _runs_dir = None

    def _verified(b) -> bool | None:
        return None if _runs_dir is None else branch_verified(_runs_dir, b.name, b.label)

    if args.branch:
        branches = args.branch
    elif args.all:
        unmerged = [b for b in list_alc_branches(repo_root) if not b.merged]
        unverified = [b.name for b in unmerged if _verified(b) is False]
        if unverified:
            # --all merges in bulk with no per-branch decision, so this is the
            # only moment the fact can reach the operator.
            print(
                "[WARNING] these branches committed work whose checks did NOT pass "
                "(the run failed or was interrupted):",
                file=sys.stderr,
            )
            for name in unverified:
                print(f"  {name}", file=sys.stderr)
            print(
                "  Landing them merges unverified work. Review with "
                "`alc land <branch>` one at a time, or `git diff` first.",
                file=sys.stderr,
            )
        branches = [b.name for b in unmerged]
    else:
        # List path — machine-readable (--json) or human-readable (default).
        unmerged = [b for b in list_alc_branches(repo_root) if not b.merged]
        if getattr(args, "json", False):
            from dataclasses import asdict

            from alc.output import emit_json

            emit_json([{**asdict(b), "verified": _verified(b)} for b in unmerged])
            return 0
        if not unmerged:
            print("No unmerged alc/ branches.")
            return 0
        for b in unmerged:
            mark = "  ← checks did not pass" if _verified(b) is False else ""
            print(f"{b.name}   ({b.label}){mark}")
        print("Run: alc land --all")
        return 0

    report = auto_merge_branches(repo_root, branches)
    print(report.summary())

    delivery = _resolve_delivery(args)
    if delivery.mode != "local":
        _deliver(repo_root, delivery, report)

    return 1 if report.conflicted else 0


def _confirm_delete(assume_yes: bool) -> bool:
    """Return True when a destructive `alc discard` action is confirmed.

    ``--yes`` always confirms. Otherwise prompt interactively when stdin is a
    TTY; a non-TTY invocation without ``--yes`` is never confirmed — never
    delete silently (e.g. from cron or a script).
    """
    if assume_yes:
        return True
    if not sys.stdin.isatty():
        return False
    reply = input("Proceed? [y/N] ").strip().lower()
    return reply in ("y", "yes")


def _discard_list(args: argparse.Namespace) -> int:
    """The no-argument path of `alc discard`: list the unmerged `alc/*` branches."""
    import time

    from alc.branches import list_alc_branches
    from alc.worktree import git_toplevel, is_git_repo

    if not is_git_repo(Path.cwd()):
        print("[ERROR] not inside a git repository", file=sys.stderr)
        return 1
    repo_root = git_toplevel(Path.cwd())
    unmerged = [b for b in list_alc_branches(repo_root) if not b.merged]

    if getattr(args, "json", False):
        from dataclasses import asdict

        from alc.output import emit_json

        emit_json([asdict(b) for b in unmerged])
        return 0

    if not unmerged:
        print("No unmerged alc/ branches.")
        return 0
    now = time.time()
    for b in unmerged:
        age_days = (now - b.committed_at) / 86400
        print(f"{b.name}   ({b.label}, {age_days:.1f}d old)")
    print("Run: alc discard --all-unmerged   (or pass branch names)")
    return 0


def cmd_discard(args: argparse.Namespace) -> int:
    """Run `alc discard [branch...] [--all-unmerged] [--worktrees] \
[--bundles --older-than N] [--yes] [--json]`.

    - No branch names and no flag: LIST the unmerged ``alc/*`` branches with
      their age and provenance (``AlcBranch.label``).
    - Branch names or ``--all-unmerged``: force-delete those ``alc/*`` branches
      via `delete_branches` (already refuses a non-``alc/`` ref and the
      current branch).
    - ``--worktrees``: prune stale worktree admin entries.
    - ``--bundles --older-than N``: delete bundle files older than N days from
      the manifest's ``bundles_dir``.

    Any actual deletion (branches, bundles) requires confirmation: ``--yes``,
    or an interactive "y" at a TTY prompt — refuses otherwise, never deleting
    silently.
    """
    import time

    from alc.branches import delete_branches, list_alc_branches, prune_worktrees
    from alc.worktree import git_toplevel, is_git_repo

    wants_branches = bool(args.branch) or args.all_unmerged
    if not (wants_branches or args.worktrees or args.bundles):
        return _discard_list(args)

    if args.branch:
        invalid = [b for b in args.branch if not b.startswith("alc/")]
        if invalid:
            print(f"[ERROR] not an alc/ branch: {', '.join(invalid)}", file=sys.stderr)
            return 1

    if args.bundles and args.older_than is None:
        print("[ERROR] --bundles requires --older-than N", file=sys.stderr)
        return 1

    repo_root = None
    if wants_branches or args.worktrees:
        if not is_git_repo(Path.cwd()):
            print("[ERROR] not inside a git repository", file=sys.stderr)
            return 1
        repo_root = git_toplevel(Path.cwd())

    branch_targets: list[str] = []
    if wants_branches:
        if args.branch:
            branch_targets = args.branch
        else:
            branch_targets = [b.name for b in list_alc_branches(repo_root) if not b.merged]

    bundle_targets: list[Path] = []
    if args.bundles:
        from alc.intake import load_manifest

        operator_layer = _find_operator_layer()
        manifest = load_manifest(operator_layer)
        bundles_dir = operator_layer.parent / manifest.bundles_dir
        if bundles_dir.is_dir():
            cutoff = time.time() - args.older_than * 86400
            bundle_targets = [
                p for p in bundles_dir.glob("*.jsonl") if p.stat().st_mtime < cutoff
            ]

    if (branch_targets or bundle_targets) and not _confirm_delete(args.yes):
        print(
            "[ERROR] refusing to delete without confirmation; pass --yes or "
            "confirm interactively",
            file=sys.stderr,
        )
        return 1

    if wants_branches:
        # runs_dir lets delete_branches drop a discarded isolated run's archived
        # report so it stops counting in audit / Mix Health. Best-effort: if the
        # operator layer can't be resolved, skip the report cleanup, never fail.
        runs_dir = None
        try:
            from alc.intake import load_manifest

            ol = _find_operator_layer()
            runs_dir = ol.parent / load_manifest(ol).runs_dir
        except Exception:  # noqa: BLE001 — cleanup is best-effort, never fatal
            runs_dir = None
        deleted = (
            delete_branches(repo_root, branch_targets, runs_dir=runs_dir)
            if branch_targets
            else []
        )
        if deleted:
            print(f"Deleted {len(deleted)} branch(es): {', '.join(deleted)}")
        else:
            print("Deleted 0 branches.")

    if args.worktrees:
        pruned = prune_worktrees(repo_root)
        print(f"Pruned {pruned} stale worktree(s).")

    if args.bundles:
        for p in bundle_targets:
            p.unlink()
        print(f"Deleted {len(bundle_targets)} bundle file(s) older than {args.older_than}d.")

    return 0


def cmd_explore(args: argparse.Namespace) -> int:
    """Run `alc explore <blueprint> "<task>" --variants N [--engine ...] [--tier ...]`.

    N copies of the SAME Blueprint+task, each dispatched via ``run_fanout`` into
    its own isolated worktree, branched ``alc/variant-<n>-<hex8>``. Repeating
    ``--engine`` and/or ``--tier`` produces their cartesian product (crossed with
    ``--variants``); with neither, ``--variants N`` alone repeats the manifest's
    default engine and the Blueprint's own tier N times.

    NEVER auto-merges — that is the whole point of exploring variants side by
    side, a property of this command itself (no flag turns it on). Run
    `alc compare` then `alc adopt` to close the loop.
    """
    from alc.fanout import run_fanout
    from alc.intake import load_manifest
    from alc.variants import variant_row, write_variant

    if args.variants < 1:
        print("[ERROR] --variants must be >= 1", file=sys.stderr)
        return 1

    operator_layer = _find_operator_layer()
    manifest = load_manifest(operator_layer)

    tiers = args.tier or [None]
    for t in tiers:
        tier_err = _validate_tier(manifest, t)
        if tier_err:
            print(f"[ERROR] {tier_err}", file=sys.stderr)
            return 1
    engines = args.engine or [None]

    units: list[dict] = []
    for _ in range(args.variants):
        for engine in engines:
            for tier in tiers:
                n = len(units) + 1
                units.append({
                    "kind": "blueprint",
                    "name": args.blueprint,
                    "task": args.task,
                    "engine": engine,
                    "tier": tier,
                    "label": f"variant-{n}",
                })

    try:
        fanout = run_fanout(
            manifest, operator_layer, units, max_workers=manifest.fanout_concurrency
        )
    except RuntimeError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1

    # Archive every variant that actually committed, so a later (separate) `alc
    # compare`/`alc adopt` invocation can read it back by branch name.
    variants_dir = operator_layer.parent / manifest.variants_dir
    rows = []
    for unit_spec, unit_result in zip(units, fanout.units):
        rows.append(variant_row(unit_result, unit_spec["engine"], unit_spec["tier"]))
        if unit_result.branch:
            write_variant(
                variants_dir,
                unit_result.branch,
                unit_spec["engine"],
                unit_spec["tier"],
                unit_result,
            )

    if getattr(args, "json", False):
        from alc.output import emit_json

        emit_json(rows)
        return 0 if fanout.success else 1

    _print_variant_table(rows)
    return 0 if fanout.success else 1


def cmd_compare(args: argparse.Namespace) -> int:
    """Run `alc compare [<branch|stem>...]`: variants side by side.

    With explicit refs, reads each ref's archive from ``manifest.variants_dir``
    (written by `alc explore`) — either the full ``alc/variant-…`` branch name or
    its bare stem. A ref with no archive is reported on stderr and the command
    exits 1.

    Bare (no refs) lists EVERY archived variant via the one shared lister
    ``variants.list_all_variants`` — so the CLI's bare read shows exactly the same
    set (and order) as the UI Compare view (CLI ≡ UI, they can never drift).
    """
    from alc.intake import load_manifest
    from alc.variants import list_all_variants, mark_live, read_variant, variant_row

    operator_layer = _find_operator_layer()
    manifest = load_manifest(operator_layer)
    variants_dir = operator_layer.parent / manifest.variants_dir

    missing: list[str] = []
    if args.refs:
        rows = []
        for ref in args.refs:
            found = read_variant(variants_dir, ref)
            if found is None:
                missing.append(ref)
                continue
            unit, engine, tier = found
            rows.append(variant_row(unit, engine, tier))
        if missing:
            print(f"[ERROR] no archived variant for: {', '.join(missing)}", file=sys.stderr)
    else:
        # Bare `alc compare` = the read view over EVERY archived variant — the same
        # set (and order) the UI Compare view lists, via the one shared lister.
        rows = list_all_variants(variants_dir)
        if not rows:
            # Empty-state guard sits BEFORE the `--diff` block on purpose: a bare
            # call on an empty project returns the friendly empty state (rc 0) and
            # never trips the "not inside a git repository (diffs unavailable)"
            # rc-1 path below.
            if getattr(args, "json", False):
                from alc.output import emit_json

                emit_json([])
                return 0
            print(
                "No archived variants yet — run `alc explore <blueprint> <task>` "
                "to create some."
            )
            return 0

    # Mark each row's liveness — does its `alc/variant-*` branch still exist? A
    # resolved variant (adopted or discarded) has a GONE branch: the Compare
    # surface must not offer Diff/Adopt on it (both would 404). ONE for-each-ref
    # for the whole table (via `mark_live`); off git -> every row resolved (no
    # repository, no branches, nothing actionable). Resolved rows stay in the
    # listing as history — never filtered — and are NOT errors (exit codes
    # unchanged). `repo_root` is then reused by the `--diff` block below (KISS).
    from alc.worktree import git_toplevel, is_git_repo

    repo_root = git_toplevel(Path.cwd()) if is_git_repo(Path.cwd()) else None
    mark_live(rows, repo_root)

    # `--diff` enriches each row with its branch's unified diff so metric-tied
    # variants (identical checks/scorecard/cost) can still be told apart. It
    # reuses the ONE shared helper `branches.branch_diff` — the same read-only
    # `git diff <base>...<branch>` the UI's `service.variant_diff` calls (DRY).
    diff_unavailable = False
    if getattr(args, "diff", False):
        from alc.branches import branch_diff

        if repo_root is None:
            # No repo -> no diffs; but the summary table the operator asked for
            # still prints. A hard error line + exit 1 signals the degradation.
            print(
                "[ERROR] not inside a git repository (diffs unavailable)",
                file=sys.stderr,
            )
            diff_unavailable = True
        else:
            for row in rows:
                branch = row.get("branch")
                if not branch:
                    continue  # an uncommitted variant has no branch to diff
                bd = branch_diff(repo_root, branch)
                # A missing branch (bd is None) is common AFTER adopt deletes the
                # losers — per-variant degradation, never a command failure.
                row["diff"] = bd.text if bd else None
                row["diff_truncated"] = bool(bd and bd.truncated)

    if getattr(args, "json", False):
        from alc.output import emit_json

        emit_json(rows)
        return 1 if (missing or diff_unavailable) else 0

    _print_variant_table(rows)
    return 1 if (missing or diff_unavailable) else 0


def cmd_adopt(args: argparse.Namespace) -> int:
    """Run `alc adopt <branch> [--yes] [--json]`.

    Integrates the chosen variant branch (reusing ``auto_merge_branches``) and
    discards every OTHER unmerged ``alc/variant-*`` branch (via
    ``delete_branches``) — closing the explore -> compare -> adopt loop.
    `explore` never merges; this is the one place a variant becomes real.

    Requires the same confirmation `alc discard` does: ``--yes``, or an
    interactive "y" at a TTY prompt (see ``_confirm_delete``). Without it,
    refuses outright — nothing is merged, nothing is deleted, never a partial
    adopt.
    """
    import re

    from alc.branches import delete_branches, list_alc_branches
    from alc.merge import auto_merge_branches
    from alc.worktree import git_toplevel, is_git_repo

    if not args.branch.startswith("alc/"):
        print(f"[ERROR] not an alc/ branch: {args.branch}", file=sys.stderr)
        return 1

    if not is_git_repo(Path.cwd()):
        print("[ERROR] not inside a git repository", file=sys.stderr)
        return 1
    repo_root = git_toplevel(Path.cwd())

    if not _confirm_delete(args.yes):
        print(
            "[ERROR] refusing to adopt without confirmation; pass --yes or "
            "confirm interactively",
            file=sys.stderr,
        )
        return 1

    variant_re = re.compile(r"^alc/variant-\d+-[0-9a-f]{8}$")
    losers = [
        b.name
        for b in list_alc_branches(repo_root)
        if not b.merged and b.name != args.branch and variant_re.match(b.name)
    ]

    merge_report = auto_merge_branches(repo_root, [args.branch])
    discarded = delete_branches(repo_root, losers) if losers else []

    if getattr(args, "json", False):
        from alc.output import emit_json

        emit_json({
            "merged": merge_report.merged,
            "conflicted": merge_report.conflicted,
            "discarded": discarded,
        })
        return 1 if merge_report.conflicted else 0

    print(merge_report.summary())
    if discarded:
        print(f"Discarded {len(discarded)} losing variant(s): {', '.join(discarded)}")
    else:
        print("Discarded 0 losing variant(s).")
    return 1 if merge_report.conflicted else 0


def cmd_status(args: argparse.Namespace) -> int:
    """Run `alc status [--json]`: aggregate health signals for external monitoring.

    Reports pending queue tasks, outstanding (retryable) failures, every
    Autonomous Loop's persisted state — flagging any 'stopped' one with its
    ``stopped_reason`` — and the count of unmerged ``alc/*`` branches (0 outside
    a git repository).

    This command NEVER fails on what it finds: it always exits 0. It is meant
    as the target of external monitoring — the CONSUMER (a monitoring script, a
    dashboard poll) decides what in the payload counts as unhealthy.
    """
    from alc.branches import list_alc_branches
    from alc.intake import load_manifest
    from alc.loop import load_loop_state, loops_dir, state_path
    from alc.queue import outstanding_failures
    from alc.worktree import git_toplevel, is_git_repo

    operator_layer = _find_operator_layer()
    manifest = load_manifest(operator_layer)
    project_root = operator_layer.parent

    queue_dir = project_root / manifest.queue_dir
    pending = len(list(queue_dir.glob("*.yaml"))) if queue_dir.is_dir() else 0

    failures = outstanding_failures(queue_dir / "done")

    loops_directory = loops_dir(manifest, operator_layer)
    loops: list[dict] = []
    if loops_directory.is_dir():
        for path in sorted(loops_directory.glob("*.yaml")):
            state = load_loop_state(state_path(loops_directory, path.stem), path.stem)
            loops.append(
                {
                    "name": state.name,
                    "status": state.status,
                    "cycle": state.cycle,
                    "stopped_reason": state.stopped_reason,
                }
            )

    branches = 0
    if is_git_repo(project_root):
        branches = len(
            [b for b in list_alc_branches(git_toplevel(project_root)) if not b.merged]
        )

    payload = {
        "pending": pending,
        "outstanding_failures": len(failures),
        "loops": loops,
        "unmerged_branches": branches,
    }

    if getattr(args, "json", False):
        from alc.output import emit_json

        emit_json(payload)
        return 0

    print(f"Pending queue tasks:     {pending}")
    print(f"Outstanding failures:    {len(failures)}")
    print(f"Unmerged alc/ branches:  {branches}")
    if loops:
        print("Loops:")
        for loop in loops:
            line = f"  {loop['name']}: {loop['status']} (cycle {loop['cycle']})"
            if loop["status"] == "stopped":
                line += f", stopped_reason={loop['stopped_reason']}"
            print(line)
    else:
        print("Loops:                   (none)")
    return 0


def cmd_runs(args: argparse.Namespace) -> int:
    """Run `alc runs list|show|tail`: inspect run logs (``.alc/runs/*.jsonl``).

    - ``list [--limit N] [--offset N] [--json]``: newest-first page of run summaries.
    - ``show <stem> [--json]``: every parsed event for one run.
    - ``tail <stem> [-n N]``: the last N events of one run (default 20).

    No ``--follow``: the web IDE already streams a live run over WebSocket, so a
    polling loop here would only duplicate it.
    """
    import json

    from alc.intake import load_manifest
    from alc.runs import STALE_MARGIN_S, list_runs, read_run

    operator_layer = _find_operator_layer()
    manifest = load_manifest(operator_layer)
    runs_dir = operator_layer.parent / manifest.runs_dir
    stale_after = manifest.default_timeout_s + STALE_MARGIN_S

    if args.runs_action == "list":
        result = list_runs(runs_dir, stale_after, limit=args.limit, offset=args.offset)
        if getattr(args, "json", False):
            from alc.output import emit_json

            emit_json(result)
            return 0
        if not result["runs"]:
            print("No runs.")
            return 0
        for run in result["runs"]:
            status = "finished" if run["finished"] else ("stale" if run["stale"] else "running")
            net = run["net_lines"]
            net_str = f"{net:+d}" if net is not None else "n/a"
            # The stem's slug is a lossy prefix of the task: a run asked to fix
            # the closing advice in install.sh becomes "run-chore-in-docs-site-
            # scripts-dist-install", which reads as a run about installing. The
            # title says what was actually asked, so it leads; the stem stays
            # whole on its own line because it is what you paste into
            # `alc runs show`.
            title = (run.get("title") or "").strip()
            if title:
                unit = run.get("unit") or ""
                print(f"{title[:100]}{'…' if len(title) > 100 else ''}{f'   [{unit}]' if unit else ''}")
            print(f"  {run['stem']}   ({run['kind']}, {status})   net-lines={net_str}")
        print(f"Showing {len(result['runs'])} of {result['total']} run(s).")
        return 0

    # show / tail both resolve one run by stem.
    try:
        result = read_run(runs_dir, args.stem, stale_after)
    except FileNotFoundError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1

    if args.runs_action == "show":
        if getattr(args, "json", False):
            from alc.output import emit_json

            emit_json(result)
            return 0
        events = result["events"]
    else:  # tail
        events = result["events"][-args.lines :] if args.lines > 0 else result["events"]

    for event in events:
        print(json.dumps(event, default=str))
    return 0


def cmd_checks(args: argparse.Namespace) -> int:
    """Run `alc checks <action>`: dispatch to `audit` or `history`."""
    if args.checks_action == "history":
        return _checks_history(args)
    # Bare `alc checks` (checks_action None) = the audit read view — never a usage
    # error. Both handlers read `--json` via getattr, so the missing attr is safe.
    return _checks_audit(args)


def _checks_audit(args: argparse.Namespace) -> int:
    """`alc checks audit [--json]`: re-detect stacks and PROPOSE check upgrades.

    Never writes — compares the Manifest's current check_sets (and each
    Blueprint's resolved checks) against what `detect_stacks()` finds today,
    including live binary availability, and prints the diff for the operator
    to apply by hand (or reconcile via `alc team hire --force`).
    """
    import json

    from alc.checks import audit_checks
    from alc.intake import load_all_blueprints, load_manifest

    operator_layer = _find_operator_layer()
    project_root = operator_layer.parent
    manifest = load_manifest(operator_layer)
    blueprints = load_all_blueprints(manifest, operator_layer)

    report = audit_checks(manifest, project_root, blueprints)

    if getattr(args, "json", False):
        from dataclasses import asdict

        from alc.output import emit_json

        emit_json(asdict(report))
        return 0

    if not report.check_sets and not report.smoke_only_blueprints:
        print("No upgrades proposed — check_sets are current with the detected stack(s).")
    elif not report.has_proposals:
        # Everything below is informational (unavailable-only sets): an honest
        # header instead of "No upgrades proposed" directly above a printed list.
        print(
            "No actionable upgrades — the checks below stay commented out "
            "until their tools are installed."
        )

    for cs in report.check_sets:
        status = "NEW" if cs.is_new else "existing"
        print(f"check_set '{cs.set_name}' ({status}):")
        for name, command in cs.add:
            print(f"  + {name}: {' '.join(command)}  (binary available — propose adding)")
            # A ready-to-paste manifest fragment: the `- name:` / `command:` lines
            # indented exactly as they sit under `check_sets: <set>:` in the Manifest.
            print(f"      - name: {name}")
            print(f"        command: {json.dumps(command)}")
        for name, command in cs.unavailable:
            # A hint marks a gap the PROJECT can satisfy (declared dev dependency,
            # missing env manager) — actionable, unlike a tool it simply never uses.
            reason = cs.install_hints.get(name, "binary not on PATH — stays commented out")
            print(f"  - {name}: {' '.join(command)}  ({reason})")

    for bp in report.smoke_only_blueprints:
        if bp.stacks:
            stacks_desc = ", ".join(bp.stacks)
            print(
                f"Blueprint '{bp.blueprint}' resolves to only the smoke placeholder while "
                f"{stacks_desc} is detected — consider wiring real checks."
            )
        else:
            print(
                f"Blueprint '{bp.blueprint}' verifies nothing but the smoke placeholder "
                "and no stack was detected — ALC's guarantees are only as strong as your "
                "checks. Run `alc onboard` to harvest this project's own checks (Makefile "
                "targets, package.json scripts, …) into check_sets, or add real ones by "
                "hand to your manifest (also editable in the UI: Checks / Manifest)."
            )

    return 0


def _checks_history(args: argparse.Namespace) -> int:
    """`alc checks history [--json]`: pass-rate, mean duration and a flake score
    per check, aggregated from the run logs' `check_finished` events.

    Sibling action to `audit` — never writes.
    """
    from dataclasses import asdict

    from alc.checks import check_history
    from alc.intake import load_manifest

    operator_layer = _find_operator_layer()
    manifest = load_manifest(operator_layer)
    runs_dir = operator_layer.parent / manifest.runs_dir

    history = check_history(runs_dir)

    if getattr(args, "json", False):
        from alc.output import emit_json

        emit_json([asdict(h) for h in history])
        return 0

    if not history:
        print("No check history yet — run `alc run`/`alc tick` to populate the run logs.")
        return 0

    for h in history:
        print(
            f"{h.name}: pass_rate={h.pass_rate:.0%} runs={h.runs} "
            f"mean_duration={h.mean_duration_s:.2f}s flake_score={h.flake_score:.2f}"
        )

    return 0


def cmd_metrics(args: argparse.Namespace) -> int:
    """Run `alc metrics [--check NAME] [--json]`: the metric-check time series
    recorded in the project's ledger.

    Read-only — a metric's baseline is only ever recorded by the Verifier while
    running a Blueprint's checks (`alc run`/`alc flow`/`alc tick`/…).
    """
    from dataclasses import asdict
    from datetime import datetime, timezone

    from alc.intake import load_manifest
    from alc.metrics import ledger_path, metric_series

    operator_layer = _find_operator_layer()
    manifest = load_manifest(operator_layer)
    path = ledger_path(operator_layer.parent / manifest.metrics_dir)

    series = metric_series(path, check=args.check)

    if getattr(args, "json", False):
        from alc.output import emit_json

        emit_json({name: [asdict(p) for p in points] for name, points in series.items()})
        return 0

    if not series:
        print(
            "No metric history yet — run a Blueprint with a `metric` check to "
            "populate the ledger."
        )
        return 0

    for name in sorted(series):
        print(f"{name}:")
        for point in series[name]:
            ts = datetime.fromtimestamp(point.ts, tz=timezone.utc).isoformat().replace(
                "+00:00", "Z"
            )
            # A rejected point never became the check's baseline (see
            # alc.metrics.latest_accepted_measurement) — flagged here so a
            # reader can tell which points the gate actually accepted.
            status = "accepted" if point.passed else "REJECTED"
            if point.delta is None:
                print(
                    f"  {ts}  value={point.value:g}  run={point.run}  "
                    f"(first measurement, {status})"
                )
            else:
                print(
                    f"  {ts}  value={point.value:g}  delta={point.delta:+g}  "
                    f"trend={point.trend}  run={point.run}  status={status}"
                )

    return 0


def cmd_artifacts(args: argparse.Namespace) -> int:
    """Run `alc artifacts [<stem>] [--json]`: list a run's captured e2e evidence — screenshots, curled responses, the health-poll log,
    or whatever else a `needs_service` Blueprint's `capture:` command produced.

    With no `<stem>`, shows the most recent run that captured any artifact.
    Read-only: artifacts are only ever produced by `alc run`/`alc flow`/`alc
    tick`/… against a Blueprint that declares `capture:`.
    """
    from alc.artifacts import artifact_type, latest_run_with_artifacts, run_artifacts
    from alc.intake import load_manifest
    from alc.output import emit_json

    operator_layer = _find_operator_layer()
    manifest = load_manifest(operator_layer)
    runs_dir = operator_layer.parent / manifest.runs_dir

    if args.stem:
        try:
            result = run_artifacts(runs_dir, args.stem)
        except FileNotFoundError as exc:
            print(f"[ERROR] {exc}", file=sys.stderr)
            return 1
    else:
        result = latest_run_with_artifacts(runs_dir)
        if result is None:
            if getattr(args, "json", False):
                emit_json({"stem": None, "artifacts": []})
                return 0
            print(
                "No run has captured any artifacts yet — a Blueprint's `capture:` "
                "command (on a `needs_service` run) populates them."
            )
            return 0

    if getattr(args, "json", False):
        emit_json(
            {
                "stem": result.stem,
                "artifacts": [
                    {"path": p, "type": artifact_type(p)} for p in result.artifacts
                ],
            }
        )
        return 0

    if not result.artifacts:
        print(f"Run '{result.stem}' captured no artifacts.")
        return 0

    print(f"Run: {result.stem}")
    for p in result.artifacts:
        print(f"  {p}   ({artifact_type(p)})")
    return 0


def cmd_schedule(args: argparse.Namespace) -> int:
    """Run `alc schedule install|list|remove <tick|cycle NAME> --every 15m`.

    Generates and manages the crontab entry that fires `alc tick` or
    `alc cycle NAME` on a cadence — the first cron
    line an operator would otherwise have to compose by hand.
    """
    if args.schedule_action == "install":
        return _schedule_install(args)
    if args.schedule_action == "remove":
        return _schedule_remove(args)
    return _schedule_list(args)


def _schedule_target(args: argparse.Namespace) -> tuple[str, str | None] | None:
    """Validate target/name and return (target, name), or None (prints the error).

    'cycle' requires a loop NAME; 'tick' takes none — a NAME given to 'tick' is
    almost certainly a typo for 'cycle', so it is rejected rather than ignored.
    """
    target = args.target
    name = args.name
    if target == "cycle" and not name:
        print("[ERROR] `schedule ... cycle` requires a loop NAME", file=sys.stderr)
        return None
    if target == "tick" and name:
        print(f"[ERROR] `schedule ... tick` takes no NAME (got '{name}')", file=sys.stderr)
        return None
    return target, (name if target == "cycle" else None)


def _schedule_label(target: str, name: str | None) -> str:
    """Human label for a target/name pair, e.g. 'cycle deliver' or 'tick'."""
    return f"{target} {name}" if name else target


def _schedule_install(args: argparse.Namespace) -> int:
    from alc.schedule import (
        build_line,
        has_crontab,
        parse_every,
        read_crontab,
        resolve_binary,
        upsert,
        write_crontab,
    )

    resolved = _schedule_target(args)
    if resolved is None:
        return 1
    target, name = resolved

    try:
        cron_expr = parse_every(args.every)
    except ValueError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1

    project_root = _find_operator_layer().parent
    line = build_line(target, name, project_root, cron_expr, resolve_binary())

    if not has_crontab():
        print("No `crontab` on this platform — add this line to your scheduler:")
        print(f"  {line}")
        return 0

    if not write_crontab(upsert(read_crontab(), target, name, line)):
        print("[ERROR] could not write the crontab — add this line yourself (crontab -e):")
        print(f"  {line}")
        return 1

    print(f"Installed: {line}")
    return 0


def _schedule_remove(args: argparse.Namespace) -> int:
    from alc.schedule import has_crontab, marker, read_crontab, remove, write_crontab

    resolved = _schedule_target(args)
    if resolved is None:
        return 1
    target, name = resolved
    label = _schedule_label(target, name)

    if not has_crontab():
        print("No `crontab` on this platform — nothing to remove.")
        return 0

    lines = read_crontab()
    tag = marker(target, name)
    matched = [line for line in lines if tag in line]
    if not matched:
        print(f"No scheduled entry for '{label}'.")
        return 0

    if not write_crontab(remove(lines, target, name)):
        print(
            "[ERROR] could not update the crontab — remove this line yourself "
            "(crontab -e):",
            file=sys.stderr,
        )
        for line in matched:
            print(f"  {line}", file=sys.stderr)
        return 1

    print(f"Removed the scheduled entry for '{label}'.")
    return 0


def _schedule_list(args: argparse.Namespace) -> int:
    from alc.schedule import has_crontab, list_entries, read_crontab

    if not has_crontab():
        print("No `crontab` on this platform.")
        return 0

    entries = list_entries(read_crontab())

    if getattr(args, "json", False):
        from alc.output import emit_json

        emit_json(entries)
        return 0

    if not entries:
        print("No ALC-scheduled entries. Run: alc schedule install tick --every 15m")
        return 0
    for line in entries:
        print(line)
    return 0


def cmd_audit(args: argparse.Namespace) -> int:
    """Run `alc audit --since 7d|24h|30m [--json]`: aggregate archived queue reports.

    Rolls up every ``done/*.report.json`` archived at/after the trailing window
    into task counts, Scorecard totals/averages, changed files, and accumulated
    engine Usage (input/output tokens, cost). An unparseable ``--since`` is a
    clear error, not a traceback.
    """
    import time
    from dataclasses import asdict

    from alc.audit import audit_window, parse_since
    from alc.intake import load_manifest

    try:
        seconds = parse_since(args.since)
    except ValueError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1

    operator_layer = _find_operator_layer()
    manifest = load_manifest(operator_layer)
    done_dir = operator_layer.parent / manifest.queue_dir / "done"
    runs_dir = operator_layer.parent / manifest.runs_dir

    window = audit_window(done_dir, time.time() - seconds, extra_report_dir=runs_dir)

    if getattr(args, "json", False):
        from alc.output import emit_json

        emit_json(asdict(window))
        return 0

    print(f"Since:            {args.since} ago")
    print(
        f"Tasks:            {window.tasks_total} total, "
        f"{window.tasks_ok} ok, {window.tasks_failed} failed"
    )
    print(
        f"Scorecard (avg):  span={window.span_avg:.2f} passes={window.passes_avg:.2f} "
        f"streak={window.streak_avg:.2f} touch={window.touch_avg:.2f}"
    )
    print(f"Changed files:    {window.changed_files_total}")
    print(
        f"Usage:            input={window.input_tokens_total} "
        f"output={window.output_tokens_total} cost_usd={window.cost_usd_total:.4f}"
    )
    return 0


def _lan_address() -> str | None:
    """The address another device on this network would type, or None.

    Opens a UDP socket toward a public address and reads back the local end.
    No packet is sent — UDP connect only picks a route — so this works offline
    against a LAN and needs no dependency. Returns None when there is no route
    at all, which is honest: better no address than a wrong one.
    """
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        try:
            sock.connect(("192.0.2.1", 1))  # TEST-NET-1: reserved, never routed
            return str(sock.getsockname()[0])
        except OSError:
            return None


def cmd_ui(args: argparse.Namespace) -> int:
    """Run `alc ui [--host H | --lan] [--port P] [--ui-dist PATH] [--no-ui]`: serve the web IDE.

    The web backend lives behind the optional ``ui`` extra (fastapi/uvicorn/
    watchfiles). When it is not installed, print a clear install hint and exit 1
    rather than raising an ImportError traceback.

    The frontend is served BY DEFAULT. Resolution order (unless --no-ui): an
    explicit --ui-dist (error + exit 1 if it has no index.html), then
    ALC_UI_DIST (a warning + skip when invalid), then the bundled build shipped
    inside the package, else API-only with a hint on how to obtain the UI.
    """
    import os

    try:
        import uvicorn

        from alc.ui.frontend import FrontendError, resolve_frontend
        from alc.ui.registry import default_registry_path
        from alc.ui.server import create_app
    except ModuleNotFoundError:
        print(
            "[ERROR] `alc ui` requires the 'ui' extra (fastapi, uvicorn, watchfiles). "
            'Install it with: uv tool install "alc-runtime[ui]"',
            file=sys.stderr,
        )
        return 1

    try:
        frontend = resolve_frontend(
            args.ui_dist, os.environ.get("ALC_UI_DIST"), no_ui=args.no_ui
        )
    except FrontendError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1

    if frontend is not None:
        location = f"frontend: {frontend}"
    else:
        location = "API only"
        if not args.no_ui:
            print(
                "No frontend build found. Build the alc-ui frontend "
                "(npm run build:alc) or pass --ui-dist PATH to serve it; "
                "running API-only for now.",
                file=sys.stderr,
            )

    # getattr throughout, not args.X: cmd_ui is also called programmatically with
    # a hand-built Namespace that predates these flags — a new option must never
    # break an existing caller.
    host = "0.0.0.0" if getattr(args, "lan", False) else args.host  # noqa: S104
    token = getattr(args, "token", None) or os.environ.get("ALC_UI_TOKEN") or None
    # Reaching a non-loopback interface without a token exposes every registered
    # project — and the exec endpoints that RUN things — to the local network.
    # Warn loudly; never silently refuse, since the operator may be behind a
    # trusted tunnel and knows better than we do.
    if not token and host not in ("127.0.0.1", "localhost", "::1"):
        print(
            f"[WARNING] Binding {host} without --token: anyone who can reach "
            "this port can read every registered project and dispatch runs. "
            "Pass --token T (or set ALC_UI_TOKEN), or bind 127.0.0.1 and use a tunnel.",
            file=sys.stderr,
        )

    # Every other command acts on the project you are standing in. `alc ui` alone
    # read the global registry and ignored the cwd, so `cd my-project && alc ui`
    # opened a list of whatever had been registered before — and to reach the
    # project you were in you had to type its absolute path into a dialog.
    #
    # The registry stays global; this only decides where the tool lands. Adding
    # is idempotent and validates, so a directory that is not an ALC project
    # leaves everything exactly as it was.
    landing = ""
    here = _find_operator_layer().parent
    if (here / ".alc" / "manifest.yaml").is_file():
        from alc.ui.registry import ProjectRegistry

        try:
            registry = ProjectRegistry(default_registry_path())
            known = {p.id for p in registry.list()}
            current = registry.add(here)
            landing = f"/projects/{current.id}"
            if current.id not in known:
                # It writes to a file shared by every project; say so rather than
                # changing persistent state silently.
                print(f"Registered {current.name} ({here}) in the project list.", flush=True)
        except Exception:  # noqa: BLE001 — never let this stop the server starting
            landing = ""

    app = create_app(default_registry_path(), ui_dist=frontend, token=token)
    auth_note = " · token required" if token else ""
    # flush: stdout is block-buffered when piped, and these lines are the whole
    # point of the command — they must not sit in a buffer behind uvicorn's own
    # output, or vanish entirely if the process is stopped.
    print(f"Serving alc ui ({location}{auth_note})", flush=True)
    # 0.0.0.0 is a bind address, not somewhere anyone can browse to. Print what
    # the operator actually types — here, and on whatever else is on the network:
    # a second laptop, a desktop, a tablet, a phone.
    shown = "127.0.0.1" if host == "0.0.0.0" else host  # noqa: S104
    query = f"{landing or '/'}?t={token}" if token else landing
    print(f"  Local:   http://{shown}:{args.port}{query}", flush=True)
    if host == "0.0.0.0":  # noqa: S104
        lan = _lan_address()
        print(
            f"  Network: http://{lan}:{args.port}{query}"
            if lan
            else "  Network: no route to this machine from the network",
            flush=True,
        )
    elif token:
        print(f"Hand the token to a browser once: http://{host}:{args.port}{query}", flush=True)
    uvicorn.run(app, host=host, port=args.port)
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    """Run `alc serve --webhook [--host H] [--port P] [--token T]`: a minimal HTTP
    door in front of signal intake and the enqueue path.

    `--webhook` is required — the only mode `alc serve` offers today — so the
    command reads as an explicit choice rather than an accidental default. It
    never executes anything: `POST /signal` and `POST /enqueue` only validate a
    payload and write a file; `alc tick` / `alc cycle` drains the queue later,
    on its own turn.
    """
    from alc.intake import load_manifest
    from alc.webhook import serve

    operator_layer = _find_operator_layer()
    manifest = load_manifest(operator_layer)

    server = serve(args.host, args.port, operator_layer, manifest, args.token)
    print(f"Serving alc webhook on http://{args.host}:{server.server_port}")
    try:
        server.serve_forever()
    finally:
        server.server_close()
    return 0


def _build_parser() -> argparse.ArgumentParser:
    """Build the fully-configured `alc` argument parser.

    Extracted from ``main()`` as a pure, behavior-neutral move so tests can
    introspect the argparse defaults — e.g. that a bare ``audit`` defaults
    ``--since`` to ``7d`` — without executing any command. ``main()`` holds the
    returned parser so ``parser.error(...)`` still reports usage against it.
    """
    parser = argparse.ArgumentParser(
        prog="alc",
        description="ALC — Agentic Layer Compiler & Runtime",
    )
    from alc.setup_skill import _resolve_version

    parser.add_argument(
        "--version", action="version", version=f"alc {_resolve_version()}"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # alc init [--force] [--setup] [--stage pre-pmf|growth|strong-pmf]
    init_parser = subparsers.add_parser(
        "init",
        help="Scaffold a default .alc/ (the Operator Layer) into the current directory.",
    )
    init_parser.add_argument(
        "--force",
        action="store_true",
        default=False,
        help="Overwrite an existing .alc/ directory.",
    )
    init_parser.add_argument(
        "--setup",
        action="store_true",
        default=False,
        help="Also install/update the user-level editor skill after scaffolding.",
    )
    init_parser.add_argument(
        "--engine",
        default="claude-code",
        help="Engine whose editor skill to install with --setup (default: claude-code).",
    )
    init_parser.add_argument(
        "--stage",
        choices=["pre-pmf", "growth", "strong-pmf"],
        default=None,
        help=(
            "Also hire the Archetype Pack combo for this stage's mix "
            "(see `alc team list`). Omit to only print a discovery hint."
        ),
    )

    # alc onboard [--dry-run] [--yes] [--json] [--stage pre-pmf|growth|strong-pmf]
    onboard_parser = subparsers.add_parser(
        "onboard",
        help=(
            "Harvest this project's own declared checks (Makefile targets, "
            "package.json scripts, …) and PROPOSE adopting them into check_sets; "
            "nothing is written without approval. The follow-up to `alc init`."
        ),
    )
    onboard_parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help=(
            "Print the proposal preview and exit; write nothing. Also the default "
            "when stdout is not a TTY and --yes was not passed."
        ),
    )
    onboard_parser.add_argument(
        "--yes",
        action="store_true",
        default=False,
        help="Apply the full proposal non-interactively (checks + opt-ins + --stage).",
    )
    onboard_parser.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="Print the proposal as JSON (machine-readable) and exit; write nothing.",
    )
    onboard_parser.add_argument(
        "--stage",
        choices=["pre-pmf", "growth", "strong-pmf"],
        default=None,
        help=(
            "Record this product stage (advisory — never changes execution). "
            "Omit to be asked interactively."
        ),
    )
    onboard_parser.add_argument(
        "--assist",
        action="store_true",
        default=False,
        help=(
            "Spend ONE bounded engine turn to propose checks the deterministic "
            "harvest missed (analyzes the file tree). Opt-in — costs one engine "
            "turn; the proposal is still yours to approve."
        ),
    )

    # alc setup [--engine NAME]
    setup_parser = subparsers.add_parser(
        "setup",
        help="Install or update the user-level editor skill for an engine.",
    )
    setup_parser.add_argument(
        "--engine",
        default="claude-code",
        help="Engine whose editor skill to install: claude-code or gemini (default: claude-code).",
    )

    # alc lint
    lint_parser = subparsers.add_parser(
        "lint", help="Check .alc/ for Policy Gate violations (not your source code)."
    )
    lint_parser.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="Output the violations as JSON (machine-readable).",
    )

    # alc run <blueprint> "<task>" [--engine NAME] [--isolate] [--primer NAME]
    #          [--bundle] [--from-bundle REF]
    run_parser = subparsers.add_parser("run", help="Run a Blueprint against a task.")
    # Both optional so a bare `alc run` can LIST the Blueprints instead of
    # printing a usage line. argparse errors before cmd_run gets a say, and the
    # bare invocation is exactly how someone asks what they can run.
    run_parser.add_argument(
        "blueprint", nargs="?", help="Blueprint name (e.g. 'chore'). Omit to list them."
    )
    run_parser.add_argument("task", nargs="?", help="Free-text task description.")
    run_parser.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="Print the full report as JSON instead of the human summary.",
    )
    run_parser.add_argument("--engine", default=None, help="Override the default engine.")
    run_parser.add_argument(
        "--isolate",
        action="store_true",
        default=False,
        help=(
            "Run inside an isolated git worktree on a temporary branch. "
            "Agent edits are committed there instead of mutating the working tree."
        ),
    )
    run_parser.add_argument(
        "--primer",
        default=None,
        metavar="NAME",
        help=(
            "Inject a named Primer (curated context block from .alc/primers/<NAME>.md) "
            "into the directive. Context Budget Trim move."
        ),
    )
    run_parser.add_argument(
        "--bundle",
        action="store_true",
        default=False,
        help="Write an append-only bundle file recording this run's result for later replay.",
    )
    run_parser.add_argument(
        "--from-bundle",
        default=None,
        metavar="REF",
        help=(
            "Replay a prior bundle into the directive. REF is a bundle file path or stem "
            "(looked up in bundles_dir). Context Budget Offload move."
        ),
    )
    run_parser.add_argument(
        "--tier",
        default=None,
        metavar="NAME",
        help="Override the Compute Tier for this invocation (flow: applies to every stage).",
    )

    # alc spike "<task>" [--engine NAME]
    spike_parser = subparsers.add_parser(
        "spike",
        help=(
            'Sugar for `alc run spike "<task>"` — the Prototyper pack\'s spike '
            "Blueprint, no blueprint name to remember."
        ),
    )
    spike_parser.add_argument("task", help="Free-text task description.")
    spike_parser.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="Print the full report as JSON instead of the human summary.",
    )
    spike_parser.add_argument("--engine", default=None, help="Override the default engine.")

    # alc tick
    tick_parser = subparsers.add_parser(
        "tick",
        help=(
            "Drain the task queue (Unattended Mode Trigger). "
            "Processes all pending tasks once and exits — call via cron."
        ),
    )
    tick_parser.add_argument(
        "--concurrency",
        type=int,
        default=1,
        help=(
            "Process up to N queue tasks in parallel; each isolated task gets "
            "its own git worktree."
        ),
    )
    tick_parser.add_argument(
        "--allow-dirty",
        action="store_true",
        default=False,
        help=(
            "Silence the dirty working-tree notice. The run proceeds either way "
            "and never commits your uncommitted work; this flag only quiets the "
            "warning."
        ),
    )
    tick_parser.add_argument(
        "--engine",
        default=None,
        help=(
            "Override the engine for every demand in this drain "
            "(wins over each task's own engine:)."
        ),
    )

    # alc retry [stem] [--all]
    retry_parser = subparsers.add_parser(
        "retry",
        help=(
            "Re-enqueue a failed task (by its done/ filename stem) with the failure "
            "feedback appended, so the next drain fixes the specific reason. With no "
            "stem, lists the outstanding failures; with --all, re-enqueues all of them."
        ),
    )
    retry_parser.add_argument(
        "stem",
        nargs="?",
        default=None,
        help=(
            "Filename stem of the failed task under queue/done/ (e.g. "
            "plan-001-...-<uid>). Omit to list the outstanding failures."
        ),
    )
    retry_parser.add_argument(
        "--all",
        action="store_true",
        default=False,
        help="Re-enqueue every outstanding failure at once (ignored when a stem is given).",
    )
    retry_parser.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="List the outstanding failures as JSON (machine-readable).",
    )
    retry_parser.add_argument(
        "--dismiss",
        action="store_true",
        default=False,
        help=(
            "Close the failure's lineage WITHOUT re-running it (requires the stem). "
            "The archives stay; delete done/<root>.dismissed to reopen."
        ),
    )

    # alc enqueue <name> "<task>" [--kind flow|specialist] [--engine NAME]
    #             [--isolate/--no-isolate] [--id ID] [--depends-on ID] [--touches PATH]
    #             [--from-file PATH] [--json]
    enqueue_parser = subparsers.add_parser(
        "enqueue",
        help="Write one or more queue task(s) directly, with no planner turn.",
    )
    enqueue_parser.add_argument("name", help="Flow or specialist name to dispatch.")
    enqueue_parser.add_argument(
        "task",
        nargs="?",
        default=None,
        help="Free-text task description. Omit when using --from-file.",
    )
    enqueue_parser.add_argument(
        "--kind",
        choices=["flow", "specialist", "run"],
        default="flow",
        help="Unit kind to dispatch (default: flow).",
    )
    enqueue_parser.add_argument("--engine", default=None, help="Override the default engine.")
    enqueue_parser.add_argument(
        "--isolate",
        dest="isolate",
        action="store_true",
        default=True,
        help="Run the enqueued task(s) in an isolated git worktree (default).",
    )
    enqueue_parser.add_argument(
        "--no-isolate",
        dest="isolate",
        action="store_false",
        help="Do not isolate the enqueued task(s) in a worktree.",
    )
    enqueue_parser.add_argument(
        "--id",
        dest="id",
        default=None,
        metavar="ID",
        help="Short slug identifying this unit so another --depends-on can reference it.",
    )
    enqueue_parser.add_argument(
        "--depends-on",
        dest="depends_on",
        action="append",
        default=[],
        metavar="ID",
        help="Id of a unit this one depends on (repeatable).",
    )
    enqueue_parser.add_argument(
        "--touches",
        dest="touches",
        action="append",
        default=[],
        metavar="PATH",
        help=(
            "File path/glob this unit will edit; overlapping touches are "
            "serialized automatically (repeatable)."
        ),
    )
    enqueue_parser.add_argument(
        "--priority",
        dest="priority",
        type=int,
        default=0,
        metavar="N",
        help=(
            "Tie-breaker among tasks ready in the same dependency wave, higher "
            "runs first (default 0)."
        ),
    )
    enqueue_parser.add_argument(
        "--from-file",
        dest="from_file",
        default=None,
        metavar="PATH",
        help=(
            "Batch-enqueue tasks from a file: a .jsonl file (one JSON object per "
            "line, 'task' required, other keys optional) or plain text (one task "
            "per line; blank lines and '#' comments are skipped)."
        ),
    )
    enqueue_parser.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="Print the written filenames as JSON (machine-readable).",
    )

    # alc land [branch...] [--all] [--json] [--push|--pr]
    land_parser = subparsers.add_parser(
        "land",
        help=(
            "Integrate alc/* demand branches into the current branch (linear "
            "cherry-pick). With no branch names, lists the unmerged ones."
        ),
    )
    land_parser.add_argument(
        "branch",
        nargs="*",
        help="Explicit alc/* branch name(s) to integrate. Omit to list the unmerged ones.",
    )
    land_parser.add_argument(
        "--all",
        action="store_true",
        default=False,
        help="Integrate every unmerged alc/* branch.",
    )
    land_parser.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="List the unmerged branches as JSON (machine-readable); only with no branch/--all.",
    )
    land_parser.add_argument(
        "--push",
        action="store_true",
        default=False,
        help=(
            "After a successful local land, push the current branch to the "
            "delivery remote (manifest `delivery.remote`, default origin)."
        ),
    )
    land_parser.add_argument(
        "--pr",
        action="store_true",
        default=False,
        help=(
            "Push (see --push) and open a pull request via `gh` against the "
            "delivery base branch (manifest `delivery.base`, default main)."
        ),
    )

    # alc discard [branch...] [--all-unmerged] [--worktrees] [--bundles --older-than N] [--yes] [--json]
    discard_parser = subparsers.add_parser(
        "discard",
        help=(
            "Force-delete alc/* branches, prune stale worktrees, and/or remove "
            "old bundle files. With no arguments, lists the unmerged branches."
        ),
    )
    discard_parser.add_argument(
        "branch",
        nargs="*",
        help="Explicit alc/* branch name(s) to delete.",
    )
    discard_parser.add_argument(
        "--all-unmerged",
        action="store_true",
        default=False,
        help="Delete every unmerged alc/* branch (ignored when branch names are given).",
    )
    discard_parser.add_argument(
        "--worktrees",
        action="store_true",
        default=False,
        help="Prune stale worktree admin entries (git worktree prune).",
    )
    discard_parser.add_argument(
        "--bundles",
        action="store_true",
        default=False,
        help="Delete bundle files older than --older-than N days.",
    )
    discard_parser.add_argument(
        "--older-than",
        type=int,
        default=None,
        metavar="N",
        help="Age threshold in days for --bundles.",
    )
    discard_parser.add_argument(
        "--yes",
        action="store_true",
        default=False,
        help="Confirm the deletion non-interactively (required when stdin is not a TTY).",
    )
    discard_parser.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="List the unmerged branches as JSON (machine-readable); only with no other arguments.",
    )

    # alc explore <blueprint> "<task>" --variants N [--engine A --engine B] [--tier X --tier Y]
    explore_parser = subparsers.add_parser(
        "explore",
        help=(
            "Run N variants of the same Blueprint+task, each in its own isolated "
            "worktree — NEVER auto-merged. Compare them, then `alc adopt` one."
        ),
    )
    explore_parser.add_argument("blueprint", help="Blueprint name (e.g. 'chore').")
    explore_parser.add_argument("task", help="Free-text task description.")
    explore_parser.add_argument(
        "--variants",
        type=int,
        default=1,
        metavar="N",
        help="Number of copies of the unit to run (default: 1).",
    )
    explore_parser.add_argument(
        "--engine",
        action="append",
        default=None,
        metavar="NAME",
        help="Engine to explore (repeatable — crossed with --tier as a cartesian product).",
    )
    explore_parser.add_argument(
        "--tier",
        action="append",
        default=None,
        metavar="NAME",
        help="Compute tier to explore (repeatable — crossed with --engine as a cartesian product).",
    )
    explore_parser.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="Print the variant table as JSON (machine-readable).",
    )

    # alc compare [<branch|stem>...]
    compare_parser = subparsers.add_parser(
        "compare",
        help="Put explored variants side by side (branch, checks, scorecard, usage, diffstat).",
    )
    # Not required: a bare `alc compare` (refs == []) lists EVERY archived variant
    # via the one shared lister — the same set the UI Compare view shows — so the
    # read opens on observation, never a usage error.
    compare_parser.add_argument(
        "refs",
        nargs="*",
        help=(
            "Variant branch name(s) or bare stem(s) from `alc explore`; "
            "omit to list all archived variants."
        ),
    )
    compare_parser.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="Print the variant table as JSON (machine-readable).",
    )
    compare_parser.add_argument(
        "--diff",
        action="store_true",
        default=False,
        help="Also print each variant's unified diff vs the current branch.",
    )

    # alc adopt <branch> [--yes] [--json]
    adopt_parser = subparsers.add_parser(
        "adopt",
        help=(
            "Integrate the chosen variant branch and discard its unmerged "
            "sibling variants — closes the explore -> compare -> adopt loop."
        ),
    )
    adopt_parser.add_argument("branch", help="The winning alc/variant-* branch to integrate.")
    adopt_parser.add_argument(
        "--yes",
        action="store_true",
        default=False,
        help="Confirm non-interactively (required when stdin is not a TTY).",
    )
    adopt_parser.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="Print the outcome as JSON (machine-readable).",
    )

    # alc conduct "<goal>" [--engine NAME] [--enqueue]
    conduct_parser = subparsers.add_parser(
        "conduct",
        help=(
            "Conduct a goal: the Conductor agent plans the required Flows and "
            "either runs them now (default) or enqueues them for alc tick."
        ),
    )
    conduct_parser.add_argument("goal", help="High-level goal for the Conductor.")
    conduct_parser.add_argument("--engine", default=None, help="Override the default engine.")
    conduct_parser.add_argument(
        "--enqueue",
        action="store_true",
        default=False,
        help="Write queue task files instead of running Flows immediately.",
    )
    conduct_parser.add_argument(
        "--parallel",
        action="store_true",
        default=False,
        help=(
            "Dispatch independent plan units concurrently, each in an isolated "
            "git worktree (requires a git repo)."
        ),
    )
    conduct_parser.add_argument(
        "--concurrency",
        type=int,
        default=None,
        help="Parallel fan-out width for --parallel (default: manifest.fanout_concurrency).",
    )
    conduct_parser.add_argument(
        "--tier",
        default=None,
        help="Compute tier for the planning turn (default: manifest.plan_tier).",
    )
    conduct_parser.add_argument(
        "--strict-stage",
        action="store_true",
        default=False,
        help=(
            "Refuse the plan instead of warning when a unit's archetype falls "
            "outside manifest.stage's target mix (no-op with no stage declared)."
        ),
    )

    # alc cycle <name> [--engine NAME] [--concurrency N] [--status] [--reset]
    cycle_parser = subparsers.add_parser(
        "cycle",
        help="Deprecated alias for `alc loop <name> --once`.",
    )
    cycle_parser.add_argument("name", help="Loop name (e.g. 'deliver').")
    cycle_parser.add_argument("--engine", default=None, help="Override the default engine.")
    cycle_parser.add_argument(
        "--concurrency",
        type=int,
        default=0,
        help="Override the loop's drain concurrency for this cycle (0 = use the definition).",
    )
    cycle_parser.add_argument(
        "--status",
        action="store_true",
        default=False,
        help="Print the loop state without running a cycle.",
    )
    cycle_parser.add_argument(
        "--reset",
        action="store_true",
        default=False,
        help="Reset the loop state, then run one cycle.",
    )
    cycle_parser.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="With --status, print the loop state as JSON (machine-readable).",
    )
    cycle_parser.add_argument(
        "--allow-dirty",
        action="store_true",
        default=False,
        help=(
            "Silence the dirty working-tree notice. The run proceeds either way "
            "and never commits your uncommitted work; this flag only quiets the "
            "warning."
        ),
    )

    # alc loop <name> [--once] [--engine NAME] [--interval S]
    #
    # One verb for one unit. `cycle` runs one iteration of a `loop` while `loop`
    # repeats `cycle` — two verbs splitting one noun in a direction nobody
    # guesses, and the collision lands on the unattended tier. `--once` says the
    # same thing in a way a reader can predict from the command they already know.
    loop_parser = subparsers.add_parser(
        "loop",
        help=(
            "Run an Autonomous Loop until it stops, sleeping between cycles. "
            "Add --once for a single cycle (the cron target)."
        ),
    )
    loop_parser.add_argument("name", help="Loop name (e.g. 'deliver').")
    loop_parser.add_argument(
        "--once",
        action="store_true",
        default=False,
        help=(
            "Run ONE cycle (replenish -> drain -> check stop) and exit. State "
            "persists between fires — this is what cron calls."
        ),
    )
    loop_parser.add_argument("--engine", default=None, help="Override the default engine.")
    loop_parser.add_argument(
        "--concurrency",
        type=int,
        default=0,
        help="With --once, override the loop's drain concurrency (0 = use the definition).",
    )
    loop_parser.add_argument(
        "--status",
        action="store_true",
        default=False,
        help="Print the loop state without running anything.",
    )
    loop_parser.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="With --status, print the loop state as JSON (machine-readable).",
    )
    loop_parser.add_argument(
        "--interval",
        type=int,
        default=300,
        help="Seconds to sleep between cycles (0 = no sleep). Default 300.",
    )
    loop_parser.add_argument(
        "--reset",
        action="store_true",
        default=False,
        help="Reset the loop's stopped/exhausted state, then run — restart in one step.",
    )
    loop_parser.add_argument(
        "--allow-dirty",
        action="store_true",
        default=False,
        help=(
            "Silence the dirty working-tree notice. The run proceeds either way "
            "and never commits your uncommitted work; this flag only quiets the "
            "warning."
        ),
    )

    # alc specialist <name> "<task>" [--engine NAME]
    specialist_parser = subparsers.add_parser(
        "specialist",
        help=(
            "Run a Specialist (Recall -> Act -> Learn): read the Knowledge File, "
            "act on the task, then update the Knowledge File."
        ),
    )
    specialist_parser.add_argument("name", help="Specialist name (e.g. 'db').")
    specialist_parser.add_argument("task", help="Free-text task description.")
    specialist_parser.add_argument(
        "--engine", default=None, help="Override the default engine."
    )

    # alc primer <action> <name> [--force]
    primer_parser = subparsers.add_parser(
        "primer",
        help="Manage Primer files (curated context blocks) in .alc/.",
    )
    primer_parser.add_argument(
        "action",
        choices=["new"],
        help="Action to perform. Currently only 'new' is supported.",
    )
    primer_parser.add_argument("name", help="Primer name (file stem, without .md extension).")
    primer_parser.add_argument(
        "--force",
        action="store_true",
        default=False,
        help="Overwrite an existing Primer file.",
    )

    # alc new <kind> <name> [--force] [--from NAME]
    new_parser = subparsers.add_parser(
        "new",
        help="Author a new unit (blueprint/flow/specialist/loop/primer) from a core scaffold.",
    )
    new_parser.add_argument(
        "kind",
        choices=["blueprint", "flow", "specialist", "loop", "primer"],
        help="Kind of unit to create.",
    )
    new_parser.add_argument("name", help="Unit name (filename stem).")
    new_parser.add_argument(
        "--force",
        action="store_true",
        default=False,
        help="Overwrite an existing unit of the same kind and name.",
    )
    new_parser.add_argument(
        "--from",
        dest="from_name",
        default=None,
        metavar="NAME",
        help="Clone an existing unit of the same kind, replacing its name: field.",
    )

    # alc team hire|list|retire|status
    team_parser = subparsers.add_parser(
        "team",
        help="Hire, list, retire, or check the status of Archetype Packs (team roster).",
    )
    # Not required: a bare `alc team` (team_action None) is normalized to `status`
    # in cmd_team so the command family opens on observation, never a usage error.
    team_subparsers = team_parser.add_subparsers(dest="team_action")

    team_hire_parser = team_subparsers.add_parser(
        "hire",
        help=(
            "Write an Archetype Pack's MISSING files (keeping existing ones), "
            "then run `alc lint`."
        ),
    )
    team_hire_parser.add_argument("archetype", help="Pack name, e.g. 'builder'.")
    team_hire_parser.add_argument(
        "--force",
        action="store_true",
        default=False,
        help="Overwrite ALL of the pack's files, replacing any local edits.",
    )

    team_list_parser = team_subparsers.add_parser(
        "list", help="List hired members and the state of any loops they brought."
    )
    team_list_parser.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="Output the roster as JSON (machine-readable).",
    )

    team_status_parser = team_subparsers.add_parser(
        "status",
        help=(
            "Like `alc team list`, plus Mix Health: archived reports' archetype "
            "spend against the declared stage's target mix."
        ),
    )
    team_status_parser.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="Output the roster as JSON (machine-readable).",
    )

    team_retire_parser = team_subparsers.add_parser(
        "retire",
        help="Archive a hired member's loop definition(s) into loops/retired/.",
    )
    team_retire_parser.add_argument("member", help="Archetype name to retire, e.g. 'builder'.")

    team_remove_parser = team_subparsers.add_parser(
        "remove",
        help=(
            "Delete a member's UNMODIFIED pack files (customised ones are kept "
            "and listed). Reversible via `alc team hire`."
        ),
    )
    team_remove_parser.add_argument("member", help="Archetype name to remove, e.g. 'sweeper'.")

    # alc prompts <action> [name] [--force]
    prompts_parser = subparsers.add_parser(
        "prompts",
        help="Manage keyed prompt overrides (.alc/prompts/) — list or eject.",
    )
    prompts_parser.add_argument(
        "action",
        choices=["list", "eject"],
        help="'list' the reserved/free prompts, or 'eject' a reserved default to a file.",
    )
    prompts_parser.add_argument(
        "name",
        nargs="?",
        default=None,
        help="Reserved prompt name to eject (required for 'eject').",
    )
    prompts_parser.add_argument(
        "--force",
        action="store_true",
        default=False,
        help="Overwrite an existing prompt override file when ejecting.",
    )
    prompts_parser.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="Output 'prompts list' as JSON (machine-readable).",
    )

    # alc flow <flow_name> "<task>" [--engine NAME] [--isolate] [--primer NAME]
    #           [--bundle] [--from-bundle REF]
    flow_parser = subparsers.add_parser(
        "flow", help="Run a Flow (multi-stage pipeline) against a task."
    )
    flow_parser.add_argument("flow_name", help="Flow name (e.g. 'ship').")
    flow_parser.add_argument("task", help="Free-text task description.")
    flow_parser.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="Print the full report as JSON instead of the human summary.",
    )
    flow_parser.add_argument("--engine", default=None, help="Override the default engine.")
    flow_parser.add_argument(
        "--isolate",
        action="store_true",
        default=False,
        help=(
            "Run all Flow stages inside one shared isolated git worktree. "
            "The plan→build file hand-off is preserved within the worktree."
        ),
    )
    flow_parser.add_argument(
        "--primer",
        default=None,
        metavar="NAME",
        help=(
            "Inject a named Primer (curated context block from .alc/primers/<NAME>.md) "
            "into every stage's directive. Context Budget Trim move."
        ),
    )
    flow_parser.add_argument(
        "--bundle",
        action="store_true",
        default=False,
        help="Write an append-only bundle file recording this flow's result for later replay.",
    )
    flow_parser.add_argument(
        "--from-bundle",
        default=None,
        metavar="REF",
        help=(
            "Replay a prior bundle into every stage's directive. REF is a bundle file path "
            "or stem (looked up in bundles_dir). Context Budget Offload move."
        ),
    )
    flow_parser.add_argument(
        "--tier",
        default=None,
        metavar="NAME",
        help="Override the Compute Tier for this invocation (flow: applies to every stage).",
    )

    # alc status [--json]
    status_parser = subparsers.add_parser(
        "status",
        help=(
            "Aggregate health signals (pending tasks, outstanding failures, loop "
            "states, unmerged branches) for external monitoring. Always exits 0."
        ),
    )
    status_parser.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="Output the status payload as JSON (machine-readable).",
    )

    # alc runs list|show|tail
    runs_parser = subparsers.add_parser(
        "runs", help="Inspect run logs (.alc/runs/*.jsonl): list, show, or tail one."
    )
    runs_subparsers = runs_parser.add_subparsers(dest="runs_action", required=True)

    runs_list_parser = runs_subparsers.add_parser(
        "list", help="List run logs, newest first."
    )
    runs_list_parser.add_argument(
        "--limit", type=int, default=50, help="Max runs to list (default: 50)."
    )
    runs_list_parser.add_argument(
        "--offset", type=int, default=0, help="Runs to skip from the newest (default: 0)."
    )
    runs_list_parser.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="Output the run list as JSON (machine-readable).",
    )

    runs_show_parser = runs_subparsers.add_parser(
        "show", help="Show every parsed event for one run."
    )
    runs_show_parser.add_argument(
        "stem", help="Run-log filename stem (e.g. from `alc runs list`)."
    )
    runs_show_parser.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="Output the run's events as JSON (machine-readable).",
    )

    runs_tail_parser = runs_subparsers.add_parser(
        "tail", help="Print the last N events of one run."
    )
    runs_tail_parser.add_argument(
        "stem", help="Run-log filename stem (e.g. from `alc runs list`)."
    )
    runs_tail_parser.add_argument(
        "-n",
        type=int,
        default=20,
        dest="lines",
        metavar="N",
        help="Number of trailing events to print (default: 20).",
    )

    # alc audit --since 7d|24h|30m [--json]
    audit_parser = subparsers.add_parser(
        "audit",
        help=(
            "Aggregate the archived queue reports (done/*.report.json) over a "
            "trailing time window: task counts, Scorecard totals/averages, "
            "changed files, and accumulated engine Usage."
        ),
    )
    audit_parser.add_argument(
        "--since",
        default="7d",
        metavar="WINDOW",
        help="Trailing window to aggregate, e.g. '7d', '24h', '30m' (default: 7d).",
    )
    audit_parser.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="Output the aggregate as JSON (machine-readable).",
    )

    # alc signal ingest --kind K --source S --title T [--body B] [--from-file PATH] [--json]
    # alc signal list [--json]
    signal_parser = subparsers.add_parser(
        "signal",
        help=(
            "Ingest a typed real-usage signal (error/feedback/issue/review) or "
            "list the ones pending consumption by a `signals` replenish loop."
        ),
    )
    signal_subparsers = signal_parser.add_subparsers(
        dest="signal_action", required=True
    )

    signal_ingest_parser = signal_subparsers.add_parser(
        "ingest",
        help="Write one typed signal into `manifest.signals_dir`.",
    )
    signal_ingest_parser.add_argument(
        "--kind",
        choices=["error", "feedback", "issue", "review"],
        default=None,
        help="Signal kind. Required unless --from-file is given.",
    )
    signal_ingest_parser.add_argument(
        "--source",
        default=None,
        metavar="NAME",
        help="Free-text origin (e.g. 'sentry', 'github'). Required unless --from-file is given.",
    )
    signal_ingest_parser.add_argument(
        "--title",
        default=None,
        help="Short signal title. Required unless --from-file is given.",
    )
    signal_ingest_parser.add_argument(
        "--body",
        default=None,
        help="Optional signal body (default: empty).",
    )
    signal_ingest_parser.add_argument(
        "--from-file",
        dest="from_file",
        default=None,
        metavar="PATH",
        help=(
            "Read an already-formed JSON object as the signal (the path the "
            "webhook and integration scripts use) instead of --kind/--source/"
            "--title/--body."
        ),
    )
    signal_ingest_parser.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="Print the written path as JSON (machine-readable).",
    )

    signal_list_parser = signal_subparsers.add_parser(
        "list", help="List the pending (not yet consumed) signals."
    )
    signal_list_parser.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="Output the pending signals as JSON (machine-readable).",
    )

    # alc checks audit [--json]
    checks_parser = subparsers.add_parser(
        "checks",
        help=(
            "Re-detect stacks and PROPOSE check_set upgrades against the Manifest "
            "(bare `alc checks` = the audit read view)."
        ),
    )
    # Not required: a bare `alc checks` (checks_action None) routes to the audit
    # read view (see cmd_checks) so the command family opens on observation.
    checks_subparsers = checks_parser.add_subparsers(dest="checks_action")

    checks_audit_parser = checks_subparsers.add_parser(
        "audit",
        help=(
            "Compare the Manifest's check_sets and each Blueprint's resolved checks "
            "against a fresh stack detection; never writes. Also flags checks "
            "commented out for a missing binary."
        ),
    )
    checks_audit_parser.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="Output the proposal as JSON (machine-readable).",
    )

    checks_history_parser = checks_subparsers.add_parser(
        "history",
        help=(
            "Aggregate the run logs' check_finished events into per-check "
            "pass-rate, mean duration, and a flake score; never writes."
        ),
    )
    checks_history_parser.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="Output the history as JSON (machine-readable).",
    )

    # alc metrics [--check NAME] [--json]
    metrics_parser = subparsers.add_parser(
        "metrics",
        help=(
            "Show the metric-check time series recorded in the project's "
            "ledger: values, delta, and trend per check."
        ),
    )
    metrics_parser.add_argument(
        "--check",
        default=None,
        metavar="NAME",
        help="Only show this check's series (default: every check in the ledger).",
    )
    metrics_parser.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="Output the series as JSON (machine-readable).",
    )

    # alc artifacts [<stem>] [--json]
    artifacts_parser = subparsers.add_parser(
        "artifacts",
        help=(
            "List a run's captured e2e evidence (screenshots, curled "
            "responses, the health-poll log) — proof a `needs_service` run's "
            "`capture:` command actually verified the app live."
        ),
    )
    artifacts_parser.add_argument(
        "stem",
        nargs="?",
        default=None,
        help=(
            "Run-log filename stem (e.g. from `alc runs list`). Default: the "
            "most recent run that captured any artifact."
        ),
    )
    artifacts_parser.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="Output the artifact list as JSON (machine-readable).",
    )

    # alc schedule install|list|remove <tick|cycle NAME> --every 15m
    schedule_parser = subparsers.add_parser(
        "schedule",
        help=(
            "Generate and manage the crontab entry that fires `alc tick` or "
            "`alc cycle NAME` on a cadence."
        ),
    )
    schedule_subparsers = schedule_parser.add_subparsers(
        dest="schedule_action", required=True
    )

    schedule_install_parser = schedule_subparsers.add_parser(
        "install",
        help=(
            "Write (or update) the crontab entry, idempotently — running it "
            "twice never produces two entries."
        ),
    )
    schedule_install_parser.add_argument(
        "target", choices=["tick", "cycle"], help="What to schedule."
    )
    schedule_install_parser.add_argument(
        "name", nargs="?", default=None, help="Loop name — required for 'cycle', omit for 'tick'."
    )
    schedule_install_parser.add_argument(
        "--every",
        required=True,
        metavar="CADENCE",
        help="How often to fire, e.g. '15m' or '1h'.",
    )

    schedule_list_parser = schedule_subparsers.add_parser(
        "list", help="List the crontab entries ALC itself installed."
    )
    schedule_list_parser.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="Output the entries as JSON (machine-readable).",
    )

    schedule_remove_parser = schedule_subparsers.add_parser(
        "remove",
        help="Remove ALC's crontab entry for a target — never touches an operator-written line.",
    )
    schedule_remove_parser.add_argument(
        "target", choices=["tick", "cycle"], help="What to unschedule."
    )
    schedule_remove_parser.add_argument(
        "name", nargs="?", default=None, help="Loop name — required for 'cycle', omit for 'tick'."
    )

    # alc ui [--host H] [--port P] [--ui-dist PATH]
    ui_parser = subparsers.add_parser(
        "ui",
        help=(
            "Serve the alc web IDE (API + WebSocket, plus the built frontend when "
            "--ui-dist points at it). Requires the optional 'ui' extra."
        ),
    )
    ui_bind = ui_parser.add_mutually_exclusive_group()
    ui_bind.add_argument(
        "--host", default="127.0.0.1", help="Host to bind (default: 127.0.0.1)."
    )
    ui_bind.add_argument(
        "--lan",
        action="store_true",
        default=False,
        help=(
            "Bind every interface so another device on your network can reach "
            "the UI, and print the address to type there. Pair it with --token "
            "unless the network is one you trust."
        ),
    )
    ui_parser.add_argument(
        "--port", type=int, default=8642, help="Port to bind (default: 8642)."
    )
    ui_parser.add_argument(
        "--ui-dist",
        default=None,
        metavar="PATH",
        help=(
            "Explicit directory of the built frontend to serve as an SPA. Must "
            "contain index.html (error + exit 1 otherwise). When unset, falls "
            "back to ALC_UI_DIST, then the bundled build, then API-only."
        ),
    )
    ui_parser.add_argument(
        "--no-ui",
        action="store_true",
        default=False,
        help="Serve only the API and WebSocket (do not serve any frontend).",
    )
    ui_parser.add_argument(
        "--token",
        default=None,
        metavar="T",
        help=(
            "Require this bearer token on every /api request and on the "
            "WebSocket handshake (env: ALC_UI_TOKEN). Omit for the local, "
            "unauthenticated default. Open the UI once at "
            "http://HOST:PORT/?t=<token> to hand it to the browser."
        ),
    )

    # alc serve --webhook [--host H] [--port P] [--token T]
    serve_parser = subparsers.add_parser(
        "serve",
        help=(
            "Run a minimal HTTP door onto signal intake and the enqueue path "
            "(the webhook Trigger). Never executes anything — only writes."
        ),
    )
    serve_parser.add_argument(
        "--webhook",
        action="store_true",
        required=True,
        help=(
            "Serve the webhook (the only mode today): POST /signal, "
            "POST /enqueue, GET /health."
        ),
    )
    serve_parser.add_argument(
        "--host", default="127.0.0.1", help="Host to bind (default: 127.0.0.1)."
    )
    serve_parser.add_argument(
        "--port", type=int, default=8787, help="Port to bind (default: 8787)."
    )
    serve_parser.add_argument(
        "--token",
        default=None,
        help=(
            "Bearer token required in the Authorization header. Omit at your "
            "own risk: the port then answers unauthenticated requests, with a "
            "warning printed to stderr."
        ),
    )

    return parser


def main() -> None:
    """Console-script entrypoint.

    Ctrl-C is a normal way to stop a run, not a crash. Left unhandled it printed
    a twenty-line Python traceback — which, on the isolated path, buried the one
    line that says the interrupted work was committed to a branch.
    """
    try:
        _dispatch()
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        sys.exit(130)


def _dispatch() -> None:
    """Parse argv and run the requested command."""
    # A broken stderr pipe (cancelled exec / disconnected client) must never crash
    # the work — only the progress output is lost. Guard every stderr write once.
    sys.stderr = _ResilientStderr(sys.stderr)  # type: ignore[assignment]
    parser = _build_parser()
    args = parser.parse_args()

    if args.command == "init":
        sys.exit(cmd_init(args))
    elif args.command == "onboard":
        sys.exit(cmd_onboard(args))
    elif args.command == "setup":
        sys.exit(cmd_setup(args))
    elif args.command == "lint":
        sys.exit(cmd_lint(args))
    elif args.command == "run":
        sys.exit(cmd_run(args))
    elif args.command == "spike":
        sys.exit(cmd_spike(args))
    elif args.command == "flow":
        sys.exit(cmd_flow(args))
    elif args.command == "tick":
        sys.exit(cmd_tick(args))
    elif args.command == "retry":
        sys.exit(cmd_retry(args))
    elif args.command == "enqueue":
        sys.exit(cmd_enqueue(args))
    elif args.command == "land":
        sys.exit(cmd_land(args))
    elif args.command == "discard":
        sys.exit(cmd_discard(args))
    elif args.command == "explore":
        sys.exit(cmd_explore(args))
    elif args.command == "compare":
        sys.exit(cmd_compare(args))
    elif args.command == "adopt":
        sys.exit(cmd_adopt(args))
    elif args.command == "conduct":
        sys.exit(cmd_conduct(args))
    elif args.command == "cycle":
        # Deprecated, not removed: `alc cycle` is in people's crontabs, and a
        # rename that breaks a scheduled job at 3am to improve a noun is not a
        # trade worth making. The notice goes to stderr so a cron mail carries it
        # while the exit code and stdout stay exactly as before.
        print(
            "[WARN] `alc cycle` is deprecated — use `alc loop "
            f"{getattr(args, 'name', '<name>')} --once`. It still works.",
            file=sys.stderr,
        )
        sys.exit(cmd_cycle(args))
    elif args.command == "loop":
        sys.exit(cmd_loop(args))
    elif args.command == "specialist":
        sys.exit(cmd_specialist(args))
    elif args.command == "primer":
        sys.exit(cmd_primer(args))
    elif args.command == "new":
        sys.exit(cmd_new(args))
    elif args.command == "team":
        sys.exit(cmd_team(args))
    elif args.command == "prompts":
        if args.action == "eject" and not args.name:
            parser.error("prompts eject requires a prompt NAME")
        sys.exit(cmd_prompts(args))
    elif args.command == "status":
        sys.exit(cmd_status(args))
    elif args.command == "runs":
        sys.exit(cmd_runs(args))
    elif args.command == "audit":
        sys.exit(cmd_audit(args))
    elif args.command == "signal":
        sys.exit(cmd_signal(args))
    elif args.command == "checks":
        sys.exit(cmd_checks(args))
    elif args.command == "metrics":
        sys.exit(cmd_metrics(args))
    elif args.command == "artifacts":
        sys.exit(cmd_artifacts(args))
    elif args.command == "schedule":
        sys.exit(cmd_schedule(args))
    elif args.command == "ui":
        sys.exit(cmd_ui(args))
    elif args.command == "serve":
        sys.exit(cmd_serve(args))
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
