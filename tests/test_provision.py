# test_provision.py — Part A: worktree provisioning of gitignored runtime deps.
# Hermetic: ProvisionSpec is pure; provision_worktree uses only tmp_path; the
# wiring + lint tests use a local git repo in tmp_path. No model is called.
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from pydantic import ValidationError

from alc.intake import load_manifest
from alc.models import Manifest, ProvisionSpec
from alc.policy import has_errors, validate_provisions
from alc.worktree import provision_worktree


# ---------------------------------------------------------------------------
# ProvisionSpec — exactly-one-of + kind/path properties
# ---------------------------------------------------------------------------


class TestProvisionSpec:
    def test_link_spec_kind_and_path(self) -> None:
        spec = ProvisionSpec(link=".env")
        assert spec.kind == "link"
        assert spec.path == ".env"

    def test_copy_spec_kind_and_path(self) -> None:
        spec = ProvisionSpec(copy="data")
        assert spec.kind == "copy"
        assert spec.path == "data"

    def test_clone_spec_kind_and_path(self) -> None:
        spec = ProvisionSpec(clone="node_modules")
        assert spec.kind == "clone"
        assert spec.path == "node_modules"

    def test_zero_set_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ProvisionSpec()

    def test_two_set_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ProvisionSpec(link=".env", copy=".env")

    def test_all_three_set_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ProvisionSpec(link="a", copy="b", clone="c")

    def test_absolute_path_is_rejected(self) -> None:
        # A provision path is joined onto a worktree, so it must stay in-tree.
        with pytest.raises(ValidationError):
            ProvisionSpec(copy="/etc/passwd")

    def test_parent_traversal_path_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ProvisionSpec(link="../secrets")

    def test_nested_relative_path_is_allowed(self) -> None:
        # A normal relative path (even nested) is fine.
        assert ProvisionSpec(copy="data/app").path == "data/app"


class TestManifestWorktreeProvisionDefault:
    def test_default_is_empty_list(self) -> None:
        manifest = Manifest(
            version=1,
            default_engine="mock",
            compute_tiers={"standard": {"mock": "mock-small"}},
            engines={"mock": {"type": "mock"}},
        )
        assert manifest.worktree_provision == []


# ---------------------------------------------------------------------------
# provision_worktree — link (shared) vs copy/clone (isolated)
# ---------------------------------------------------------------------------


def _make_project(base: Path) -> tuple[Path, Path]:
    """Create a project root with a nested dir dep and a single-file dep.

    Returns ``(project_root, worktree)`` — both are empty of the deps at first.
    """
    project = base / "project"
    (project / "node_modules" / "pkg").mkdir(parents=True)
    (project / "node_modules" / "pkg" / "index.js").write_text("original\n")
    (project / ".env").write_text("SECRET=original\n")
    worktree = base / "worktree"
    worktree.mkdir()
    return project, worktree


class TestProvisionLink:
    def test_link_is_a_symlink_sharing_the_source(self, tmp_path: Path) -> None:
        project, worktree = _make_project(tmp_path)
        provision_worktree(worktree, project, [ProvisionSpec(link="node_modules")])

        dst = worktree / "node_modules"
        assert dst.is_symlink()
        assert dst.resolve() == (project / "node_modules").resolve()

        # A change to the source IS visible through the link (proves it's shared).
        (project / "node_modules" / "pkg" / "index.js").write_text("changed\n")
        assert (dst / "pkg" / "index.js").read_text() == "changed\n"

    def test_link_a_single_file(self, tmp_path: Path) -> None:
        project, worktree = _make_project(tmp_path)
        provision_worktree(worktree, project, [ProvisionSpec(link=".env")])

        dst = worktree / ".env"
        assert dst.is_symlink()
        assert dst.read_text() == "SECRET=original\n"


class TestProvisionCopy:
    def test_copy_a_dir_is_isolated(self, tmp_path: Path) -> None:
        project, worktree = _make_project(tmp_path)
        provision_worktree(worktree, project, [ProvisionSpec(copy="node_modules")])

        dst = worktree / "node_modules"
        assert dst.is_dir() and not dst.is_symlink()
        assert (dst / "pkg" / "index.js").read_text() == "original\n"

        # Writing into the worktree copy does NOT change the source.
        (dst / "pkg" / "index.js").write_text("worktree-edit\n")
        assert (project / "node_modules" / "pkg" / "index.js").read_text() == "original\n"

        # A change to the source does NOT appear in the copy (key safety property).
        (project / "node_modules" / "pkg" / "index.js").write_text("source-edit\n")
        assert (dst / "pkg" / "index.js").read_text() == "worktree-edit\n"

    def test_copy_a_single_file_is_isolated(self, tmp_path: Path) -> None:
        project, worktree = _make_project(tmp_path)
        provision_worktree(worktree, project, [ProvisionSpec(copy=".env")])

        dst = worktree / ".env"
        assert not dst.is_symlink()
        dst.write_text("SECRET=worktree\n")
        assert (project / ".env").read_text() == "SECRET=original\n"


class TestProvisionClone:
    def test_clone_a_dir_is_isolated(self, tmp_path: Path) -> None:
        # The isolation must hold whether clone used COW or the copy fallback.
        project, worktree = _make_project(tmp_path)
        provision_worktree(worktree, project, [ProvisionSpec(clone="node_modules")])

        dst = worktree / "node_modules"
        assert dst.is_dir() and not dst.is_symlink()
        assert (dst / "pkg" / "index.js").read_text() == "original\n"

        # Writing into the worktree clone does NOT change the source.
        (dst / "pkg" / "index.js").write_text("worktree-edit\n")
        assert (project / "node_modules" / "pkg" / "index.js").read_text() == "original\n"

        # A change to the source does NOT appear in the clone.
        (project / "node_modules" / "pkg" / "index.js").write_text("source-edit\n")
        assert (dst / "pkg" / "index.js").read_text() == "worktree-edit\n"

    def test_clone_falls_back_when_cow_unsupported(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        # Force `cp` to fail (simulating a filesystem with no COW): the fallback
        # deep copy must still produce an ISOLATED copy.
        import alc.worktree as wt_mod

        real_run = subprocess.run

        def _failing_run(cmd, *args, **kwargs):
            if cmd and cmd[0] == "cp":
                return subprocess.CompletedProcess(cmd, 1, b"", b"no reflink")
            return real_run(cmd, *args, **kwargs)

        monkeypatch.setattr(wt_mod.subprocess, "run", _failing_run)

        project, worktree = _make_project(tmp_path)
        provision_worktree(worktree, project, [ProvisionSpec(clone="node_modules")])

        dst = worktree / "node_modules"
        assert dst.is_dir() and not dst.is_symlink()
        assert (dst / "pkg" / "index.js").read_text() == "original\n"

        # Isolation still holds via the deep-copy fallback.
        (project / "node_modules" / "pkg" / "index.js").write_text("source-edit\n")
        assert (dst / "pkg" / "index.js").read_text() == "original\n"


class TestProvisionEdgeCases:
    def test_missing_source_is_skipped(self, tmp_path: Path) -> None:
        project, worktree = _make_project(tmp_path)
        provision_worktree(worktree, project, [ProvisionSpec(copy="does-not-exist")])
        assert not (worktree / "does-not-exist").exists()

    def test_empty_provisions_is_a_noop(self, tmp_path: Path) -> None:
        project, worktree = _make_project(tmp_path)
        provision_worktree(worktree, project, [])
        assert list(worktree.iterdir()) == []

    def test_existing_placeholder_is_replaced(self, tmp_path: Path) -> None:
        # A worktree may carry a tracked placeholder at the dst path; it must be
        # removed before the provision so the result is deterministic.
        project, worktree = _make_project(tmp_path)
        placeholder = worktree / ".env"
        placeholder.write_text("PLACEHOLDER\n")

        provision_worktree(worktree, project, [ProvisionSpec(copy=".env")])
        assert (worktree / ".env").read_text() == "SECRET=original\n"

    def test_creates_missing_parent_dirs(self, tmp_path: Path) -> None:
        project = tmp_path / "project"
        (project / "config").mkdir(parents=True)
        (project / "config" / "secret.env").write_text("K=V\n")
        worktree = tmp_path / "worktree"
        worktree.mkdir()

        provision_worktree(
            worktree, project, [ProvisionSpec(copy="config/secret.env")]
        )
        assert (worktree / "config" / "secret.env").read_text() == "K=V\n"


# ---------------------------------------------------------------------------
# _process_task wiring — provisioning fires inside the worktree run
# ---------------------------------------------------------------------------


def _init_git(root: Path) -> None:
    """Init a git repo at *root* with one commit so worktrees can be created."""
    subprocess.run(["git", "init", str(root)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(root), "config", "user.email", "test@alc.local"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(root), "config", "user.name", "ALC Test"],
        check=True,
        capture_output=True,
    )


def _commit_all(root: Path, message: str = "init") -> None:
    # Seed a tracked file so the initial commit always has content to record.
    (root / "seed.txt").write_text("seed\n")
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(root), "commit", "-m", message], check=True, capture_output=True
    )


class TestProcessTaskWiring:
    def test_provisioned_dep_is_present_during_the_run(
        self, operator_layer: Path, monkeypatch
    ) -> None:
        from alc import queue as queue_mod

        project_root = operator_layer.parent
        _init_git(project_root)
        # A gitignored runtime dep at the project root (absent from a fresh worktree).
        (project_root / ".env").write_text("SECRET=live\n")
        (project_root / ".gitignore").write_text(".env\n")
        _commit_all(project_root)

        # Rewrite the manifest to declare a provision and load it.
        manifest = load_manifest(operator_layer)
        manifest = manifest.model_copy(
            update={"worktree_provision": [ProvisionSpec(link=".env")]}
        )

        # Spy provision_worktree to capture its args (and still run the real one).
        # The worktree is torn down on exit, so record dep existence AT provision
        # time (which is during the run) rather than after process_queue returns.
        calls: list[tuple] = []
        real_provision = queue_mod.provision_worktree

        def _spy(worktree, root, provisions):
            result = real_provision(worktree, root, provisions)
            calls.append((worktree, root, provisions, (worktree / ".env").exists()))
            return result

        monkeypatch.setattr(queue_mod, "provision_worktree", _spy)

        queue_dir = operator_layer / "queue"
        queue_dir.mkdir(parents=True, exist_ok=True)
        (queue_dir / "t1.yaml").write_text(
            "flow: ship\ntask: \"tidy\"\nengine: mock\nisolate: true\n"
        )

        results = queue_mod.process_queue(manifest, operator_layer)

        assert len(results) == 1
        # provision_worktree was called once, with (worktree_path, project_root, provisions).
        assert len(calls) == 1
        _wt_path, root_arg, provisions_arg, dep_existed = calls[0]
        assert root_arg == project_root
        assert provisions_arg == manifest.worktree_provision
        # The provisioned dep existed inside the worktree during the run.
        assert dep_existed is True

    def test_empty_provisions_makes_no_effect(
        self, operator_layer: Path, monkeypatch
    ) -> None:
        from alc import queue as queue_mod

        project_root = operator_layer.parent
        _init_git(project_root)
        _commit_all(project_root)

        manifest = load_manifest(operator_layer)  # worktree_provision defaults to []

        seen: list[list] = []
        real_provision = queue_mod.provision_worktree

        def _spy(worktree, root, provisions):
            seen.append(provisions)
            return real_provision(worktree, root, provisions)

        monkeypatch.setattr(queue_mod, "provision_worktree", _spy)

        queue_dir = operator_layer / "queue"
        queue_dir.mkdir(parents=True, exist_ok=True)
        (queue_dir / "t1.yaml").write_text(
            "flow: ship\ntask: \"tidy\"\nengine: mock\nisolate: true\n"
        )

        results = queue_mod.process_queue(manifest, operator_layer)

        assert len(results) == 1
        # provision_worktree runs but with an EMPTY list -> zero filesystem effect.
        assert seen == [[]]


# ---------------------------------------------------------------------------
# lint — reject provisioning a TRACKED path
# ---------------------------------------------------------------------------


def _manifest_with_provision(spec: ProvisionSpec) -> Manifest:
    return Manifest(
        version=1,
        default_engine="mock",
        compute_tiers={"standard": {"mock": "mock-small"}},
        engines={"mock": {"type": "mock"}},
        worktree_provision=[spec],
    )


class TestValidateProvisions:
    def test_tracked_path_is_an_error(self, tmp_path: Path) -> None:
        _init_git(tmp_path)
        (tmp_path / "tracked.txt").write_text("in the repo\n")
        _commit_all(tmp_path)

        manifest = _manifest_with_provision(ProvisionSpec(copy="tracked.txt"))
        violations = validate_provisions(manifest, tmp_path)
        assert has_errors(violations)
        assert any(v.rule == "worktree-provision-tracked" for v in violations)

    def test_gitignored_path_is_ok(self, tmp_path: Path) -> None:
        _init_git(tmp_path)
        (tmp_path / ".gitignore").write_text(".env\n")
        (tmp_path / ".env").write_text("SECRET=x\n")
        _commit_all(tmp_path)

        manifest = _manifest_with_provision(ProvisionSpec(link=".env"))
        violations = validate_provisions(manifest, tmp_path)
        assert not any(v.rule == "worktree-provision-tracked" for v in violations)

    def test_outside_a_git_repo_is_ok(self, tmp_path: Path) -> None:
        (tmp_path / ".env").write_text("SECRET=x\n")
        manifest = _manifest_with_provision(ProvisionSpec(link=".env"))
        violations = validate_provisions(manifest, tmp_path)
        assert violations == []

    def test_empty_provision_is_ok(self, tmp_path: Path) -> None:
        _init_git(tmp_path)
        _commit_all(tmp_path)
        manifest = Manifest(
            version=1,
            default_engine="mock",
            compute_tiers={"standard": {"mock": "mock-small"}},
            engines={"mock": {"type": "mock"}},
        )  # worktree_provision defaults to []
        assert validate_provisions(manifest, tmp_path) == []
