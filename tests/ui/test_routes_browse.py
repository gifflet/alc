"""The /api/fs/browse endpoint."""

from __future__ import annotations


def test_lists_directories_for_a_path(client, tmp_path):
    (tmp_path / "child").mkdir()
    (tmp_path / "note.txt").write_text("x")

    body = client.get("/api/fs/browse", params={"path": str(tmp_path)}).json()

    assert body["path"] == str(tmp_path.resolve())
    assert [e["name"] for e in body["entries"]] == ["child"]


def test_flags_alc_projects(client, tmp_path):
    (tmp_path / "proj" / ".alc").mkdir(parents=True)

    body = client.get("/api/fs/browse", params={"path": str(tmp_path)}).json()

    assert body["entries"][0]["is_alc_project"] is True


def test_hidden_directories_require_opting_in(client, tmp_path):
    (tmp_path / ".secret").mkdir()

    default = client.get("/api/fs/browse", params={"path": str(tmp_path)}).json()
    assert default["entries"] == []

    shown = client.get(
        "/api/fs/browse", params={"path": str(tmp_path), "show_hidden": "true"}
    ).json()
    assert [e["name"] for e in shown["entries"]] == [".secret"]


def test_missing_directory_is_404(client, tmp_path):
    response = client.get("/api/fs/browse", params={"path": str(tmp_path / "gone")})
    assert response.status_code == 404


def test_a_file_is_400(client, tmp_path):
    target = tmp_path / "f.txt"
    target.write_text("x")

    assert client.get("/api/fs/browse", params={"path": str(target)}).status_code == 400
