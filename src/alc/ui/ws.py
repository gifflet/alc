# ws.py — The /ws WebSocket: subscribe per project and receive typed messages.
#
# A client sends {"type": "subscribe", "project_id": ...} (repeatable). The
# server acks with {"type": "subscribed", ...} and thereafter forwards every
# bus message whose project_id the client subscribed to, plus all global
# messages (project_id == None, e.g. project_list_changed).
from __future__ import annotations

import asyncio

from fastapi import FastAPI, WebSocket, WebSocketDisconnect


def register(app: FastAPI) -> None:
    """Attach the /ws endpoint to the app."""

    @app.websocket("/ws")
    async def ws(websocket: WebSocket) -> None:
        await websocket.accept()
        bus = websocket.app.state.bus
        subscribed: set[str] = set()

        with bus.subscribe() as sub:
            recv_task = asyncio.ensure_future(websocket.receive_json())
            get_task = asyncio.ensure_future(sub.get())
            try:
                while True:
                    done, _pending = await asyncio.wait(
                        {recv_task, get_task}, return_when=asyncio.FIRST_COMPLETED
                    )

                    if recv_task in done:
                        try:
                            message = recv_task.result()
                        except WebSocketDisconnect:
                            break
                        if (
                            isinstance(message, dict)
                            and message.get("type") == "subscribe"
                            and message.get("project_id")
                        ):
                            pid = message["project_id"]
                            subscribed.add(pid)
                            await websocket.send_json({"type": "subscribed", "project_id": pid})
                        recv_task = asyncio.ensure_future(websocket.receive_json())

                    if get_task in done:
                        event = get_task.result()
                        pid = event.get("project_id")
                        if pid is None or pid in subscribed:
                            await websocket.send_json(event)
                        get_task = asyncio.ensure_future(sub.get())
            finally:
                recv_task.cancel()
                get_task.cancel()
