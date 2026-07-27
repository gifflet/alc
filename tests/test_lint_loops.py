# test_lint_loops.py — Hermetic tests for the `deps-loop-without-env-refresh`
# Policy Gate rule (policy.lint_loops).
#
# The gap this rule guards: a `link:` provision shares the operator's already-
# installed packages into every worktree. A loop that bumps dependency manifests
# (the Maintainer pack's deps-refresh Loop) whose worktree_provision declares NO
# `refresh` would run its checks against those STALE, already-installed packages —
# a breaking major bump passes green because type-check/build/test never saw the
# new versions (a vacuous check). `alc init` scaffolds the refresh for NEW Node
# projects; this WARN catches an EXISTING project that adopted such a loop without
# declaring one. It is the lint-time complement to the run-time env-refresh fix
# (commit f394f0b). Pure over already-loaded models — no filesystem, no engine.
from __future__ import annotations

from pathlib import Path

import yaml

from alc.intake import load_all_loops
from alc.models import (
    LoopDefinition,
    LoopStop,
    Manifest,
    ProvisionSpec,
    Replenish,
)
from alc.packs import pack_files
from alc.policy import (
    _DEPS_LOOP_CANONICAL,
    _DEPS_SPECIALIST_CANONICAL,
    has_errors,
    lint_loops,
)
from alc.scaffold import scaffold

RULE = "deps-loop-without-env-refresh"

# A bare provision (no refresh declared) — the vacuous-check state this rule fires on.
_BARE = ProvisionSpec(link="node_modules")
# A provision that DOES declare a refresh — the fix the rule points operators at.
_REFRESH = ProvisionSpec(
    link="node_modules",
    refresh=["npm", "install"],
    when_changed=["package.json", "package-lock.json"],
)
# A refresh provision on a DIFFERENT path — proves the guard is manifest-wide, not
# per-entry: any single entry declaring a refresh silences the whole rule.
_REFRESH_OTHER = ProvisionSpec(
    copy="data",
    refresh=["sh", "-c", "echo refreshed"],
    when_changed=["data/schema.sql"],
)


def _manifest(**overrides) -> Manifest:
    defaults = dict(
        version=1,
        default_engine="mock",
        compute_tiers={"standard": {"mock": "mock-small"}},
        engines={"mock": {"type": "mock"}},
    )
    defaults.update(overrides)
    return Manifest(**defaults)


def _loop(
    name: str = _DEPS_LOOP_CANONICAL,
    *,
    kind: str | None = "specialist",
    ref: str | None = _DEPS_SPECIALIST_CANONICAL,
) -> LoopDefinition:
    """A LoopDefinition; ``kind=None`` yields a Mode B (drain-only) loop."""
    replenish = None if kind is None else Replenish(kind=kind, ref=ref, task="t")
    return LoopDefinition(name=name, replenish=replenish, stop=LoopStop(max_cycles=10))


# ---------------------------------------------------------------------------
# Fires: a deps-bumping loop with no refresh provision is a vacuous check
# ---------------------------------------------------------------------------


class TestLintLoopsFires:
    def test_deps_loop_with_bare_provision_warns_once(self) -> None:
        manifest = _manifest(worktree_provision=[_BARE])
        violations = lint_loops(manifest, [_loop()])
        matching = [v for v in violations if v.rule == RULE]
        assert len(matching) == 1
        assert matching[0].severity == "warn"
        # A warn NEVER blocks a run — this is advisory, like the stage-mix rules.
        assert not has_errors(violations)

    def test_empty_worktree_provision_still_fires(self) -> None:
        # An ABSENT config is the vacuous state, not an exemption: a deps loop
        # with no provisioning at all installs nothing before its checks.
        manifest = _manifest(worktree_provision=[])
        matching = [v for v in lint_loops(manifest, [_loop()]) if v.rule == RULE]
        assert len(matching) == 1

    def test_message_names_the_loop_and_the_fix(self) -> None:
        manifest = _manifest(worktree_provision=[_BARE])
        message = [v for v in lint_loops(manifest, [_loop()]) if v.rule == RULE][0].message
        assert f"Loop '{_DEPS_LOOP_CANONICAL}'" in message
        assert "refresh" in message
        assert "when_changed" in message
        assert "alc init" in message
        assert "manifest.worktree_provision" in message

    def test_renamed_loop_still_caught_via_the_specialist_ref(self) -> None:
        # Rename the LOOP but keep the deps specialist ref -> the specialist arm
        # of the predicate still catches it, and the message names the new loop.
        manifest = _manifest(worktree_provision=[_BARE])
        loop = _loop(name="dependency-updates", kind="specialist", ref="deps")
        matching = [v for v in lint_loops(manifest, [loop]) if v.rule == RULE]
        assert len(matching) == 1
        assert "Loop 'dependency-updates'" in matching[0].message

    def test_canonical_name_caught_even_with_a_different_ref(self) -> None:
        # Keep the canonical loop name but point replenish elsewhere -> the name
        # arm of the predicate catches it independently of the ref.
        manifest = _manifest(worktree_provision=[_BARE])
        loop = _loop(name=_DEPS_LOOP_CANONICAL, kind="specialist", ref="packages")
        matching = [v for v in lint_loops(manifest, [loop]) if v.rule == RULE]
        assert len(matching) == 1

    def test_mode_b_loop_with_canonical_name_fires(self) -> None:
        # The name arm needs no replenish: a drain-only (Mode B) loop that still
        # carries the canonical name is caught (the None-deref guard holds).
        manifest = _manifest(worktree_provision=[_BARE])
        loop = _loop(name=_DEPS_LOOP_CANONICAL, kind=None)
        matching = [v for v in lint_loops(manifest, [loop]) if v.rule == RULE]
        assert len(matching) == 1

    def test_plan_kind_replenish_to_deps_fires(self) -> None:
        # `kind: plan` groups with `kind: specialist` in validate_loop (both
        # name a Specialist), so a plan replenish to the deps specialist fires.
        manifest = _manifest(worktree_provision=[_BARE])
        loop = _loop(name="plan-bumps", kind="plan", ref="deps")
        matching = [v for v in lint_loops(manifest, [loop]) if v.rule == RULE]
        assert len(matching) == 1

    def test_two_matching_loops_yield_two_violations_each_named(self) -> None:
        manifest = _manifest(worktree_provision=[_BARE])
        loops = [
            _loop(name=_DEPS_LOOP_CANONICAL),
            _loop(name="dep-updates", kind="specialist", ref="deps"),
        ]
        matching = [v for v in lint_loops(manifest, loops) if v.rule == RULE]
        assert len(matching) == 2
        named = {m.message for m in matching}
        assert any(f"Loop '{_DEPS_LOOP_CANONICAL}'" in m for m in named)
        assert any("Loop 'dep-updates'" in m for m in named)


# ---------------------------------------------------------------------------
# Silent: false-positive guards
# ---------------------------------------------------------------------------


class TestLintLoopsSilent:
    def test_refresh_provision_silences_the_rule(self) -> None:
        manifest = _manifest(worktree_provision=[_REFRESH])
        assert not any(v.rule == RULE for v in lint_loops(manifest, [_loop()]))

    def test_a_single_refresh_entry_alongside_a_bare_one_silences_it(self) -> None:
        # The predicate is manifest-wide (`any(spec.refresh ...)`): one entry
        # declaring a refresh — even on ANOTHER path — silences the whole rule.
        manifest = _manifest(worktree_provision=[_BARE, _REFRESH_OTHER])
        assert not any(v.rule == RULE for v in lint_loops(manifest, [_loop()]))

    def test_non_deps_loop_is_silent(self) -> None:
        # A `deliver`-style conduct loop bumps nothing — never flagged.
        manifest = _manifest(worktree_provision=[_BARE])
        loop = _loop(name="deliver", kind="conduct", ref=None)
        assert not any(v.rule == RULE for v in lint_loops(manifest, [loop]))

    def test_drain_only_non_deps_loop_is_silent(self) -> None:
        # Mode B (replenish is None) + a non-canonical name: the predicate must
        # short-circuit the replenish deref and stay silent.
        manifest = _manifest(worktree_provision=[_BARE])
        loop = _loop(name="cleanup", kind=None)
        assert not any(v.rule == RULE for v in lint_loops(manifest, [loop]))

    def test_no_loops_is_silent(self) -> None:
        assert lint_loops(_manifest(worktree_provision=[_BARE]), []) == []

    def test_deps_ref_under_a_signals_kind_is_silent(self) -> None:
        # `signals`/`flow`/`regression` refs name a FLOW, not a specialist — so
        # a ref that happens to read "deps" under such a kind must NOT match.
        manifest = _manifest(worktree_provision=[_BARE])
        loop = _loop(name="signal-drain", kind="signals", ref="deps")
        assert not any(v.rule == RULE for v in lint_loops(manifest, [loop]))

    def test_both_names_changed_is_a_known_false_negative(self) -> None:
        # KNOWN, ACCEPTED false negative: renaming BOTH the loop AND the deps
        # specialist defeats the name-matching predicate. Acceptable for a WARN —
        # there is no archetype/role marker on Specialist/LoopDefinition to key on
        # instead; renaming ONE is still caught (see TestLintLoopsFires).
        manifest = _manifest(worktree_provision=[_BARE])
        loop = _loop(name="package-bumps", kind="specialist", ref="pkgs")
        assert not any(v.rule == RULE for v in lint_loops(manifest, [loop]))


# ---------------------------------------------------------------------------
# Drift guard — the canonical names must track what the Maintainer pack ships
# ---------------------------------------------------------------------------


class TestCanonicalNamesTrackThePack:
    def test_scaffolded_deps_refresh_loop_matches_the_canonical_names(self) -> None:
        # If a future edit renames the pack's loop or its deps specialist, the
        # canonical constants (and thus the rule) would silently stop matching —
        # this parses the pack's own scaffolded YAML and pins both names.
        content = pack_files("maintainer", stacks=[])[".alc/loops/deps-refresh.yaml"]
        loop = LoopDefinition.model_validate(yaml.safe_load(content))
        assert loop.name == _DEPS_LOOP_CANONICAL
        assert loop.replenish is not None
        assert loop.replenish.ref == _DEPS_SPECIALIST_CANONICAL


# ---------------------------------------------------------------------------
# Cry-wolf invariant — a freshly `alc init`-ed project stays silent
# ---------------------------------------------------------------------------


class TestCryWolfInvariant:
    def test_scaffolded_project_lints_silent(self, tmp_path: Path) -> None:
        """`alc init` writes no loops, so this rule can never fire on day one —
        a rule that cries wolf on a fresh project is one operators learn to ignore."""
        scaffold(tmp_path)
        operator_layer = tmp_path / ".alc"
        from alc.intake import load_manifest

        manifest = load_manifest(operator_layer)
        assert lint_loops(manifest, load_all_loops(manifest, operator_layer)) == []


# ---------------------------------------------------------------------------
# End-to-end — `alc lint --json` surfaces the rule (a warn never fails lint)
# ---------------------------------------------------------------------------


class TestLintLoopsEndToEnd:
    def test_cmd_lint_json_surfaces_the_rule_and_exits_zero(
        self, operator_layer: Path, monkeypatch, capsys
    ) -> None:
        import argparse
        import json

        from alc.cli import cmd_lint

        loops = operator_layer / "loops"
        loops.mkdir(parents=True, exist_ok=True)
        (loops / "deps-refresh.yaml").write_text(
            pack_files("maintainer", stacks=[])[".alc/loops/deps-refresh.yaml"]
        )

        monkeypatch.chdir(operator_layer.parent)
        rc = cmd_lint(argparse.Namespace(json=True))

        data = json.loads(capsys.readouterr().out)
        rules = {v["rule"] for v in data}
        assert RULE in rules
        # A warn never fails lint — the manifest carries no worktree_provision.
        assert rc == 0
