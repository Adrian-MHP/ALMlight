"""Live co-editing (Yjs over WebSockets) and the live channel (change events, presence).

The tests speak the real wire protocol with Python Yjs clients (pycrdt) that write the document structure the
browser editor writes (ProseMirror nodes as XML elements, marks as text attributes).
"""

import json
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout

import pytest
from conftest import new_item
from fastapi.testclient import TestClient
from pycrdt import (
    Doc,
    XmlElement,
    XmlFragment,
    XmlText,
    create_sync_message,
    create_update_message,
    handle_sync_message,
)

from almlight.core.config import get_settings
from almlight.modules.collab import protocol as p

_pool = ThreadPoolExecutor(max_workers=8)


class YClient:
    """A minimal y-websocket client."""

    def __init__(self, tc: TestClient, item_id: str, token: str | None, base: str = ""):
        self.doc = Doc()
        self.body = self.doc.get("body", type=XmlFragment)
        self.title = self.doc.get("title", type=XmlFragment)
        query = "&".join(x for x in (f"token={token}" if token else "", f"base={base}" if base else "") if x)
        self._cm = tc.websocket_connect(f"/api/v1/collab/items/{item_id}?{query}")
        self.ws = self._cm.__enter__()
        self.updates: list[bytes] = []
        self.awareness: list[p.AwarenessEntry] = []
        self.close_code: int | None = None
        self.doc.observe(lambda e: self.updates.append(e.update))

    def recv(self, timeout: float = 5.0) -> dict:
        try:
            return _pool.submit(self.ws.receive).result(timeout)
        except FutureTimeout:
            raise AssertionError("no message from the server") from None

    def process(self, msg: dict) -> str:
        if msg["type"] == "websocket.close":
            self.close_code = msg.get("code")
            return "close"
        data = msg.get("bytes")
        if not data:
            return "other"
        if data[0] == p.MSG_SYNC:
            sub = data[1]
            reply = handle_sync_message(data[1:], self.doc)
            if reply is not None:
                self.ws.send_bytes(reply)
            return {p.SYNC_STEP1: "step1", p.SYNC_STEP2: "step2", p.SYNC_UPDATE: "update"}[sub]
        if data[0] == p.MSG_AWARENESS:
            self.awareness.extend(p.parse_awareness(p.Reader(data[1:]).var_bytes()))
            return "awareness"
        return "other"

    def until(self, *kinds: str, timeout: float = 5.0) -> str:
        deadline = time.monotonic() + timeout
        while True:
            kind = self.process(self.recv(max(0.1, deadline - time.monotonic())))
            if kind in kinds or kind == "close":
                return kind

    def handshake(self) -> None:
        assert self.until("step1") == "step1"  # the server asks for our state ...
        self.ws.send_bytes(create_sync_message(self.doc))  # ... and we ask for its state
        assert self.until("step2") == "step2"

    def edit(self, fn) -> None:
        self.updates.clear()
        with self.doc.transaction():
            fn(self)
        for u in self.updates:
            self.ws.send_bytes(create_update_message(u))
        self.updates.clear()

    def html(self) -> str:
        from almlight.modules.collab.serialize import body_html

        return body_html(self.body)

    def close(self) -> None:
        self._cm.__exit__(None, None, None)


def paragraph(c: YClient, text: str, attrs: dict | None = None) -> None:
    para = c.body.children.append(XmlElement("paragraph"))
    t = para.children.append(XmlText())
    t.insert(0, text, attrs)


def _tokens(*apis) -> list[str]:
    return [api.post("/auth/tokens", {"name": f"t{uuid.uuid4().hex[:6]}"}, expect=201)["token"] for api in apis]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def fast_sessions():
    s = get_settings()
    old = (s.collab_leave_grace_seconds, s.collab_draft_save_seconds)
    s.collab_leave_grace_seconds, s.collab_draft_save_seconds = 0.3, 0.2
    yield
    s.collab_leave_grace_seconds, s.collab_draft_save_seconds = old


def test_co_editing_session(app, team, project, fast_sessions):
    c, r, v = team["contributor"], team["reviewer"], team["viewer"]
    item = new_item(c, project, "system_requirement", "Live item", description="")
    tc_, tr, tv = _tokens(c, r, v)
    url = f"/api/v1/projects/{project}/items/{item['key']}"
    with TestClient(app) as tc:
        # Access control and stale start states close the connection with a reason code.
        anon = YClient(tc, item["id"], None)
        assert anon.until("step1") == "close" and anon.close_code == 4401
        stale = YClient(tc, item["id"], tc_, base="0000000000000000")
        assert stale.until("step1") == "close" and stale.close_code == 4409
        missing = YClient(tc, str(uuid.uuid4()), tc_)
        assert missing.until("step1") == "close" and missing.close_code == 4404
        with tc.websocket_connect(f"/api/v1/collab/items/{item['id']}?token={tc_}",
                                  headers={"origin": "https://evil.example"}) as cross:
            closed = _pool.submit(cross.receive).result(5)
            assert closed["type"] == "websocket.close" and closed["code"] == 4401  # cross-site refused

        a = YClient(tc, item["id"], tc_, base=item["content_hash"])
        a.handshake()
        b = YClient(tc, item["id"], tr, base=item["content_hash"])
        b.handshake()
        viewer = YClient(tc, item["id"], tv, base=item["content_hash"])
        viewer.handshake()

        # Concurrent edits are shared instantly and merge.
        a.edit(lambda c_: paragraph(c_, "Hello"))
        assert b.until("update") == "update" and b.html() == "<p>Hello</p>"
        b.edit(lambda c_: c_.body.children[0].children[0].insert(5, " world", {"bold": {}}))
        assert a.until("update") == "update" and a.html() == "<p>Hello<strong> world</strong></p>"

        # Read-only participants cannot change the shared text (their update is not applied or relayed).
        viewer.edit(lambda c_: paragraph(c_, "Viewer was here"))

        # Presence carries the authenticated user, not what the client claims.
        a.ws.send_bytes(p.awareness_message([p.AwarenessEntry(
            a.doc.client_id, 1, json.dumps({"user": {"name": "Mallory"}, "cursor": None}))]))
        assert b.until("awareness") == "awareness"
        state = json.loads(next(e.state for e in b.awareness if e.client_id == a.doc.client_id))
        assert state["user"]["name"] == "Carla" and state["user"]["canWrite"] is True

        status = tc.get(f"{url}/collab", headers=_auth(tr)).json()
        assert status["active"] and status["dirty"] and len(status["participants"]) == 3

        # Explicit save: a new version with the shared text, recording who contributed.
        saved = tc.post(f"{url}/collab/save", headers=_auth(tr)).json()
        assert saved["saved"] is True and saved["version"] == "A.2", saved
        detail = tc.get(url, headers=_auth(tc_)).json()
        assert detail["description"] == "<p>Hello<strong> world</strong></p>"
        latest = tc.get(f"{url}/versions", headers=_auth(tc_)).json()[0]
        assert latest["change_note"] == "Live co-editing with Carla" and latest["created_by"]["display_name"] == "Rene"
        assert tc.post(f"{url}/collab/save", headers=_auth(tr)).json()["saved"] is False  # nothing new

        # A change from elsewhere restarts the session from the new text.
        res = tc.patch(url, json={"description": "Changed in the form", "expected_version": 2}, headers=_auth(tc_))
        assert res.status_code == 200
        for client in (a, b, viewer):
            assert client.until("never") == "close" and client.close_code == 4001
        for client in (a, b, viewer, anon, stale, missing):
            client.close()


def test_session_saved_when_last_editor_leaves(app, team, project, fast_sessions):
    c = team["contributor"]
    item = new_item(c, project, "system_requirement", "Leave me", description="Old")
    (tok,) = _tokens(c)
    url = f"/api/v1/projects/{project}/items/{item['key']}"
    with TestClient(app) as tc:
        a = YClient(tc, item["id"], tok, base=item["content_hash"])
        a.handshake()
        a.edit(lambda c_: paragraph(c_, "Written live"))
        a.close()
        for _ in range(50):
            detail = tc.get(url, headers=_auth(tok)).json()
            if detail["version"] == "A.2":
                break
            time.sleep(0.1)
        assert detail["version"] == "A.2" and detail["description"] == "<p>Written live</p>"
        note = tc.get(f"{url}/versions", headers=_auth(tok)).json()[0]["change_note"]
        assert note == "Live co-editing (saved when the session ended)"
        assert tc.get(f"{url}/collab", headers=_auth(tok)).json()["active"] is False


def test_transition_saves_session_first_and_freezes_it(app, team, project, fast_sessions):
    c = team["contributor"]
    item = new_item(c, project, "system_requirement", "Review me", description="")
    (tok,) = _tokens(c)
    url = f"/api/v1/projects/{project}/items/{item['key']}"
    with TestClient(app) as tc:
        a = YClient(tc, item["id"], tok, base=item["content_hash"])
        a.handshake()
        a.edit(lambda c_: paragraph(c_, "Final wording"))
        time.sleep(0.1)
        res = tc.post(f"{url}/transitions/submit", json={}, headers=_auth(tok))
        assert res.status_code == 200, res.text
        detail = tc.get(url, headers=_auth(tok)).json()
        # the reviewed version contains the live edits
        assert detail["lifecycle"]["state"] == "in_review" and detail["description"] == "<p>Final wording</p>"
        assert a.until("never") == "close" and a.close_code == 4001
        a.close()
        again = YClient(tc, item["id"], tok, base=detail["content_hash"])
        again.handshake()
        again.edit(lambda c_: paragraph(c_, "Sneaky change"))  # frozen: read-only connection
        time.sleep(0.2)
        assert tc.get(f"{url}/collab", headers=_auth(tok)).json()["dirty"] is False
        again.close()


def test_drafts_survive_a_restart(team, project, db):
    from almlight.core.richtext import content_hash
    from almlight.modules.collab.models import CollabDraft
    from almlight.modules.collab.rooms import recover_drafts

    c = team["contributor"]
    item = new_item(c, project, "system_requirement", "Crash test", description="Before")
    doc = Doc()
    body = doc.get("body", type=XmlFragment)
    doc.get("title", type=XmlFragment)
    with doc.transaction():
        para = body.children.append(XmlElement("paragraph"))
        para.children.append(XmlText()).insert(0, "Typed before the crash")
    db.add(CollabDraft(item_id=uuid.UUID(item["id"]), project_id=db.execute(
        __import__("sqlalchemy").text("SELECT id FROM projects WHERE key = :k"), {"k": project}).scalar(),
        base_hash=content_hash(item["title"], item["description"]), state=doc.get_update(),
        contributors={team["users"]["contributor"]["id"]: 3}))
    db.commit()
    assert recover_drafts() == 1
    detail = c.get(f"/projects/{project}/items/{item['key']}")
    assert detail["description"] == "<p>Typed before the crash</p>" and detail["version"] == "A.2"
    assert c.get(f"/projects/{project}/items/{item['key']}/versions")[0]["change_note"] == (
        "Live co-editing (recovered after a server restart)")


def test_live_channel_presence_and_changes(app, team, project):
    c, r = team["contributor"], team["reviewer"]
    spec = new_item(c, project, "specification", "Spec")
    tc_, tr = _tokens(c, r)
    with TestClient(app) as tc, tc.websocket_connect(f"/api/v1/live?token={tc_}") as wa, \
                tc.websocket_connect(f"/api/v1/live?token={tr}") as wb:
        wa.send_text(json.dumps({"type": "presence", "project": project, "doc": spec["key"]}))
        wb.send_text(json.dumps({"type": "presence", "project": project, "doc": spec["key"],
                                 "editing": "SYS-1"}))

        def next_msg(ws, pred, n=20):
            for _ in range(n):
                m = json.loads(_pool.submit(ws.receive_text).result(5))
                if pred(m):
                    return m
            raise AssertionError("expected message not received")

        pres = next_msg(wa, lambda m: m["type"] == "presence" and len(m["users"]) == 2)
        names = {u["name"]: u for u in pres["users"]}
        assert names["Rene"]["editing"] == "SYS-1" and names["Carla"]["doc"] == spec["key"]
        res = tc.patch(f"/api/v1/projects/{project}/items/{spec['key']}", json={"title": "Spec v2"},
                       headers=_auth(tc_))
        assert res.status_code == 200
        change = next_msg(wb, lambda m: m["type"] == "change")
        assert change["action"] == "item.updated" and change["project"] == project and change["actor"] == "carla"
        wb.send_text(json.dumps({"type": "subscribe", "project": "NOPE"}))
        assert next_msg(wb, lambda m: m["type"] == "error")["message"].startswith("Project NOPE")
