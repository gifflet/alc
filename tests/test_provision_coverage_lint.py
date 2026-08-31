# test_provision_coverage_lint.py — a check that cds into a dir with gitignored
# deps, and no provision covering them, must be named at LINT time.
#
# Dogfood finding 6: worktree_provision is optional, so deleting it keeps lint
# green while every isolated run silently loses its node_modules — and finding 3
# shows what that buys: npx stray-package walls and a burned repair turn. The
# rule is deliberately narrow (the A3 lesson): deps must exist ON DISK and the
# check must actually cd into that directory.
from __future__ import annotations

from pathlib import Path

from alc.models import Blueprint, Check, Manifest, ProvisionSpec
from alc.policy import lint_provision_coverage


def _manifest(provisions: list[ProvisionSpec] | None = None, check_sets=None) -> Manifest:
    return Manifest(
        version=1,
        default_engine="mock",
        compute_tiers={"standard": {"mock": "mock-small"}},
        engines={"mock": {"type": "mock"}},
        worktree_provision=provisions or [],
        check_sets=check_sets or {},
    )


def _bp(shell: str | None = None, command: list[str] | None = None) -> Blueprint:
    check = Check(name="ui-test", shell=shell) if shell else Check(name="test", command=command)
    return Blueprint(name="chore", purpose="p", checks=[check], workflow="# w")


def _node_project(tmp_path: Path) -> Path:
    (tmp_path / "ui" / "node_modules").mkdir(parents=True)
    return tmp_path


class TestProvisionCoverage:
    def test_warns_when_a_cd_check_has_no_provision(self, tmp_path: Path) -> None:
        root = _node_project(tmp_path)
        violations = lint_provision_coverage(_manifest(), [_bp(shell="cd ui && npx vitest run")], root)

        assert len(violations) == 1
        v = violations[0]
        assert v.rule == "provision-missing-for-check-dir"
        assert v.severity == "warn"
        assert "clone: ui/node_modules" in v.message

    def test_a_declared_provision_silences_it(self, tmp_path: Path) -> None:
        root = _node_project(tmp_path)
        manifest = _manifest([ProvisionSpec(clone="ui/node_modules")])
        assert lint_provision_coverage(manifest, [_bp(shell="cd ui && npx vitest run")], root) == []

    def test_linking_the_whole_dir_also_counts(self, tmp_path: Path) -> None:
        root = _node_project(tmp_path)
        manifest = _manifest([ProvisionSpec(link="ui")])
        assert lint_provision_coverage(manifest, [_bp(shell="cd ui && npx vitest run")], root) == []

    def test_uninstalled_deps_stay_silent(self, tmp_path: Path) -> None:
        # No node_modules on disk -> a different problem, not this rule's.
        assert lint_provision_coverage(_manifest(), [_bp(shell="cd ui && npm test")], tmp_path) == []

    def test_root_level_checks_stay_silent(self, tmp_path: Path) -> None:
        _node_project(tmp_path)
        assert lint_provision_coverage(_manifest(), [_bp(command=["pytest", "-q"])], tmp_path) == []

    def test_one_warn_per_directory_not_per_check(self, tmp_path: Path) -> None:
        root = _node_project(tmp_path)
        bp = Blueprint(
            name="chore", purpose="p", workflow="# w",
            checks=[
                Check(name="ui-test", shell="cd ui && npx vitest run"),
                Check(name="ui-typecheck", shell="cd ui && npx tsc --noEmit"),
            ],
        )
        assert len(lint_provision_coverage(_manifest(), [bp], root)) == 1
