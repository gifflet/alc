# test_schedule_api.py — GET /api/schedule: a thin, read-only route over
# schedule.list_entries/has_crontab/read_crontab (ui-phase-5.md Wave 6, T12).
#
# Project-independent (the crontab is host-level, not per-project) so these
# tests never register a project. The crontab itself is FAKE/INJECTED via
# monkeypatch on `alc.ui.service` — never the real host crontab, mirroring
# tests/test_schedule.py's own fake-crontab discipline.
from __future__ import annotations

import pytest


class TestGetSchedule:
    def test_no_crontab_on_this_host_is_an_explicit_empty_result(
        self, client, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("alc.ui.service.has_crontab", lambda: False)

        resp = client.get("/api/schedule")

        assert resp.status_code == 200
        assert resp.json() == {"available": False, "entries": []}

    def test_crontab_with_no_alc_entries_is_available_but_empty(
        self, client, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("alc.ui.service.has_crontab", lambda: True)
        monkeypatch.setattr(
            "alc.ui.service.read_crontab", lambda: ["0 3 * * * /home/me/backup.sh"]
        )

        resp = client.get("/api/schedule")

        assert resp.status_code == 200
        assert resp.json() == {"available": True, "entries": []}

    def test_lists_only_the_alc_scheduled_entries(
        self, client, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        operator_line = "0 3 * * * /home/me/backup.sh"
        tick_entry = "*/15 * * * * cd /proj && /usr/bin/alc tick # alc-schedule:tick"
        cycle_entry = (
            "0 */2 * * * cd /proj && /usr/bin/alc cycle deliver "
            "# alc-schedule:cycle:deliver"
        )
        monkeypatch.setattr("alc.ui.service.has_crontab", lambda: True)
        monkeypatch.setattr(
            "alc.ui.service.read_crontab",
            lambda: [operator_line, tick_entry, cycle_entry],
        )

        resp = client.get("/api/schedule")

        assert resp.status_code == 200
        body = resp.json()
        assert body["available"] is True
        assert body["entries"] == [tick_entry, cycle_entry]
        assert operator_line not in body["entries"]

    def test_never_touches_the_real_crontab(
        self, client, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`read_crontab`/`has_crontab` are never called for real — only the
        injected fakes above are — proven by making the real ones explode."""

        def _boom(*args, **kwargs):
            raise AssertionError("the real crontab must never be touched")

        monkeypatch.setattr("alc.schedule.subprocess.run", _boom)
        monkeypatch.setattr("alc.ui.service.has_crontab", lambda: True)
        monkeypatch.setattr("alc.ui.service.read_crontab", lambda: [])

        resp = client.get("/api/schedule")

        assert resp.status_code == 200
        assert resp.json() == {"available": True, "entries": []}
