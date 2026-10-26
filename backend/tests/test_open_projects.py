"""Projects open to every signed-in user (example projects, company-wide read access) and the demo dataset for a
server that others can reach: demo users that cannot sign in, the open role, a demo repository that survives a
restart."""

import io
import shutil

import pytest
from conftest import login, new_item
from PIL import Image
from sqlalchemy import func, select

from almlight.core.config import Settings, get_settings


def _png() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (8, 8), (30, 80, 120)).save(out, "PNG")
    return out.getvalue()


def test_open_role_gives_every_signed_in_user_access(team, project, make_user, db):
    manager, contributor, viewer = team["manager"], team["contributor"], team["viewer"]
    outsider, _ = make_user()
    item = new_item(contributor, project, "system_requirement", "Open for everyone")["key"]
    up = contributor.post(f"/projects/{project}/images", files={"file": ("a.png", io.BytesIO(_png()), "image/png")})
    image = up["url"].removeprefix("/api/v1")

    # members only: the project does not exist for outsiders
    outsider.get(f"/projects/{project}", expect=404)
    assert project not in [p["key"] for p in outsider.get("/projects")]
    assert project not in outsider.get("/auth/me")["projects"]
    outsider.get(image, expect=404)

    # a role for everyone: viewers read, contributors write; it needs a manager and one of three roles
    contributor.patch(f"/projects/{project}", {"open_role": "viewer"}, expect=403)
    manager.patch(f"/projects/{project}", {"open_role": "manager"}, expect=422)
    shown = manager.patch(f"/projects/{project}", {"open_role": "viewer"})
    assert shown["open_role"] == "viewer"
    assert outsider.get(f"/projects/{project}")["role"] == "viewer"
    assert project in [p["key"] for p in outsider.get("/projects")]
    assert outsider.get("/auth/me")["projects"][project] == "viewer"
    assert outsider.get(f"/projects/{project}/items/{item}")["title"] == "Open for everyone"
    assert any(r["key"] == item for r in outsider.get("/search?q=Open%20for%20everyone"))
    outsider.get(image)  # images of an open project can be read
    outsider.post(f"/projects/{project}/items", {"type": "system_requirement", "title": "No"}, expect=403)

    # other settings do not touch it; the higher of membership and open role counts
    assert manager.patch(f"/projects/{project}", {"name": "Renamed"})["open_role"] == "viewer"
    manager.patch(f"/projects/{project}", {"open_role": "contributor"})
    new_item(outsider, project, "system_requirement", "Written by an outsider")
    assert viewer.get(f"/projects/{project}")["role"] == "contributor"  # member viewer, open contributor
    assert contributor.get(f"/projects/{project}")["role"] == "contributor"
    manager.patch(f"/projects/{project}", {"open_role": "viewer"})
    assert contributor.get(f"/projects/{project}")["role"] == "contributor"  # members keep what they have
    assert viewer.get(f"/projects/{project}")["role"] == "viewer"

    # members only again
    assert manager.patch(f"/projects/{project}", {"open_role": None})["open_role"] is None
    outsider.get(f"/projects/{project}", expect=404)
    assert project not in outsider.get("/auth/me")["projects"]
    from almlight.modules.audit.models import AuditEntry

    changes = db.execute(select(AuditEntry.summary).where(AuditEntry.action == "project.open_role")
                         .order_by(AuditEntry.id)).scalars().all()
    assert changes[0].endswith("role viewer in PX") and changes[-1] == "PX is open to members only"


def test_open_role_setting_is_validated_from_the_environment():
    assert Settings(demo_open_role=" Contributor ").demo_open_role == "contributor"
    assert Settings(demo_open_role="").demo_open_role is None and Settings(demo_open_role="none").demo_open_role is None
    with pytest.raises(ValueError):
        Settings(demo_open_role="manager")


def test_demo_project_for_a_server_others_can_reach(db, admin, anon, make_user, monkeypatch):
    from almlight.seed.demo import seed_demo

    settings = get_settings()
    monkeypatch.setattr(settings, "demo_sign_in", False)
    monkeypatch.setattr(settings, "demo_open_role", "contributor")
    seed_demo(db)  # the approvals inside need the (unknown) demo password: they must still work
    for name in ("alex", "rita", "max"):  # nobody can sign in as a demo user
        anon.post("/auth/login", {"username": name, "password": "demo1234"}, expect=401)
    assert admin.get("/projects/DEMO")["open_role"] == "contributor"
    assert admin.get("/projects/DEMO/stats")["total_items"] > 50
    colleague, _ = make_user()  # a colleague who has just signed in for the first time
    mine = colleague.get("/projects/DEMO")
    assert mine["role"] == "contributor" and "DEMO" in colleague.get("/auth/me")["projects"]
    assert colleague.get("/projects/DEMO/items?limit=5")["total"] > 50
    new_item(colleague, "DEMO", "system_requirement", "Added by a colleague")
    members = {m["username"]: m["role"] for m in admin.get("/projects/DEMO/members")}
    assert members == {"admin": "manager", "alex": "contributor", "rita": "reviewer", "max": "manager"}
    repo = colleague.get("/projects/DEMO/repositories")[0]
    assert repo["name"] == "sensor-firmware" and repo["last_error"] is None and repo["commit_count"] >= 9


def test_demo_users_sign_in_by_default_and_the_project_is_closed(db, admin, anon, make_user):
    from almlight.seed.demo import seed_demo

    seed_demo(db)
    login(anon.c.app, "alex", "demo1234")  # unchanged for local use and the tests
    assert admin.get("/projects/DEMO")["open_role"] is None
    outsider, _ = make_user()
    outsider.get("/projects/DEMO", expect=404)


def test_demo_repository_is_written_again_after_a_restart(db, admin):
    """The demo repository lives below the data directory; when that is gone (container restart) it is written again
    with the same commit hashes, so the commits already indexed stay valid and the repository does not fail."""
    from almlight.modules.vcs import service as vcs
    from almlight.modules.vcs.models import RepoCommit, Repository
    from almlight.seed.demo import seed_demo
    from almlight.seed.demo_repo import _repository_path, ensure_firmware_repository

    seed_demo(db)
    repo = db.execute(select(Repository).where(Repository.name == "sensor-firmware")).scalar_one()
    shas = set(db.execute(select(RepoCommit.sha).where(RepoCommit.repository_id == repo.id)).scalars())
    assert len(shas) >= 9 and repo.meta["demo_seed"]["keys"]
    local, mirror = _repository_path("DEMO"), vcs.mirror_path(repo)
    ensure_firmware_repository(db)  # nothing to do while the repository exists
    assert local.exists()
    shutil.rmtree(local)
    shutil.rmtree(mirror)  # the container is new: both are gone
    assert vcs.sync(db, repo)["ok"] is False
    db.commit()
    ensure_firmware_repository(db)
    db.refresh(repo)
    assert local.exists() and repo.last_error is None
    again = set(db.execute(select(RepoCommit.sha).where(RepoCommit.repository_id == repo.id)).scalars())
    assert again == shas, "the rebuilt repository has other commit hashes"
    assert db.execute(select(func.count()).select_from(RepoCommit).where(RepoCommit.repository_id == repo.id)
                      ).scalar() == len(shas)
    assert admin.get(f"/projects/DEMO/repositories/{repo.id}/commits?limit=3")["total"] == len(shas)
