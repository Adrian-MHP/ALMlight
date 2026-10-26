"""A manager opens a project to everyone who signs in; a user who is no member then finds it."""

from playwright.sync_api import Page, Playwright, expect

from conftest import ADMIN_PASSWORD, BASE_URL, choose, login, shot

DEMO_PW = "demo1234"


def test_manager_opens_the_project_to_everyone_who_signs_in(page: Page, playwright: Playwright):
    admin = playwright.request.new_context(base_url=BASE_URL)
    assert admin.post("/api/v1/auth/login", data={"username": "admin", "password": ADMIN_PASSWORD}).ok
    assert admin.post("/api/v1/users", data={"username": "gina", "display_name": "Gina Guest",
                                             "password": "gina-password-1"}).ok
    gina = playwright.request.new_context(base_url=BASE_URL)
    assert gina.post("/api/v1/auth/login", data={"username": "gina", "password": "gina-password-1"}).ok
    assert gina.get("/api/v1/projects/DEMO").status == 404  # not a member: the project does not exist for her

    login(page, "max", DEMO_PW)
    page.goto("/p/DEMO/settings")
    card = page.get_by_test_id("open-role-card")
    expect(card).to_contain_text("Everyone who signs in")
    choose(page, "open-role", "Viewer")
    expect(page.get_by_text("Access for all users updated")).to_be_visible()
    shot(page, "74-open-project")
    mine = gina.get("/api/v1/projects").json()
    assert [(p["key"], p["role"]) for p in mine] == [("DEMO", "viewer")]
    assert gina.get("/api/v1/projects/DEMO/items?limit=1").json()["total"] > 10

    choose(page, "open-role", "Members only")
    expect(page.get_by_text("Access for all users updated").last).to_be_visible()
    assert gina.get("/api/v1/projects/DEMO").status == 404
    admin.dispose()
    gina.dispose()
