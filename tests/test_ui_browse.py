"""Filesystem browsing for the project picker."""

from __future__ import annotations

import os

import pytest

from alc.ui import browse
from alc.ui.errors import ApiError


def test_lists_only_directories(tmp_path):
    (tmp_path / "a-dir").mkdir()
    (tmp_path / "b-file.txt").write_text("not a directory")

    listing = browse.list_directory(str(tmp_path))

    names = [e.name for e in listing.entries]
    assert names == ["a-dir"]
    # A file name is never returned: the picker chooses folders, and listing
    # file names would expose more than the job needs.
    assert "b-file.txt" not in names


def test_hides_dot_directories_unless_asked(tmp_path):
    (tmp_path / "visible").mkdir()
    (tmp_path / ".hidden").mkdir()

    assert [e.name for e in browse.list_directory(str(tmp_path)).entries] == ["visible"]

    with_hidden = browse.list_directory(str(tmp_path), show_hidden=True)
    assert sorted(e.name for e in with_hidden.entries) == [".hidden", "visible"]


def test_marks_alc_projects_and_git_repos(tmp_path):
    project = tmp_path / "a-project"
    (project / ".alc").mkdir(parents=True)
    repo = tmp_path / "a-repo"
    (repo / ".git").mkdir(parents=True)
    plain = tmp_path / "plain"
    plain.mkdir()

    by_name = {e.name: e for e in browse.list_directory(str(tmp_path)).entries}

    assert by_name["a-project"].is_alc_project and not by_name["a-project"].is_git_repo
    assert by_name["a-repo"].is_git_repo and not by_name["a-repo"].is_alc_project
    assert not by_name["plain"].is_alc_project and not by_name["plain"].is_git_repo


def test_reports_the_parent_so_the_caller_can_go_up(tmp_path):
    child = tmp_path / "child"
    child.mkdir()

    listing = browse.list_directory(str(child))

    assert listing.parent == str(tmp_path.resolve())


def test_root_has_no_parent():
    # At "/" the parent is itself; reporting it would render a step-up control
    # that goes nowhere.
    assert browse.list_directory("/").parent is None


def test_resolves_symlinks_to_their_target(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real)

    listing = browse.list_directory(str(link))

    # The returned path is where the caller actually is, so the UI cannot show
    # one location while meaning another.
    assert listing.path == str(real.resolve())


def test_expands_the_home_shorthand(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / "inside").mkdir()

    assert [e.name for e in browse.list_directory("~").entries] == ["inside"]


def test_defaults_to_the_home_directory(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / "inside").mkdir()

    assert browse.list_directory(None).path == str(tmp_path.resolve())


def test_missing_path_is_a_404(tmp_path):
    with pytest.raises(ApiError) as exc:
        browse.list_directory(str(tmp_path / "nope"))
    assert exc.value.status == 404


def test_a_file_is_a_400_not_an_empty_listing(tmp_path):
    target = tmp_path / "file.txt"
    target.write_text("x")

    with pytest.raises(ApiError) as exc:
        browse.list_directory(str(target))
    # Saying "not a directory" beats rendering an empty folder, which would
    # look like a directory that happens to be empty.
    assert exc.value.status == 400
    assert "not a directory" in str(exc.value)


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads regardless of mode")
def test_an_unreadable_child_is_skipped_not_fatal(tmp_path):
    (tmp_path / "readable").mkdir()
    locked = tmp_path / "locked"
    locked.mkdir()
    locked.chmod(0o000)
    try:
        names = [e.name for e in browse.list_directory(str(tmp_path)).entries]
        # The locked directory is still listed — we only stat it, we do not
        # descend. What must not happen is the parent becoming unlistable.
        assert "readable" in names
    finally:
        locked.chmod(0o755)
