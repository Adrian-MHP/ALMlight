"""The AI assistant in the browser: it answers from the project, and a change it proposes happens only after the
person applies it. The language model is the stub of compose.test.yaml (e2e/llm_stub.py)."""

import uuid

from playwright.sync_api import Page, Playwright, expect

from conftest import ADMIN_PASSWORD, BASE_URL, login, shot

DEMO_PW = "demo1234"
API = "/api/v1/projects/DEMO"


def open_assistant(page: Page):
    page.get_by_test_id("assistant-open").click()
    expect(page.get_by_test_id("assistant-panel")).to_be_visible()


def test_assistant_answers_from_the_project(page: Page):
    login(page, "alex", DEMO_PW)
    page.goto("/p/DEMO")
    open_assistant(page)
    expect(page.get_by_test_id("assistant-panel")).to_contain_text("gpt-test")
    page.get_by_test_id("assistant-input").fill("Wie viele Anforderungen gibt es?")
    page.get_by_test_id("assistant-send").click()
    # the tool ran on the server and the answer carries the number the API reports
    expect(page.get_by_test_id("assistant-tool-search_items")).to_be_visible()
    total = page.request.get(f"{API}/items?type=system_requirement&limit=1").json()["total"]
    expect(page.get_by_test_id("assistant-answer").last).to_contain_text(f"{total} Systemanforderungen")
    shot(page, "76-assistant")


def test_a_proposed_change_needs_the_person(page: Page):
    topic = f"Salzsprühnebel{uuid.uuid4().hex[:6]}"  # unique, so the test can run on a stack that is not fresh
    found = lambda: page.request.get(f"{API}/items?q={topic}").json()  # noqa: E731
    login(page, "alex", DEMO_PW)
    page.goto("/p/DEMO")
    open_assistant(page)
    page.get_by_test_id("assistant-input").fill(f"Lege eine Anforderung {topic} an")
    page.get_by_test_id("assistant-send").click()
    expect(page.get_by_test_id("assistant-proposal")).to_contain_text(topic)
    assert found()["total"] == 0, "nothing may be created before the person applies it"

    page.get_by_test_id("assistant-discard").click()
    expect(page.get_by_test_id("assistant-proposal")).to_have_count(0)
    assert found()["total"] == 0

    page.get_by_test_id("assistant-input").fill(f"Lege eine Anforderung {topic} an")
    page.get_by_test_id("assistant-send").click()
    expect(page.get_by_test_id("assistant-proposal")).to_be_visible()
    shot(page, "77-assistant-proposal")
    page.get_by_test_id("assistant-apply").click()
    expect(page.get_by_test_id("assistant-answer").last).to_contain_text("Angelegt als")
    created = found()["items"]
    assert len(created) == 1 and created[0]["fields"]["priority"] == "should"
    # the item is a normal item with a normal history, written by the person who confirmed
    history = page.request.get(f"{API}/items/{created[0]['key']}/versions").json()
    assert history[-1]["change_note"] == "Created by the assistant"


def test_a_reader_gets_an_assistant_that_cannot_change_anything(page: Page, playwright: Playwright):
    admin = playwright.request.new_context(base_url=BASE_URL)
    assert admin.post("/api/v1/auth/login", data={"username": "admin", "password": ADMIN_PASSWORD}).ok
    created = admin.post("/api/v1/users", data={"username": "lea", "display_name": "Lea Reader",
                                                "password": "reader-password-1"})
    if created.ok:
        admin.put("/api/v1/projects/DEMO/members", data={"user_id": created.json()["id"], "role": "viewer"})
    admin.dispose()

    login(page, "lea", "reader-password-1")
    page.goto("/p/DEMO")
    open_assistant(page)
    panel = page.get_by_test_id("assistant-panel")  # the interface is English here, only the model answers German
    expect(panel).to_contain_text("read only")
    expect(panel).to_contain_text("cannot change anything")
    page.get_by_test_id("assistant-input").fill("Lege eine Anforderung Testlauf an")
    page.get_by_test_id("assistant-send").click()
    expect(page.get_by_test_id("assistant-answer").last).to_be_visible()
    expect(page.get_by_test_id("assistant-proposal")).to_have_count(0)
    assert page.request.get(f"{API}/items?q=Testlauf").json()["total"] == 0


def test_the_model_can_be_chosen_per_conversation(page: Page):
    """Two models are configured in the test stack (a cloud one and a local one): the panel lets you pick."""
    login(page, "alex", DEMO_PW)
    page.goto("/p/DEMO")
    open_assistant(page)
    picker = page.get_by_test_id("assistant-model")
    expect(picker).to_have_value("gpt-test")
    picker.click()
    page.get_by_role("option", name="qwen3:8b (lokal)").click()
    page.get_by_test_id("assistant-input").fill("Wie viele Anforderungen gibt es?")
    page.get_by_test_id("assistant-send").click()
    answer = page.get_by_test_id("assistant-answer").last
    expect(answer).to_contain_text("lokal beantwortet")
    expect(answer).to_contain_text("qwen3:8b")           # the answer names the model that wrote it
    expect(picker).to_be_disabled()                       # a running conversation keeps its model
    shot(page, "78-assistant-model")
