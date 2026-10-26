"""Hardening for the public deployment: sign-in protection (limit, audit, no user-name oracle), single-sign-on user
names in any case, concurrent changes of one item (clean conflict) and unexpected faults answered as JSON."""

import asyncio
import threading
import time

import pytest
from conftest import ADMIN_PASSWORD, Api, login, new_item
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import DBAPIError, IntegrityError

from almlight.core import ratelimit
from almlight.core.config import get_settings
from almlight.core.errors import Conflict
from almlight.core.ratelimit import FailureLimiter


def _client(app) -> tuple[TestClient, Api]:
    client = TestClient(app)
    return client, Api(client)


def test_failed_sign_ins_are_limited_audited_and_do_not_reveal_user_names(app, make_user, monkeypatch, db):
    monkeypatch.setattr(get_settings(), "login_max_failures", 3)
    make_user(username="lena")
    client, api = _client(app)
    for _ in range(3):
        err = api.post("/auth/login", {"username": "lena", "password": "wrong-password"}, expect=401)
        assert err["error"]["message"] == "Invalid username or password"
    # the fourth attempt is refused before the password is looked at — also with the right password
    blocked = api.post("/auth/login", {"username": "Lena", "password": "password-123"}, expect=429)
    assert blocked["error"]["code"] == "too_many_requests" and "minute" in blocked["error"]["message"]
    resp = client.post("/api/v1/auth/login", json={"username": "lena", "password": "password-123"})
    assert resp.status_code == 429 and 0 < int(resp.headers["retry-after"]) <= 15 * 60 + 1
    german = client.post("/api/v1/auth/login", json={"username": "lena", "password": "x"},
                         headers={"Accept-Language": "de"}).json()
    assert "Anmeldeversuche" in german["error"]["message"]
    # other users are not affected; guessed names are blocked exactly like real ones
    login(app, "admin", ADMIN_PASSWORD)
    for _ in range(3):
        api.post("/auth/login", {"username": "nobody", "password": "guess"}, expect=401)
    assert api.post("/auth/login", {"username": "nobody", "password": "guess"}, expect=429)["error"]["code"] == \
        "too_many_requests"
    # the audit trail records failures of existing users and the block, not guessed names; the chain stays valid
    from almlight.modules.audit import service as audit
    from almlight.modules.audit.models import AuditEntry

    rows = db.execute(select(AuditEntry.action, AuditEntry.actor_name, AuditEntry.summary)
                      .where(AuditEntry.action.like("user.login_%")).order_by(AuditEntry.id)).all()
    assert [(r.action, r.actor_name) for r in rows] == [("user.login_failed", "lena")] * 3 + \
        [("user.login_blocked", "lena")]
    assert audit.verify_chain(db)["ok"]


def test_failures_per_client_address_and_reset_by_success(app, make_user, monkeypatch):
    monkeypatch.setattr(get_settings(), "login_max_failures", 1)  # per address: three times as many
    _, api = _client(app)
    for name in ("a1", "a2", "a3"):
        api.post("/auth/login", {"username": name, "password": "guess"}, expect=401)
    api.post("/auth/login", {"username": "a4", "password": "guess"}, expect=429)
    monkeypatch.setattr(get_settings(), "login_max_failures", 3)
    ratelimit.login_failures.reset()
    make_user(username="mona")
    _, api = _client(app)
    for _ in range(2):  # a success clears the counter of the user name
        api.post("/auth/login", {"username": "mona", "password": "wrong"}, expect=401)
        api.post("/auth/login", {"username": "mona", "password": "password-123"}, expect=200)
    for _ in range(2):
        api.post("/auth/login", {"username": "mona", "password": "wrong"}, expect=401)
    api.post("/auth/login", {"username": "mona", "password": "password-123"}, expect=200)


def test_guessing_the_current_password_is_limited(admin, monkeypatch):
    monkeypatch.setattr(get_settings(), "login_max_failures", 3)
    body = {"current_password": "not-it", "new_password": "another-password-1"}
    for _ in range(3):
        admin.post("/auth/password", body, expect=401)
    admin.post("/auth/password", {**body, "current_password": ADMIN_PASSWORD}, expect=429)


def test_limiter_window_expires_and_memory_is_bounded(monkeypatch):
    now = [0.0]
    limiter = FailureLimiter(clock=lambda: now[0])
    for _ in range(3):
        limiter.record("k", 60)
    assert 0 < limiter.retry_after("k", 3, 60) <= 61
    now[0] = 59
    assert limiter.retry_after("k", 3, 60) == 2
    now[0] = 61
    assert limiter.retry_after("k", 3, 60) == 0  # the failures have aged out
    assert limiter.retry_after("k", 0, 60) == 0  # a limit of 0 switches the protection off
    monkeypatch.setattr(ratelimit, "MAX_KEYS", 10)
    for n in range(40):
        limiter.record(f"guess-{n}", 60)
        now[0] += 0.1
    assert len(limiter._hits) <= 10


def test_single_sign_on_user_names_are_case_insensitive(db):
    from almlight.modules.identity import oidc
    from almlight.modules.identity.models import User

    first = oidc.provision(db, {"preferred_username": "Max.Mustermann@MHP.com", "name": "Max Mustermann"})
    assert first.username == "max.mustermann@mhp.com"
    again = oidc.provision(db, {"preferred_username": "MAX.MUSTERMANN@mhp.com", "name": "Max M."})
    assert again.id == first.id and again.display_name == "Max M."
    legacy = User(username="Erika.Muster@mhp.com", display_name="Erika", password_hash="x", auth_provider="oidc")
    db.add(legacy)
    db.commit()  # created before user names were lower-cased
    assert oidc.provision(db, {"preferred_username": "erika.muster@mhp.com"}).id == legacy.id
    assert db.execute(select(func.count()).select_from(User).where(
        func.lower(User.username).in_(["max.mustermann@mhp.com", "erika.muster@mhp.com"]))).scalar() == 2


def test_concurrent_changes_of_one_item_end_in_a_clean_conflict(team, project):
    """Two people save the same version at once: one saves, the other gets a conflict (409), not a database error."""
    from almlight.core.db import session_factory
    from almlight.modules.identity.models import User
    from almlight.modules.items import service
    from almlight.modules.projects.models import Project

    c = team["contributor"]
    key = new_item(c, project, "system_requirement", "Measuring range")["key"]
    version = c.get(f"/projects/{project}/items/{key}")["version_no"]
    outcome: list = []
    loaded = threading.Event()

    def load(session):
        proj = session.execute(select(Project).where(Project.key == project)).scalar_one()
        user = session.execute(select(User).where(User.username == "carla")).scalar_one()
        return proj, user, service.get_item(session, proj, key)

    def second():
        with session_factory()() as s2:
            proj, user, item = load(s2)  # still sees the old version: the first change is not committed yet
            loaded.set()
            try:
                service.update_item(s2, proj, user, item, service.ContentChange(title="Second"),
                                    expected_version=version)
                s2.commit()
                outcome.append("saved")
            except Exception as exc:  # noqa: BLE001
                outcome.append(exc)

    with session_factory()() as s1:
        proj, user, item = load(s1)
        service.update_item(s1, proj, user, item, service.ContentChange(title="First"), expected_version=version)
        thread = threading.Thread(target=second)
        thread.start()
        assert loaded.wait(10)
        time.sleep(0.5)  # the second change now waits for the item's row lock
        s1.commit()
    thread.join(20)
    assert len(outcome) == 1 and isinstance(outcome[0], Conflict), outcome
    current = c.get(f"/projects/{project}/items/{key}")
    assert current["title"] == "First" and current["version_no"] == version + 1


def test_database_conflicts_answer_409_and_unexpected_faults_answer_json(app, db):
    from almlight.core.db import get_db
    from almlight.modules.identity.models import User

    db.add(User(username="dup", display_name="D", password_hash="x"))
    db.commit()
    db.add(User(username="dup", display_name="D", password_hash="x"))
    with pytest.raises(IntegrityError) as raised:
        db.commit()
    db.rollback()
    handler = app.exception_handlers[DBAPIError]
    from starlette.requests import Request

    request = Request({"type": "http", "method": "GET", "path": "/", "headers": [(b"accept-language", b"de")]})
    response = asyncio.run(handler(request, raised.value))
    assert response.status_code == 409 and b'"conflict"' in response.body and b"gleichzeitig" in response.body
    with pytest.raises(DBAPIError):  # other database errors are real faults: they go on to the generic handler
        asyncio.run(handler(request, DBAPIError("SELECT 1", {}, Exception("disk full"))))

    def broken():
        raise RuntimeError("boom")
        yield  # pragma: no cover

    app.dependency_overrides[get_db] = broken
    try:
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/api/v1/projects", headers={"Accept-Language": "de"})
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 500 and resp.headers["content-type"].startswith("application/json")
    assert resp.json()["error"] == {"code": "internal_error", "message": "Interner Serverfehler", "details": {}}
    assert resp.headers["cache-control"] == "no-store"
