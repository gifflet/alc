"""Clone request validation — the security surface of the clone feature."""

from __future__ import annotations

import pytest

from alc.ui import clone
from alc.ui.errors import ApiError


class TestValidateUrl:
    @pytest.mark.parametrize(
        "url",
        [
            "https://github.com/gifflet/alc.git",
            "http://internal.example/team/repo",
            "ssh://git@github.com/gifflet/alc.git",
            "git@github.com:gifflet/alc.git",
        ],
    )
    def test_accepts_ordinary_repository_urls(self, url: str) -> None:
        assert clone.validate_url(url) == url

    @pytest.mark.parametrize(
        "url",
        [
            # git runs the value of --upload-pack. This is the attack the
            # allow-list exists to stop.
            "--upload-pack=touch /tmp/pwned",
            "--config=core.sshCommand=id",
            "-u whatever",
            # ext:: hands git a command to execute, by design.
            "ext::sh -c 'id'",
            "file:///etc/passwd",
            # A scheme git would not fetch from.
            "javascript:alert(1)",
            "",
            "   ",
        ],
    )
    def test_refuses_anything_that_is_not_a_fetch(self, url: str) -> None:
        with pytest.raises(ApiError):
            clone.validate_url(url)

    def test_refuses_whitespace_so_a_url_cannot_carry_a_second_argument(self) -> None:
        with pytest.raises(ApiError) as exc:
            clone.validate_url("https://example.com/repo --upload-pack=id")
        assert "whitespace" in str(exc.value)

    def test_says_why_it_refused(self) -> None:
        with pytest.raises(ApiError) as exc:
            clone.validate_url("-x")
        assert "may not start with '-'" in str(exc.value)


class TestRepoName:
    @pytest.mark.parametrize(
        ("url", "expected"),
        [
            ("https://github.com/gifflet/alc.git", "alc"),
            ("https://github.com/gifflet/alc", "alc"),
            ("https://github.com/gifflet/alc/", "alc"),
            ("git@github.com:gifflet/alc.git", "alc"),
        ],
    )
    def test_derives_the_directory_git_would_create(self, url: str, expected: str) -> None:
        assert clone.repo_name(url) == expected


class TestResolveDestination:
    def test_uses_the_repository_name_by_default(self, tmp_path):
        target = clone.resolve_destination(str(tmp_path), "https://h/o/repo.git", None)
        assert target == tmp_path.resolve() / "repo"

    def test_an_explicit_name_wins(self, tmp_path):
        target = clone.resolve_destination(str(tmp_path), "https://h/o/repo.git", "mine")
        assert target == tmp_path.resolve() / "mine"

    def test_an_empty_directory_is_fine(self, tmp_path):
        (tmp_path / "empty").mkdir()
        assert clone.resolve_destination(str(tmp_path), "https://h/o/empty.git", None)

    def test_refuses_a_destination_that_already_has_files(self, tmp_path):
        occupied = tmp_path / "taken"
        occupied.mkdir()
        (occupied / "file").write_text("x")

        with pytest.raises(ApiError) as exc:
            clone.resolve_destination(str(tmp_path), "https://h/o/taken.git", None)
        assert "already exists and is not empty" in str(exc.value)

    @pytest.mark.parametrize("name", ["..", ".", "a/b", "a\\b", "   "])
    def test_refuses_a_name_that_would_escape_the_parent(self, tmp_path, name: str) -> None:
        with pytest.raises(ApiError):
            clone.resolve_destination(str(tmp_path), "https://h/o/r.git", name)

    def test_an_empty_name_means_use_the_repository_name(self, tmp_path):
        """The form sends "" when the operator leaves the name field alone, and
        that should mean the default rather than an error."""
        target = clone.resolve_destination(str(tmp_path), "https://h/o/repo.git", "")
        assert target == tmp_path.resolve() / "repo"

    def test_refuses_a_parent_that_is_not_a_directory(self, tmp_path):
        target = tmp_path / "f.txt"
        target.write_text("x")
        with pytest.raises(ApiError):
            clone.resolve_destination(str(target), "https://h/o/r.git", None)


def test_argv_separates_options_from_operands(tmp_path):
    argv = clone.build_argv("https://h/o/r.git", tmp_path / "r")
    # `--` means even a URL that slipped past validation cannot be read as a flag.
    assert argv[:4] == ["git", "clone", "--progress", "--"]
    assert argv[4] == "https://h/o/r.git"
