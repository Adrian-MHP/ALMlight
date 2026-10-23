"""German user interface: switching the language, translated texts and model labels, server messages in German,
the language following the user, and switching back."""

import re

from playwright.sync_api import Page, expect

from conftest import BASE_URL, login, shot

DEMO_PW = "demo1234"


def test_german_user_interface(page: Page):
    login(page, "rita", DEMO_PW)
    try:
        sys1 = page.request.get("/api/v1/projects/DEMO/items?type=system_requirement&limit=1").json()["items"][0]["key"]
        page.goto(f"/p/DEMO/items/{sys1}")
        page.get_by_test_id("user-menu").click()
        page.get_by_test_id("lang-de").click()
        # the page reloads in German: navigation, tabs, model labels (template translations)
        expect(page.get_by_test_id("nav-items")).to_contain_text("Objekte")
        expect(page.get_by_role("tab", name="Übersicht")).to_be_visible()
        expect(page.get_by_role("tab", name="Historie")).to_be_visible()
        expect(page.get_by_text("Systemanforderung").first).to_be_visible()
        assert page.request.get("/api/v1/auth/me").json()["locale"] == "de"
        shot(page, "60-german-item")
        # server messages arrive in German
        page.goto("/p/DEMO/items")
        page.get_by_test_id("qtext-toggle").click()
        page.get_by_test_id("qtext").fill("priority:(must OR")
        page.get_by_test_id("qtext-apply").click()
        expect(page.get_by_test_id("qtext-error")).to_contain_text("Wert erwartet bei")
        # timeline and timesheet
        page.goto("/p/DEMO/timeline")
        expect(page.get_by_test_id("tl-view")).to_contain_text("Ressourcen")
        expect(page.get_by_text(re.compile(r"Terminkonflikt|Kritischer Pfad")).first).to_be_visible()
        page.goto("/p/DEMO/timesheet")
        expect(page.get_by_role("heading", name="Zeiterfassung")).to_be_visible()
        # the language follows the user to a new browser
        other = page.context.browser.new_context(base_url=BASE_URL, locale="en-US")
        p2 = other.new_page()
        login(p2, "rita", DEMO_PW)
        expect(p2.get_by_test_id("nav-projects")).to_contain_text("Alle Projekte")
        other.close()
        # and back to English
        page.get_by_test_id("user-menu").click()
        page.get_by_test_id("lang-en").click()
        expect(page.get_by_role("heading", name="Timesheet")).to_be_visible()
    finally:
        page.request.put("/api/v1/auth/me/locale", data={"locale": None})
