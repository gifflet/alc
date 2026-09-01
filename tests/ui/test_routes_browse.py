"""The /api/fs/browse endpoint."""

from __future__ import annotations


def test_lists_directories_for_a_path(client, tmp_path):
    (tmp_path / "child").mkdir()
    (tmp_path / "note.txt").write_text("x")

    body = client.get("/api/fs/browse", params={"path": str(tmp_path)}).json()

    assert body["path"] == str(tmp_path.resolve())
    assert [e["name"] for e in body["entries"]] == ["child"]


def test_flags_alc_projects(client, tmp_path):
    # The MANIFEST is the test, matching what the registry enforces — a bare
    # `.alc/` directory made ~/.alc (the tool's own global state) read as a
    # project and the browser offered $HOME for registration.
    (tmp_path / "proj" / ".alc").mkdir(parents=True)
    (tmp_path / "proj" / ".alc" / "manifest.yaml").write_text("version: 1\n")

    body = client.get("/api/fs/browse", params={"path": str(tmp_path)}).json()

    assert body["entries"][0]["is_alc_project"] is True


def test_a_bare_dot_alc_directory_is_not_a_project(client, tmp_path):
    (tmp_path / "home" / ".alc" / "ui").mkdir(parents=True)

    body = client.get("/api/fs/browse", params={"path": str(tmp_path / "home")}).json()

    assert body["is_alc_project"] is False


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


def test_clone_refuses_a_url_that_is_really_a_git_option(client, tmp_path):
    """`git clone --upload-pack=<cmd>` runs <cmd>. The endpoint must refuse the
    URL before it ever reaches a subprocess."""
    response = client.post(
        "/api/fs/clone",
        json={"url": "--upload-pack=touch /tmp/pwned", "parent": str(tmp_path)},
    )
    assert response.status_code == 400
    assert "may not start with '-'" in response.json()["detail"]


def test_clone_refuses_an_ext_url(client, tmp_path):
    response = client.post(
        "/api/fs/clone", json={"url": "ext::sh -c id", "parent": str(tmp_path)}
    )
    assert response.status_code == 400


def test_clone_refuses_an_occupied_destination(client, tmp_path):
    taken = tmp_path / "repo"
    taken.mkdir()
    (taken / "file").write_text("x")

    response = client.post(
        "/api/fs/clone",
        json={"url": "https://example.com/o/repo.git", "parent": str(tmp_path)},
    )
    assert response.status_code == 400
    assert "already exists" in response.json()["detail"]


def test_clone_starts_and_returns_an_exec_to_follow(client, tmp_path):
    """A clone can take minutes, so the request returns the exec id rather than
    blocking until git finishes."""
    response = client.post(
        "/api/fs/clone",
        json={"url": "https://example.invalid/o/repo.git", "parent": str(tmp_path)},
    )
    assert response.status_code == 202
    body = response.json()
    assert body["exec_id"]
    assert body["destination"] == str((tmp_path / "repo").resolve())


def test_clone_output_is_global_so_it_reaches_a_client_with_no_project(client, tmp_path):
    """The WebSocket only delivers messages for a subscribed project, plus
    global ones. A clone happens before any project exists, so its exec must be
    global — otherwise the progress reaches nobody."""
    response = client.post(
        "/api/fs/clone",
        json={"url": "https://example.invalid/o/repo.git", "parent": str(tmp_path)},
    )
    exec_id = response.json()["exec_id"]

    listed = {e["id"]: e for e in client.get("/api/execs").json()}
    assert listed[exec_id]["project_id"] is None


def test_new_project_creates_the_directory_and_starts_init(client, tmp_path):
    response = client.post(
        "/api/fs/new-project",
        json={"parent": str(tmp_path), "name": "fresh", "git": False},
    )

    assert response.status_code == 202
    body = response.json()
    assert body["destination"] == str((tmp_path / "fresh").resolve())
    assert (tmp_path / "fresh").is_dir()
    assert body["exec_id"]


def test_new_project_can_make_a_git_repository(client, tmp_path):
    """Isolation, landing and the commit step all need a repository, so a new
    project gets one unless the caller says otherwise."""
    client.post("/api/fs/new-project", json={"parent": str(tmp_path), "name": "repo"})
    assert (tmp_path / "repo" / ".git").is_dir()


def test_new_project_refuses_an_occupied_directory(client, tmp_path):
    taken = tmp_path / "taken"
    taken.mkdir()
    (taken / "file").write_text("x")

    response = client.post(
        "/api/fs/new-project", json={"parent": str(tmp_path), "name": "taken"}
    )
    assert response.status_code == 400


def test_new_project_refuses_a_name_that_escapes_the_parent(client, tmp_path):
    response = client.post(
        "/api/fs/new-project", json={"parent": str(tmp_path), "name": "../escape"}
    )
    assert response.status_code == 400
    # Nothing should have been created outside the parent.
    assert not (tmp_path.parent / "escape").exists()


def test_adopt_scaffolds_alc_into_an_existing_repository(client, tmp_path):
    """The commonest first move is pointing ALC at a repository that already has
    code. The registry refuses it until .alc/ exists, so the UI needs a way to
    create it without sending the user to a terminal."""
    project = tmp_path / "real-work"
    project.mkdir()
    (project / "main.py").write_text("print('code')\n")

    response = client.post("/api/fs/adopt", json={"path": str(project)})

    assert response.status_code == 202
    assert response.json()["destination"] == str(project.resolve())


def test_adopt_refuses_a_directory_that_is_already_a_project(client, tmp_path):
    project = tmp_path / "already"
    (project / ".alc").mkdir(parents=True)
    (project / ".alc" / "manifest.yaml").write_text("version: 1\n")

    response = client.post("/api/fs/adopt", json={"path": str(project)})

    assert response.status_code == 400
    assert "already an ALC project" in response.json()["detail"]


def test_adopt_refuses_a_path_that_is_not_a_directory(client, tmp_path):
    target = tmp_path / "file.txt"
    target.write_text("x")

    assert client.post("/api/fs/adopt", json={"path": str(target)}).status_code == 400
