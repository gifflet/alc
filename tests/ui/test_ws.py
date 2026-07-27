# test_ws.py — The /ws WebSocket: subscribe, filtered delivery, global messages.
from __future__ import annotations


class TestWebSocket:
    def test_subscribe_ack_and_project_message(self, client, app, registered: str) -> None:
        bus = app.state.bus
        with client.websocket_connect("/ws") as ws:
            ws.send_json({"type": "subscribe", "project_id": registered})
            ack = ws.receive_json()
            assert ack == {"type": "subscribed", "project_id": registered}

            bus.publish({"type": "queue_changed", "project_id": registered})
            message = ws.receive_json()
            assert message["type"] == "queue_changed"
            assert message["project_id"] == registered

    def test_global_message_delivered_without_subscription(
        self, client, app, registered: str
    ) -> None:
        bus = app.state.bus
        with client.websocket_connect("/ws") as ws:
            # Subscribe first purely to synchronise (the ack proves the loop is live).
            ws.send_json({"type": "subscribe", "project_id": registered})
            assert ws.receive_json()["type"] == "subscribed"

            bus.publish({"type": "project_list_changed", "project_id": None})
            message = ws.receive_json()
            assert message["type"] == "project_list_changed"

    def test_unsubscribed_project_message_is_filtered(
        self, client, app, registered: str
    ) -> None:
        bus = app.state.bus
        with client.websocket_connect("/ws") as ws:
            ws.send_json({"type": "subscribe", "project_id": registered})
            assert ws.receive_json()["type"] == "subscribed"

            # A message for another project is dropped; the next global one arrives.
            bus.publish({"type": "queue_changed", "project_id": "someone-else"})
            bus.publish({"type": "project_list_changed", "project_id": None})
            message = ws.receive_json()
            assert message["type"] == "project_list_changed"

    def test_run_event_forwarded(self, client, app, registered: str) -> None:
        bus = app.state.bus
        with client.websocket_connect("/ws") as ws:
            ws.send_json({"type": "subscribe", "project_id": registered})
            assert ws.receive_json()["type"] == "subscribed"

            bus.publish(
                {
                    "type": "run_event",
                    "project_id": registered,
                    "stem": "20250101T000000-run-x-abc123",
                    "event": {"event": "act_started", "attempt": 1},
                }
            )
            message = ws.receive_json()
            assert message["type"] == "run_event"
            assert message["event"]["event"] == "act_started"

    def test_worktree_changed_forwarded_with_status_payload(
        self, client, app, registered: str
    ) -> None:
        # The live repo/working-tree push: the Watcher's RepoStatusTracker
        # publishes this on a debounced change; it must reach a subscribed client
        # verbatim, `status` payload included (the client invalidates on it).
        bus = app.state.bus
        status = {
            "available": True,
            "dirty": True,
            "branch": "main",
            "detached": False,
            "upstream": "origin/main",
            "ahead": 1,
            "behind": 0,
            "untracked": 2,
        }
        with client.websocket_connect("/ws") as ws:
            ws.send_json({"type": "subscribe", "project_id": registered})
            assert ws.receive_json()["type"] == "subscribed"

            bus.publish(
                {"type": "worktree_changed", "project_id": registered, "status": status}
            )
            message = ws.receive_json()
            assert message["type"] == "worktree_changed"
            assert message["project_id"] == registered
            assert message["status"] == status
