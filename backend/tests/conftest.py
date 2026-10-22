"""Test fixtures: a dedicated PostgreSQL database migrated with Alembic, truncated between tests.

Run inside Docker: ``docker compose -f compose.test.yaml run --rm backend-tests``.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, text

ADMIN_URL = os.environ.get(
    "ALMLIGHT_TEST_DATABASE_ADMIN_URL", "postgresql+psycopg://almlight:almlight@localhost:5432/almlight"
)
TEST_DB = "almlight_test"
TEST_URL = ADMIN_URL.rsplit("/", 1)[0] + f"/{TEST_DB}"
ADMIN_PASSWORD = "admin-test-password"

os.environ["ALMLIGHT_DATABASE_URL"] = TEST_URL
os.environ["ALMLIGHT_ADMIN_PASSWORD"] = ADMIN_PASSWORD
os.environ.setdefault("ALMLIGHT_DATA_DIR", "/tmp/almlight-test-data")
os.environ["ALMLIGHT_OUTBOX_WORKER"] = "false"
os.environ["ALMLIGHT_DEMO_DATA"] = "false"
os.environ["ALMLIGHT_STATIC_DIR"] = "/nonexistent"


def _create_database() -> None:
    engine = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
    with engine.connect() as conn:
        conn.execute(text(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)"))
        conn.execute(text(f"CREATE DATABASE {TEST_DB}"))
    engine.dispose()


@pytest.fixture(scope="session")
def app():
    _create_database()
    from alembic import command
    from alembic.config import Config

    cfg = Config(os.path.join(os.path.dirname(__file__), "..", "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(os.path.dirname(__file__), "..", "migrations"))
    command.upgrade(cfg, "head")
    from almlight.main import create_app

    return create_app()


@pytest.fixture(autouse=True)
def clean_db(app) -> Iterator[None]:
    from almlight.core.db import get_engine, session_factory
    from almlight.models import Base
    from almlight.modules.identity.service import ensure_bootstrap_admin

    tables = ", ".join(t.name for t in Base.metadata.sorted_tables)
    with get_engine().begin() as conn:
        conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    with session_factory()() as db:
        ensure_bootstrap_admin(db)
    yield


@pytest.fixture
def db():
    from almlight.core.db import session_factory

    with session_factory()() as session:
        yield session


class Api:
    """Thin wrapper around TestClient that asserts status codes and returns JSON."""

    def __init__(self, client):
        self.c = client

    def _call(self, method: str, url: str, expect: int | tuple[int, ...] | None, **kw):
        resp = self.c.request(method, "/api/v1" + url, **kw)
        expected = (expect,) if isinstance(expect, int) else expect
        if expected is not None:
            assert resp.status_code in expected, f"{method} {url} -> {resp.status_code}: {resp.text}"
        ctype = resp.headers.get("content-type", "")
        return resp.json() if ctype.startswith("application/json") else resp

    def get(self, url, expect=200, **kw):
        return self._call("GET", url, expect, **kw)

    def post(self, url, json=None, expect=(200, 201), **kw):
        return self._call("POST", url, expect, json=json, **kw)

    def patch(self, url, json=None, expect=200, **kw):
        return self._call("PATCH", url, expect, json=json, **kw)

    def put(self, url, json=None, expect=200, **kw):
        return self._call("PUT", url, expect, json=json, **kw)

    def delete(self, url, expect=200, **kw):
        return self._call("DELETE", url, expect, **kw)


def login(app, username: str, password: str) -> Api:
    from fastapi.testclient import TestClient

    client = TestClient(app)
    api = Api(client)
    api.post("/auth/login", {"username": username, "password": password}, expect=200)
    return api


@pytest.fixture
def admin(app) -> Api:
    return login(app, "admin", ADMIN_PASSWORD)


@pytest.fixture
def anon(app) -> Api:
    from fastapi.testclient import TestClient

    return Api(TestClient(app))


@pytest.fixture
def make_user(app, admin):
    def _make(role: str | None = None, project: str | None = None, username: str | None = None) -> tuple[Api, dict]:
        name = username or f"u{uuid.uuid4().hex[:8]}"
        user = admin.post("/users", {"username": name, "display_name": name.title(), "password": "password-123"})
        if project and role:
            admin.put(f"/projects/{project}/members", {"user_id": user["id"], "role": role})
        return login(app, name, "password-123"), user

    return _make


@pytest.fixture
def project(admin) -> str:
    admin.post("/projects", {"key": "PX", "name": "Test Product", "template": "systems_engineering"})
    return "PX"


@pytest.fixture
def team(project, make_user):
    """A project with a contributor, a reviewer and a manager (besides the admin)."""
    contributor, cu = make_user("contributor", project, "carla")
    reviewer, ru = make_user("reviewer", project, "rene")
    manager, mu = make_user("manager", project, "mia")
    viewer, vu = make_user("viewer", project, "vic")
    return {"contributor": contributor, "reviewer": reviewer, "manager": manager, "viewer": viewer,
            "users": {"contributor": cu, "reviewer": ru, "manager": mu, "viewer": vu}}


def new_item(api: Api, project: str, type_: str, title: str, **extra) -> dict:
    return api.post(f"/projects/{project}/items", {"type": type_, "title": title, **extra}, expect=201)


def approve(item_key: str, project: str, requester: Api, approver: Api, transition: str = "approve",
            password: str = "password-123") -> dict:
    """Request an approval transition and approve it with an e-signature."""
    res = requester.post(f"/projects/{project}/items/{item_key}/transitions/{transition}", {})
    assert res["status"] == "approval_requested", res
    return approver.post(f"/projects/{project}/approvals/{res['request_id']}/vote",
                         {"decision": "approve", "password": password})
