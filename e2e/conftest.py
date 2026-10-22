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
