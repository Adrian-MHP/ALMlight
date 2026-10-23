"""Smoke test: every page and tab loads without JavaScript exceptions or server errors (roles, themes, phone)."""

import re

from playwright.sync_api import Browser, Page

from conftest import BASE_URL, login

DEMO_PW = "demo1234"
EXPECTED_404 = (re.compile(r"/api/v1/projects/NOPE"), re.compile(r"/document\?baseline="), re.compile(r"/compare-documents"))


def _watch(page: Page, problems: list[str]) -> None:
    page.on("pageerror", lambda e: problems.append(f"{page.url}: JS error {e}"))

    def on_response(r):
        if r.status >= 500 or (r.status >= 400 and r.url.startswith(BASE_URL + "/api/") and not any(p.search(r.url) for p in EXPECTED_404)):
            problems.append(f"{page.url}: HTTP {r.status} {r.url}")

    page.on("response", on_response)


def _settle(page: Page) -> None:
    try:
        page.wait_for_load_state("networkidle", timeout=6000)
    except Exception:  # noqa: BLE001 — long-polling free app; a slow page still gets checked below
        pass


def test_all_pages_and_tabs_load_cleanly(page: Page, browser: Browser):
    problems: list[str] = []
    _watch(page, problems)
    login(page, "max", DEMO_PW)
    routes = ["/", "/projects", "/approvals", "/search?q=pressure", "/account", "/p/DEMO", "/p/DEMO/items",
              "/p/DEMO/items/SYS-1", "/p/DEMO/items/SE-1", "/p/DEMO/items/TR-1", "/p/DEMO/items/CO-1",
              "/p/DEMO/documents", "/p/DEMO/documents/SPEC-2", "/p/DEMO/structure", "/p/DEMO/traceability",
              "/p/DEMO/changes", "/p/DEMO/verification", "/p/DEMO/variants", "/p/DEMO/baselines", "/p/DEMO/reports",
              "/p/DEMO/activity", "/p/DEMO/settings", "/p/DEMO/risks", "/p/DEMO/plans", "/p/DEMO/plans?release=REL-1",
              "/p/DEMO/structure?view=bom", "/p/DEMO/items/RSK-1", "/p/DEMO/items/REL-1", "/p/DEMO/items/TC-5",
              "/p/DEMO/items/SE-5", "/p/DEMO/boards", "/p/DEMO/timeline", "/p/DEMO/timesheet", "/p/DEMO/items/TSK-2",
              "/p/NOPE", "/no-such-page"]
    for route in routes:
        page.goto(route)
        _settle(page)
        for tab in page.locator("main").get_by_role("tab").all():
            tab.click()
            _settle(page)
    page.goto("/p/DEMO/timeline")
    page.get_by_test_id("tl-view").get_by_text("Resources").click()
    _settle(page)
    for scheme, viewport, lang in (("dark", {"width": 1440, "height": 900}, "en-US"),
                                   ("light", {"width": 390, "height": 844}, "de-DE")):  # the phone pass runs in German
        ctx = browser.new_context(base_url=BASE_URL, viewport=viewport, color_scheme=scheme, locale=lang)
        other = ctx.new_page()
        _watch(other, problems)
        login(other, "alex", DEMO_PW)
        for route in ("/", "/p/DEMO/items/SYS-5", "/p/DEMO/documents/SPEC-2", "/p/DEMO/reports", "/p/DEMO/risks",
                      "/p/DEMO/plans?release=REL-1", "/p/DEMO/structure?view=bom", "/p/DEMO/boards", "/p/DEMO/timeline",
                      "/p/DEMO/timesheet", "/p/DEMO/items/TSK-2?tab=time"):
            other.goto(route)
            _settle(other)
        other.goto("/p/DEMO/timeline")
        other.get_by_test_id("tl-view").locator("label").nth(1).click()  # Resources / Ressourcen
        _settle(other)
        ctx.close()
    assert not problems, "\n".join(problems)
