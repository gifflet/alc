# test_checks_audit.py — Hermetic tests for `alc checks audit` (roadmap-phase-2.md
# T13): the pure audit_checks() function, its CLI wiring, and the advisory Policy
# Gate rule that flags an execution Blueprint resolving to only the smoke
# placeholder. audit_checks() never writes — every assertion here is read-only.
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from alc.checks import ChecksAudit, CheckSetAudit, SmokeOnlyBlueprint, audit_checks
from alc.cli import cmd_checks
from alc.models import Blueprint, Check, Manifest
from alc.policy import lint


def _manifest(check_sets: dict | None = None) -> Manifest:
    return Manifest(
        version=1,
        default_engine="mock",
        compute_tiers={"standard": {"mock": "mock-small"}},
        engines={"mock": {"type": "mock"}},
        check_sets=check_sets or {},
    )


def _blueprint(name: str = "chore", check_set: str | None = None, checks=None) -> Blueprint:
    return Blueprint(
        name=name,
        purpose="p",
        check_set=check_set,
        checks=checks if checks is not None else [Check(name="smoke", command=["true"])],
        workflow="# w",
    )


# ---------------------------------------------------------------------------
# audit_checks — check_sets: new / add / unavailable
# ---------------------------------------------------------------------------


class TestAuditChecksCheckSets:
    def test_new_stack_not_in_manifest_is_flagged_new(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("alc.checks.shutil.which", lambda cmd: f"/usr/bin/{cmd}")
        (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")

        report = audit_checks(_manifest(), tmp_path, [])

        python_set = next(cs for cs in report.check_sets if cs.set_name == "python")
        assert python_set.is_new is True
        assert {name for name, _cmd in python_set.add} == {"test", "lint"}
        assert python_set.unavailable == []

    def test_binary_missing_reports_unavailable_not_add(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("alc.checks.shutil.which", lambda cmd: None)
        (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")

        report = audit_checks(_manifest(), tmp_path, [])

        python_set = next(cs for cs in report.check_sets if cs.set_name == "python")
        assert python_set.add == []
        assert {name for name, _cmd in python_set.unavailable} == {"test", "lint"}

    def test_uv_locked_pytest_is_proposed_through_its_runner(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A uv.lock declaring pytest -> the audit proposes `uv run pytest -q`
        (same resolution `alc init` scaffolds), not the bare binary."""
        monkeypatch.setattr("alc.checks.shutil.which", lambda cmd: f"/usr/bin/{cmd}")
        (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")
        (tmp_path / "uv.lock").write_text(
            'version = 1\n\n[[package]]\nname = "pytest"\nversion = "9.1.1"\n'
        )

        report = audit_checks(_manifest(), tmp_path, [])

        python_set = next(cs for cs in report.check_sets if cs.set_name == "python")
        assert dict(python_set.add)["test"] == ["uv", "run", "pytest", "-q"]
        assert dict(python_set.add)["lint"] == ["ruff", "check", "."]  # not locked

    def test_already_live_check_is_not_proposed_again(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("alc.checks.shutil.which", lambda cmd: f"/usr/bin/{cmd}")
        (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")
        manifest = _manifest(
            check_sets={"python": [Check(name="test", command=["pytest", "-q"])]}
        )

        report = audit_checks(manifest, tmp_path, [])

        python_set = next(cs for cs in report.check_sets if cs.set_name == "python")
        assert python_set.is_new is False
        assert {name for name, _cmd in python_set.add} == {"lint"}  # "test" already live

    def test_fully_up_to_date_set_is_omitted(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("alc.checks.shutil.which", lambda cmd: None)  # nothing installed
        (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")
        manifest = _manifest(
            check_sets={
                "python": [
                    Check(name="test", command=["pytest", "-q"]),
                    Check(name="lint", command=["ruff", "check", "."]),
                ]
            }
        )

        report = audit_checks(manifest, tmp_path, [])

        assert not any(cs.set_name == "python" for cs in report.check_sets)

    def test_no_stack_still_audits_the_security_set(self, tmp_path: Path) -> None:
        report = audit_checks(_manifest(), tmp_path, [])
        assert any(cs.set_name == "security" for cs in report.check_sets)

    def test_no_proposals_has_proposals_is_false(self, tmp_path: Path) -> None:
        # gitleaks (the only stack-agnostic security check) unavailable, no stack:
        # still ends up with an empty ChecksAudit whenever nothing is actionable.
        report = ChecksAudit(check_sets=[], smoke_only_blueprints=[])
        assert report.has_proposals is False

    def test_unavailable_only_set_still_has_no_proposals(self) -> None:
        report = ChecksAudit(
            check_sets=[
                CheckSetAudit(
                    set_name="security", is_new=False, add=[], unavailable=[("gitleaks", ["gitleaks", "detect"])]
                )
            ],
            smoke_only_blueprints=[],
        )
        assert report.has_proposals is False

    def test_add_proposal_has_proposals_is_true(self) -> None:
        report = ChecksAudit(
            check_sets=[
                CheckSetAudit(
                    set_name="python", is_new=True, add=[("test", ["pytest", "-q"])], unavailable=[]
                )
            ],
            smoke_only_blueprints=[],
        )
        assert report.has_proposals is True


# ---------------------------------------------------------------------------
# audit_checks — smoke-only Blueprints
# ---------------------------------------------------------------------------


class TestAuditChecksSmokeOnlyBlueprints:
    def test_smoke_only_blueprint_flagged_when_stack_detected(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")
        bp = _blueprint("chore")

        report = audit_checks(_manifest(), tmp_path, [bp])

        assert report.smoke_only_blueprints == [
            SmokeOnlyBlueprint(blueprint="chore", stacks=["Python"])
        ]

    def test_stackless_smoke_only_blueprint_is_flagged(self, tmp_path: Path) -> None:
        """No stack detected is the case that needs the warning MOST — flag it,
        with ``stacks=[]`` marking the stackless variant."""
        bp = _blueprint("chore")
        report = audit_checks(_manifest(), tmp_path, [bp])
        assert report.smoke_only_blueprints == [
            SmokeOnlyBlueprint(blueprint="chore", stacks=[])
        ]

    def test_plan_is_exempt_even_with_no_stack(self, tmp_path: Path) -> None:
        report = audit_checks(_manifest(), tmp_path, [_blueprint("plan"), _blueprint("chore")])
        assert [s.blueprint for s in report.smoke_only_blueprints] == ["chore"]

    def test_blueprint_with_real_checks_not_flagged(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")
        bp = _blueprint("chore", checks=[Check(name="test", command=["pytest", "-q"])])
        report = audit_checks(_manifest(), tmp_path, [bp])
        assert report.smoke_only_blueprints == []

    def test_plan_is_never_flagged(self, tmp_path: Path) -> None:
        """`plan` keeps the smoke placeholder by design — a planning stage writes no code."""
        (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")

        report = audit_checks(_manifest(), tmp_path, [_blueprint("plan"), _blueprint("chore")])

        assert [s.blueprint for s in report.smoke_only_blueprints] == ["chore"]


# ---------------------------------------------------------------------------
# CLI — `alc checks audit [--json]`
# ---------------------------------------------------------------------------


def _ns(**overrides) -> argparse.Namespace:
    defaults = {"checks_action": "audit", "json": False}
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


class TestChecksAuditCli:
    def test_never_writes_anything(
        self, operator_layer: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(operator_layer.parent)
        before = sorted(p.relative_to(operator_layer.parent) for p in operator_layer.rglob("*"))
        assert cmd_checks(_ns()) == 0
        after = sorted(p.relative_to(operator_layer.parent) for p in operator_layer.rglob("*"))
        assert before == after

    def test_security_set_always_appears_even_with_no_stack(
        self, operator_layer: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        monkeypatch.chdir(operator_layer.parent)
        assert cmd_checks(_ns()) == 0
        out = capsys.readouterr().out
        assert "security" in out  # `_build_check_sets` always includes it

    def test_json_output_matches_audit_checks(
        self, operator_layer: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        monkeypatch.chdir(operator_layer.parent)
        assert cmd_checks(_ns(json=True)) == 0
        data = json.loads(capsys.readouterr().out)
        assert "check_sets" in data
        assert "smoke_only_blueprints" in data

    def test_stackless_smoke_only_blueprint_prints_honest_message(
        self, operator_layer: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        # The operator_layer fixture has a smoke-only `chore` and no stack markers.
        monkeypatch.chdir(operator_layer.parent)
        assert cmd_checks(_ns()) == 0
        out = capsys.readouterr().out
        assert "chore" in out
        assert "no stack was detected" in out
        # Now that `alc onboard` exists, the honest nudge points at the harvest path.
        assert "alc onboard" in out

    def test_add_proposal_prints_a_pasteable_snippet(
        self, operator_layer: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        # Every binary "available" -> gitleaks (in the always-present security set)
        # is an add proposal, and the audit prints a manifest-ready YAML fragment.
        monkeypatch.setattr("alc.checks.shutil.which", lambda cmd: f"/usr/bin/{cmd}")
        monkeypatch.chdir(operator_layer.parent)
        assert cmd_checks(_ns()) == 0
        out = capsys.readouterr().out
        assert "- name: gitleaks" in out
        assert 'command: ["gitleaks", "detect"]' in out

    def test_bare_checks_action_none_prints_audit_not_history(
        self, operator_layer: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        # GAP 1: a bare `alc checks` (checks_action None) opens on the audit read
        # view, never a usage error. The fixture's stackless smoke-only `chore`
        # prints audit's honest "no stack was detected" nudge — a message unique
        # to the audit path (history aggregates run logs, never says this).
        monkeypatch.chdir(operator_layer.parent)
        assert cmd_checks(_ns(checks_action=None)) == 0
        out = capsys.readouterr().out
        assert "no stack was detected" in out


# ---------------------------------------------------------------------------
# CLI header — "No upgrades proposed" only when there is truly NOTHING to
# show; an informational-only report (unavailable entries) gets an honest
# header instead of a contradiction ("nothing proposed" above a list).
# ---------------------------------------------------------------------------

# A chore blueprint with a REAL inline check, so the layer has no smoke-only
# execution blueprint (which would count as a proposal and mask the
# informational-only case these specs isolate).
_REAL_CHECK_CHORE = """\
---
name: chore
purpose: Apply a low-risk, well-scoped maintenance change.
compute_tier: standard
checks:
  - name: scan
    command: ["gitleaks", "detect"]
report:
  format: json
  schema:
    status: string
---
# Workflow
1. Make the smallest change that satisfies the task.
"""

_MANIFEST_TEMPLATE = """\
version: 1
default_engine: mock
compute_tiers:
  standard:
    mock: mock-small
  deep:
    mock: mock-large
engines:
  mock:
    type: mock
check_sets:
{check_sets}
blueprints_dir: .alc/blueprints
flows_dir: .alc/flows
queue_dir: .alc/queue
"""


def _real_check_layer(tmp_path: Path, check_sets_yaml: str) -> Path:
    """A hermetic layer whose chore blueprint carries a real check (never
    smoke-only) and whose manifest declares *check_sets_yaml*."""
    alc = tmp_path / ".alc"
    (alc / "blueprints").mkdir(parents=True)
    (alc / "manifest.yaml").write_text(
        _MANIFEST_TEMPLATE.format(check_sets=check_sets_yaml)
    )
    (alc / "blueprints" / "chore.md").write_text(_REAL_CHECK_CHORE)
    return alc


class TestChecksAuditCliHeaders:
    def test_truly_empty_report_prints_no_upgrades_proposed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        # gitleaks (the whole fresh security battery) is already live in the
        # Manifest -> nothing to add, nothing informational, nothing smoke-only.
        _real_check_layer(
            tmp_path,
            '  security:\n    - name: gitleaks\n      command: ["gitleaks", "detect"]',
        )
        monkeypatch.setattr("alc.checks.shutil.which", lambda cmd: None)
        monkeypatch.chdir(tmp_path)

        assert cmd_checks(_ns()) == 0

        out = capsys.readouterr().out
        assert "No upgrades proposed" in out
        assert "No actionable upgrades" not in out

    def test_informational_only_report_gets_an_honest_header(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        # The security set EXISTS (not new) but gitleaks' binary is absent:
        # the only content is informational, so the header says exactly that —
        # never "No upgrades proposed" directly above a printed list.
        _real_check_layer(tmp_path, "  security: []")
        monkeypatch.setattr("alc.checks.shutil.which", lambda cmd: None)
        monkeypatch.chdir(tmp_path)

        assert cmd_checks(_ns()) == 0

        out = capsys.readouterr().out
        assert "No upgrades proposed" not in out
        assert "No actionable upgrades" in out
        assert "gitleaks" in out  # the informational list still prints

    def test_actionable_report_prints_neither_header(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        _real_check_layer(tmp_path, "  security: []")
        monkeypatch.setattr("alc.checks.shutil.which", lambda cmd: f"/usr/bin/{cmd}")
        monkeypatch.chdir(tmp_path)

        assert cmd_checks(_ns()) == 0

        out = capsys.readouterr().out
        assert "No upgrades proposed" not in out
        assert "No actionable upgrades" not in out
        assert "+ gitleaks" in out


# ---------------------------------------------------------------------------
# install_hints — "declared but not installed" is actionable, "not used by the
# project" is not; the audit tells them apart (per-check hint via pydeps).
# ---------------------------------------------------------------------------


class TestAuditInstallHints:
    def test_declared_dev_dependency_gets_a_pyproject_hint(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("alc.checks.shutil.which", lambda cmd: None)
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname="x"\nversion="0"\n\n[dependency-groups]\ndev = ["pytest"]\n'
        )

        report = audit_checks(_manifest(), tmp_path, [])

        python_set = next(cs for cs in report.check_sets if cs.set_name == "python")
        assert {name for name, _cmd in python_set.unavailable} == {"test", "lint"}
        assert "declared in pyproject.toml" in python_set.install_hints["test"]
        assert "lint" not in python_set.install_hints  # ruff is NOT declared

    def test_undeclared_tool_keeps_no_hint(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("alc.checks.shutil.which", lambda cmd: None)
        (tmp_path / "pyproject.toml").write_text('[project]\nname="x"\nversion="0"\n')

        report = audit_checks(_manifest(), tmp_path, [])

        python_set = next(cs for cs in report.check_sets if cs.set_name == "python")
        assert python_set.install_hints == {}

    def test_missing_env_manager_gets_a_runner_hint(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """uv.lock declares pytest so the proposal is `uv run pytest -q`, but uv
        itself is off PATH — the hint targets the env manager."""
        monkeypatch.setattr("alc.checks.shutil.which", lambda cmd: None)
        (tmp_path / "pyproject.toml").write_text('[project]\nname="x"\nversion="0"\n')
        (tmp_path / "uv.lock").write_text(
            'version = 1\n\n[[package]]\nname = "pytest"\nversion = "9.1.1"\n'
        )

        report = audit_checks(_manifest(), tmp_path, [])

        python_set = next(cs for cs in report.check_sets if cs.set_name == "python")
        assert dict(python_set.unavailable)["test"] == ["uv", "run", "pytest", "-q"]
        assert "install uv" in python_set.install_hints["test"]

    def test_cli_prints_the_hint_on_the_unavailable_line(
        self, operator_layer: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        monkeypatch.setattr("alc.checks.shutil.which", lambda cmd: None)
        (operator_layer.parent / "pyproject.toml").write_text(
            '[project]\nname="x"\nversion="0"\n\n[dependency-groups]\ndev = ["pytest"]\n'
        )
        monkeypatch.chdir(operator_layer.parent)

        assert cmd_checks(_ns()) == 0

        out = capsys.readouterr().out
        assert "declared in pyproject.toml" in out


# ---------------------------------------------------------------------------
# Policy Gate — advisory smoke-only-execution-blueprint rule (T13)
# ---------------------------------------------------------------------------


class TestSmokeOnlyPolicyRule:
    def _manifest_with_empty_set(self) -> Manifest:
        return _manifest(check_sets={"python": []})

    def test_warns_when_check_set_resolves_empty_and_own_checks_are_smoke_only(self) -> None:
        bp = _blueprint("chore", check_set="python")
        violations = lint(self._manifest_with_empty_set(), [bp])
        matching = [v for v in violations if v.rule == "blueprint-checks-smoke-only"]
        assert len(matching) == 1
        assert matching[0].severity == "warn"

    def test_no_warn_when_check_set_resolves_to_real_checks(self) -> None:
        manifest = _manifest(check_sets={"python": [Check(name="test", command=["pytest", "-q"])]})
        bp = _blueprint("chore", check_set="python")
        violations = lint(manifest, [bp])
        assert not any(v.rule == "blueprint-checks-smoke-only" for v in violations)

    def test_plan_blueprint_is_always_exempt(self) -> None:
        # Constraint: a planning stage legitimately produces no executable code.
        bp = _blueprint("plan", check_set="python")
        violations = lint(self._manifest_with_empty_set(), [bp])
        assert not any(v.rule == "blueprint-checks-smoke-only" for v in violations)

    def test_no_check_set_warns_when_smoke_only(self) -> None:
        # The constraint this once pinned ("the default init layer must stay
        # lint-clean") was reversed on purpose: a check that always passes is
        # not a guarantee, and staying silent about it was the gap the site
        # friction study proved — the gate refused an EMPTY check list and said
        # nothing about one that cannot fail. Firing on every fresh project is
        # correct; a warn never blocks (exit stays 0).
        bp = _blueprint("chore", check_set=None)
        violations = lint(_manifest(), [bp])
        hits = [v for v in violations if v.rule == "blueprint-checks-smoke-only"]
        assert len(hits) == 1
        assert hits[0].severity == "warn"
        assert "alc onboard" in hits[0].message

    def test_the_inline_and_check_set_paths_never_double_fire(self) -> None:
        # Rule 16 covers check_set=None, rule 11 covers a declared-but-empty
        # set. One Blueprint must land in exactly one of them.
        bp = _blueprint("chore", check_set="python")
        violations = lint(self._manifest_with_empty_set(), [bp])
        hits = [v for v in violations if v.rule == "blueprint-checks-smoke-only"]
        assert len(hits) == 1

    def test_a_real_inline_check_stays_silent(self) -> None:
        bp = _blueprint("chore", check_set=None, checks=[Check(name="test", command=["pytest", "-q"])])
        violations = lint(_manifest(), [bp])
        assert not any(v.rule == "blueprint-checks-smoke-only" for v in violations)

    def test_hint_names_a_populated_alternative_set_when_one_exists(self) -> None:
        # The hired-pack case: `test` points at the empty `python` set while a
        # populated `project` set (onboard's harvest) already exists — the WARN
        # should name it so the remedy is actionable, not the dead-end audit hint.
        manifest = _manifest(
            check_sets={
                "python": [],
                "project": [Check(name="test", command=["make", "test"])],
            }
        )
        bp = _blueprint("test", check_set="python")
        [warn] = [v for v in lint(manifest, [bp]) if v.rule == "blueprint-checks-smoke-only"]
        assert "'project'" in warn.message
        assert "check_set: project" in warn.message
        assert "alc checks audit" in warn.message  # kept as a secondary pointer

    def test_hint_falls_back_to_audit_when_no_populated_alternative(self) -> None:
        # With no other populated set, the actionable pointer has nothing to name,
        # so the original `alc checks audit` remedy is preserved unchanged.
        bp = _blueprint("chore", check_set="python")
        [warn] = [
            v
            for v in lint(self._manifest_with_empty_set(), [bp])
            if v.rule == "blueprint-checks-smoke-only"
        ]
        assert "Run `alc checks audit` to see what would become available." in warn.message
        assert "A populated check_set already exists" not in warn.message
