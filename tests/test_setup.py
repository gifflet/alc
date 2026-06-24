# test_setup.py — Hermetic tests for setup_skill.py and the `alc setup` command.
# Never touches the real ~/.claude directory.
from __future__ import annotations

from pathlib import Path

import pytest

from alc.setup_skill import install_skill, render_skill


class TestInstallSkillWritesFile:
    def test_install_skill_writes_file(self, tmp_path: Path) -> None:
        """install_skill() creates SKILL.md and returns (path, True) on first write."""
        path, changed = install_skill(skills_root=tmp_path, version="1.2.3")

        expected = tmp_path / "alc" / "SKILL.md"
        assert path == expected
        assert changed is True
        assert expected.is_file()

        content = expected.read_text()
        assert "name: alc" in content
        assert "1.2.3" in content
        # Description must reference the CLI purpose.
        assert ".alc/" in content
        assert "alc" in content


class TestInstallSkillIdempotent:
    def test_install_skill_idempotent(self, tmp_path: Path) -> None:
        """Second call with identical args returns (path, False) and leaves file unchanged."""
        path1, changed1 = install_skill(skills_root=tmp_path, version="1.2.3")
        assert changed1 is True

        content_before = path1.read_text()

        path2, changed2 = install_skill(skills_root=tmp_path, version="1.2.3")
        assert changed2 is False
        assert path2 == path1
        assert path2.read_text() == content_before


class TestInstallSkillDefaultRootUsesHome:
    def test_install_skill_default_root_uses_home(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """install_skill() without skills_root defaults to <home>/.claude/skills."""
        monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))

        path, changed = install_skill(version="9.9.9")

        expected = tmp_path / ".claude" / "skills" / "alc" / "SKILL.md"
        assert path == expected
        assert changed is True
        assert expected.is_file()
        assert "9.9.9" in expected.read_text()


class TestRenderSkillContainsCliSurface:
    def test_render_skill_contains_cli_surface(self) -> None:
        """render_skill() output mentions every CLI command in the ALC surface."""
        text = render_skill("0.0.0")

        assert "alc run" in text
        assert "alc flow" in text
        assert "alc conduct" in text
        assert "alc specialist" in text
        assert "alc tick" in text
