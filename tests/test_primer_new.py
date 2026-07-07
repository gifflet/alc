# test_primer_new.py — Hermetic tests for primer.new_primer().
from __future__ import annotations

from pathlib import Path

import pytest

from alc.primer import new_primer


class TestNewPrimerCreatesFile:
    def test_creates_file_with_template(self, tmp_path: Path) -> None:
        """new_primer() creates the file and returns its path."""
        primers_dir = tmp_path / "primers"
        path = new_primer(primers_dir, "overview")

        assert path == primers_dir / "overview.md"
        assert path.is_file()

    def test_file_contains_title_line(self, tmp_path: Path) -> None:
        """Created file starts with a Markdown title matching the name."""
        primers_dir = tmp_path / "primers"
        new_primer(primers_dir, "my-primer")

        content = (primers_dir / "my-primer.md").read_text()
        assert "# my-primer" in content

    def test_file_contains_where_things_live_section(self, tmp_path: Path) -> None:
        """Created file includes the 'Where things live' placeholder section."""
        primers_dir = tmp_path / "primers"
        new_primer(primers_dir, "arch")

        content = (primers_dir / "arch.md").read_text()
        assert "## Where things live" in content

    def test_file_contains_conventions_section(self, tmp_path: Path) -> None:
        """Created file includes the 'Conventions' placeholder section."""
        primers_dir = tmp_path / "primers"
        new_primer(primers_dir, "arch")

        content = (primers_dir / "arch.md").read_text()
        assert "## Conventions" in content

    def test_mkdir_parents(self, tmp_path: Path) -> None:
        """new_primer() creates nested parent directories automatically."""
        primers_dir = tmp_path / "deep" / "nested" / "primers"
        path = new_primer(primers_dir, "info")

        assert path.is_file()


class TestNewPrimerRefusesExistingWithoutForce:
    def test_raises_file_exists_error(self, tmp_path: Path) -> None:
        """new_primer() raises FileExistsError when the file exists and force is False."""
        primers_dir = tmp_path / "primers"
        new_primer(primers_dir, "existing")

        with pytest.raises(FileExistsError, match="existing"):
            new_primer(primers_dir, "existing")


class TestNewPrimerForceOverwrites:
    def test_force_overwrites_existing_file(self, tmp_path: Path) -> None:
        """new_primer(force=True) replaces the file when it already exists."""
        primers_dir = tmp_path / "primers"
        primers_dir.mkdir(parents=True)
        (primers_dir / "doc.md").write_text("old content")

        path = new_primer(primers_dir, "doc", force=True)

        assert path.is_file()
        content = path.read_text()
        assert "old content" not in content
        assert "## Conventions" in content
