from conftest import ADMIN_PASSWORD, new_item


def test_login_me_logout(admin, anon):
    me = admin.get("/auth/me")
    assert me["username"] == "admin" and me["is_admin"] is True
    anon.post("/auth/login", {"username": "admin", "password": "wrong"}, expect=401)
    anon.post("/auth/login", {"username": "nobody", "password": "x"}, expect=401)
    anon.get("/auth/me", expect=401)
    admin.post("/auth/logout", expect=200)
    admin.get("/auth/me", expect=401)


def test_unknown_api_path_is_json_404(admin):
    body = admin.get("/does-not-exist", expect=404)
    assert body["error"]["code"] == "not_found"


def test_api_token_lifecycle(admin, anon):
    created = admin.post("/auth/tokens", {"name": "ci"}, expect=201)
    token = created["token"]
    assert token.startswith("alm_")
    me = anon.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me["username"] == "admin"
    admin.delete(f"/auth/tokens/{created['id']}")
    anon.get("/auth/me", headers={"Authorization": f"Bearer {token}"}, expect=401)
    anon.get("/auth/me", headers={"Authorization": "Bearer alm_invalid"}, expect=401)


def test_user_administration_requires_admin(make_user, admin):
    api, user = make_user()
    api.get("/users", expect=403)
    api.post("/users", {"username": "x2", "display_name": "X", "password": "password-123"}, expect=403)
    admin.post("/users", {"username": "Bad Name", "display_name": "X", "password": "password-123"}, expect=422)
    admin.post("/users", {"username": "short", "display_name": "X", "password": "123"}, expect=422)
    admin.post("/users", {"username": user["username"], "display_name": "X", "password": "password-123"},
               expect=409)
    admin.patch(f"/users/{user['id']}", {"is_active": False})
    api.get("/auth/me", expect=401)


def test_admin_cannot_lock_themselves_out(admin):
    me = admin.get("/auth/me")
    admin.patch(f"/users/{me['id']}", {"is_admin": False}, expect=422)
    admin.patch(f"/users/{me['id']}", {"is_active": False}, expect=422)


def test_change_password(make_user, app):
    from conftest import login

    api, user = make_user()
    api.post("/auth/password", {"current_password": "wrong", "new_password": "new-password-1"}, expect=401)
    api.post("/auth/password", {"current_password": "password-123", "new_password": "x"}, expect=422)
    api.post("/auth/password", {"current_password": "password-123", "new_password": "new-password-1"})
    login(app, user["username"], "new-password-1")


def test_project_creation_and_validation(admin, make_user):
    tpls = admin.get("/templates")
    assert {t["key"] for t in tpls} >= {"systems_engineering", "lean_requirements"}
    p = admin.post("/projects", {"key": "abc1", "name": "Alpha", "template": "lean_requirements"}, expect=201)
    assert p["key"] == "ABC1" and p["role"] == "manager"
    admin.post("/projects", {"key": "ABC1", "name": "Dup"}, expect=409)
    admin.post("/projects", {"key": "1BAD", "name": "Bad"}, expect=422)
    admin.post("/projects", {"key": "OK2", "name": "X", "template": "nope"}, expect=422)
    user, _ = make_user()
    user.post("/projects", {"key": "NOPE", "name": "X"}, expect=403)


def test_project_access_by_role(team, project, make_user):
    outsider, _ = make_user()
    outsider.get(f"/projects/{project}", expect=404)  # existence is not revealed
    outsider.get(f"/projects/{project}/items", expect=404)
    viewer = team["viewer"]
    assert viewer.get(f"/projects/{project}")["role"] == "viewer"
    viewer.post(f"/projects/{project}/items", {"type": "system_requirement", "title": "X"}, expect=403)
    item = new_item(team["contributor"], project, "system_requirement", "Measure pressure")
    viewer.get(f"/projects/{project}/items/{item['key']}")
    team["contributor"].delete(f"/projects/{project}/items/{item['key']}", expect=403)
    team["contributor"].put(f"/projects/{project}/members",
                            {"user_id": team["users"]["viewer"]["id"], "role": "manager"}, expect=403)
    assert [p["key"] for p in outsider.get("/projects")] == []


def test_last_manager_cannot_be_removed(admin, project):
    me = admin.get("/auth/me")
    admin.delete(f"/projects/{project}/members/{me['id']}", expect=422)


def test_project_stats_and_audit(team, project, admin):
    new_item(team["contributor"], project, "system_requirement", "R1")
    stats = admin.get(f"/projects/{project}/stats")
    assert stats["total_items"] == 1
    log = admin.get(f"/projects/{project}/audit")
    assert any(e["action"] == "item.created" for e in log)
    assert admin.get("/admin/audit/verify")["ok"] is True


def test_bootstrap_admin_password_from_env(anon):
    anon.post("/auth/login", {"username": "admin", "password": ADMIN_PASSWORD}, expect=200)
