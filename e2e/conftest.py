"""Browser E2E tests against a running ALMlight with demo data (see compose.test.yaml)."""

import os
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

BASE_URL = os.environ.get("BASE_URL", "http://localhost:48081")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin-e2e-password")
ARTIFACTS = Path(__file__).parent / "artifacts"
ARTIFACTS.mkdir(exist_ok=True)

expect.set_options(timeout=10_000)


@pytest.fixture(scope="session")
def browser_context_args(browser_context_args):
    return {**browser_context_args, "base_url": BASE_URL, "viewport": {"width": 1440, "height": 900}}


def login(page: Page, username: str, password: str) -> None:
    page.goto("/login")
    page.get_by_test_id("login-username").fill(username)
    page.get_by_test_id("login-password").fill(password)
    page.get_by_test_id("login-submit").click()
    expect(page.get_by_test_id("user-menu")).to_be_visible()


def logout(page: Page) -> None:
    page.get_by_test_id("user-menu").click()
    page.get_by_test_id("logout").click()
    expect(page.get_by_test_id("login-username")).to_be_visible()


def shot(page: Page, name: str) -> None:
    page.screenshot(path=str(ARTIFACTS / f"{name}.png"), full_page=True)


def choose(page: Page, test_id: str, option: str) -> None:
    """Pick an option in a Mantine Select identified by data-testid."""
    page.get_by_test_id(test_id).click()
    page.get_by_role("option", name=option, exact=False).first.click()


def add_filter(page: Page, field: str, *, options: tuple[str, ...] = (), link: str | None = None) -> None:
    """Add a condition with the query builder: the field from the Filter menu, then its values."""
    page.get_by_test_id("qadd").click()
    page.get_by_test_id(f"qfield-{field}").click()
    editor = page.get_by_test_id("qedit")
    for o in options:
        editor.get_by_test_id(f"qopt-{o}").click()
        expect(editor.get_by_test_id(f"qopt-{o}")).to_be_checked()
    if link:
        editor.get_by_text(link, exact=True).click()
    editor.get_by_role("button", name="Done").click()
    expect(editor).to_have_count(0)


def drag(page: Page, source, target, dx: float | None = None) -> None:
    """Pointer drag (dnd-kit and the timeline need real pointer moves): to a target element or by dx pixels."""
    try:
        page.wait_for_load_state("networkidle", timeout=5000)  # no refresh may re-render the board mid-drag
    except Exception:  # noqa: BLE001
        pass
    page.wait_for_timeout(300)
    source.scroll_into_view_if_needed()
    sb = source.bounding_box()
    x0, y0 = sb["x"] + min(30, sb["width"] / 2), sb["y"] + sb["height"] / 2
    page.mouse.move(x0, y0)
    page.mouse.down()
    page.mouse.move(x0 + 8, y0 + 4, steps=4)
    if target is not None:
        tb = target.bounding_box()
        page.mouse.move(tb["x"] + tb["width"] / 2, tb["y"] + min(30, tb["height"] / 2), steps=20)
    else:
        page.mouse.move(x0 + dx, y0, steps=20)
    page.wait_for_timeout(120)
    page.mouse.up()
