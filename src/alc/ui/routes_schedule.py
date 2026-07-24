# routes_schedule.py — Read-only view of the host crontab's ALC-scheduled
# entries (`alc schedule list`). Project-independent: the crontab lives on the
# host, not inside any one project (ui-phase-5.md T12). Installing/removing a
# schedule stays a CLI-only operation — this route never writes.
from __future__ import annotations

from fastapi import APIRouter

from alc.ui import service

router = APIRouter(prefix="/api/schedule", tags=["schedule"])


@router.get("")
def get_schedule() -> dict:
    return service.schedule_status()
