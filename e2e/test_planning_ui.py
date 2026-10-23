"""Polarion/Teamcenter-class planning and work management in the browser: query builder and query language,
configurable columns and sorting, bulk edit, Kanban boards with drag & drop transitions, the planning board,
the timeline (critical path, baseline comparison, rescheduling, dependencies) and the workflow viewer."""

import re
import uuid
from datetime import date, timedelta

from playwright.sync_api import Page, expect

from conftest import add_filter, drag, login, shot

DEMO_PW = "demo1234"
API = "/api/v1/projects/DEMO"


def create(page: Page, type_: str, title: str, **fields) -> str:
    resp = page.request.post(f"{API}/items", data={"type": type_, "title": title, "fields": fields})
    assert resp.ok, resp.text()
    return resp.json()["key"]


def test_query_builder_language_columns_and_sorting(page: Page):
    login(page, "alex", DEMO_PW)
    page.goto("/p/DEMO/items")
    page.get_by_test_id("qtext-toggle").click()
    page.get_by_test_id("qtext").fill("type:system_requirement priority:(must OR should) NOT link.verifies.in:*")
    page.get_by_test_id("qtext-apply").click()
    expect(page.get_by_test_id("qchip-type")).to_contain_text("System Requirement")
    expect(page.get_by_test_id("qchip-field.priority")).to_contain_text("Must, Should")
    expect(page.get_by_test_id("qchip-link.verifies.in")).to_contain_text("none")
    total = page.request.get(f"{API}/items?ql=type:system_requirement priority:(must OR should) NOT link.verifies.in:*&limit=1").json()["total"]
    expect(page.get_by_text(f"{total} item(s)")).to_be_visible()
    rows = page.get_by_test_id("items-table").locator("tbody tr")
    # a wrong query explains itself
    page.get_by_test_id("qtext").fill("state:draft OR state:approved")
    page.get_by_test_id("qtext-apply").click()
    expect(page.get_by_test_id("qtext-error")).to_contain_text("OR combines values")
    # chips: negate the priority filter
    page.get_by_test_id("qchip-field.priority").click()
    page.get_by_test_id("qedit").get_by_text("is not", exact=True).click()
    page.get_by_test_id("qedit").get_by_role("button", name="Done").click()
    expect(page.get_by_test_id("qchip-field.priority")).to_contain_text("NOT Priority")
    page.get_by_test_id("qclear").click()
    expect(page.get_by_test_id("qchip-type")).to_have_count(0)
    # columns and sorting by a custom number field
    add_filter(page, "type", options=("system_requirement",))
    page.get_by_test_id("columns-menu").click()
    page.get_by_test_id("columns-chooser").get_by_test_id("col-field.estimate").check()
    page.keyboard.press("Escape")
    expect(page.get_by_test_id("sort-field.estimate")).to_be_visible()
    page.get_by_test_id("sort-field.estimate").click()
    page.get_by_test_id("sort-field.estimate").click()
    expect(page).to_have_url(re.compile(r"sort=-field\.estimate"))
    top = page.request.get(f"{API}/items?type=system_requirement&sort=-field.estimate&limit=1").json()["items"][0]["key"]
    expect(rows.first).to_contain_text(top)
    shot(page, "50-query-builder")


def test_bulk_edit_fields_and_status_with_preview(page: Page):
    login(page, "alex", DEMO_PW)
    tag = uuid.uuid4().hex[:5]
    keys = [create(page, "system_requirement", f"Bulk {tag} {n}", priority="could") for n in range(2)]
    page.goto("/p/DEMO/items?type=system_requirement")
    page.get_by_test_id("items-search").fill(f"Bulk {tag}")
    expect(page.get_by_test_id("items-table").locator("tbody tr")).to_have_count(2)
    page.get_by_test_id("select-page").check()
    expect(page.get_by_test_id("bulk-count")).to_have_text("2 selected")
    page.get_by_test_id("bulk-edit").click()
    modal = page.get_by_test_id("bulk-modal")
    modal.get_by_test_id("bulk-field").click()
    page.get_by_role("option", name="Priority", exact=True).click()
    modal.get_by_test_id("field-priority").click()
    page.get_by_role("option", name="Should", exact=True).click()
    modal.get_by_test_id("bulk-preview-run").click()
    expect(modal.get_by_test_id("bulk-preview")).to_contain_text("ok: 2")
    shot(page, "51-bulk-preview")
    modal.get_by_test_id("bulk-apply").click()
    expect(page.get_by_text(re.compile(r"Edit fields: 2 changed"))).to_be_visible()
    for k in keys:
        assert page.request.get(f"{API}/items/{k}").json()["fields"]["priority"] == "should"
    # change status of both at once
    page.get_by_test_id("select-page").check()
    page.get_by_test_id("bulk-state").click()
    page.get_by_test_id("bulk-transition").click()
    page.get_by_role("option", name="Submit for review", exact=True).click()
    page.get_by_test_id("bulk-preview-run").click()
    expect(page.get_by_test_id("bulk-preview")).to_contain_text("ok: 2")
    page.get_by_test_id("bulk-apply").click()
    expect(page.get_by_text(re.compile(r"Change status: 2 changed"))).to_be_visible()
    for k in keys:
        assert page.request.get(f"{API}/items/{k}").json()["lifecycle"]["state"] == "in_review"


def test_board_drag_runs_transitions_and_board_configuration(page: Page):
    login(page, "alex", DEMO_PW)
    tag = uuid.uuid4().hex[:5]
    key = create(page, "system_requirement", f"Board card {tag}", priority="must")
    # the shared demo board shows the card with WIP limits and swimlanes
    page.goto("/p/DEMO/boards")
    page.get_by_test_id("board-Requirements by status").click()
    expect(page.get_by_test_id("cell-draft-must").get_by_test_id(f"card-{key}")).to_be_attached()
    expect(page.get_by_test_id("count-in_review")).to_contain_text("/ 3")  # WIP limit shown
    # a personal board filtered to this card keeps the drag test independent of other data
    board = page.request.post(f"{API}/boards", data={"name": f"E2E {tag}", "config": {
        "types": ["system_requirement"], "columns_by": "state", "conditions": [
            {"field": "title", "op": "contains", "values": [tag]}]}}).json()
    page.goto(f"/p/DEMO/boards?board={board['id']}")
    card = page.get_by_test_id(f"card-{key}")
    expect(page.get_by_test_id("col-draft").get_by_test_id(f"card-{key}")).to_be_visible()
    drag(page, card, page.get_by_test_id("col-in_review"))
    expect(page.get_by_text(f"{key}: Submit for review")).to_be_visible()
    expect(page.get_by_test_id("col-in_review").get_by_test_id(f"card-{key}")).to_be_visible()
    assert page.request.get(f"{API}/items/{key}").json()["lifecycle"]["state"] == "in_review"
    shot(page, "52-board")
    # back to draft needs a comment: the transition dialog asks for it
    drag(page, page.get_by_test_id(f"card-{key}"), page.get_by_test_id("col-draft"))
    page.get_by_test_id("prompt-comment").fill("Needs a measurable acceptance criterion")
    page.get_by_test_id("prompt-confirm").click()
    expect(page.get_by_test_id("col-draft").get_by_test_id(f"card-{key}")).to_be_visible()
    # moving to a state without a transition is refused and nothing changes
    drag(page, page.get_by_test_id(f"card-{key}"), page.get_by_test_id("col-approved"))
    expect(page.get_by_text(re.compile(r"No transition from Draft to Approved"))).to_be_visible()
    assert page.request.get(f"{API}/items/{key}").json()["lifecycle"]["state"] == "draft"
    page.wait_for_load_state("networkidle")
    page.get_by_test_id("board-delete").click()
    expect(page.get_by_text("Board deleted").first).to_be_visible()
    # a new personal board from a template
    page.get_by_role("button", name="Tasks by status").click()
    modal = page.get_by_test_id("board-modal")
    expect(modal.get_by_test_id("board-name")).to_have_value("Tasks by status")
    modal.get_by_test_id("board-save").click()
    expect(page.get_by_test_id("board-title")).to_have_text("Tasks by status")
    expect(page.get_by_test_id("board")).to_contain_text("Build B-samples")
    page.get_by_test_id("board-delete").click()
    expect(page.get_by_text("Board deleted").first).to_be_visible()


def test_planning_board_moves_work_between_backlog_and_iterations(page: Page):
    login(page, "alex", DEMO_PW)
    key = create(page, "system_requirement", f"Backlog {uuid.uuid4().hex[:4]}", estimate=2)
    plans = page.request.get(f"{API}/plans").json()["releases"]
    rel = next(r for r in plans if r["title"].startswith("Release 1.0"))
    sprint2 = next(r for r in plans if r["title"].startswith("Sprint 1"))  # the first sprint column is always in view
    page.goto(f"/p/DEMO/plans?release={rel['key']}")
    expect(page.get_by_test_id(f"release-{sprint2['key']}")).to_contain_text("Iteration")
    page.wait_for_timeout(300)
    page.get_by_test_id("plan-tab-planning").click()
    page.get_by_test_id("backlog-search").fill(key)
    card = page.get_by_test_id(f"pb-card-{key}")
    expect(card).to_be_visible()
    drag(page, card, page.get_by_test_id(f"pb-col-{sprint2['key']}"))
    expect(page.get_by_test_id(f"pb-col-{sprint2['key']}").get_by_test_id(f"pb-card-{key}")).to_be_visible()
    assert key in {i["key"] for i in page.request.get(f"{API}/plans/{sprint2['key']}").json()["items"]}
    shot(page, "53-planning-board")
    page.wait_for_timeout(400)
    drag(page, page.get_by_test_id(f"pb-col-{sprint2['key']}").get_by_test_id(f"pb-card-{key}"), page.get_by_test_id("pb-col-__backlog"))
    expect(page.get_by_test_id("pb-col-__backlog").get_by_test_id(f"pb-card-{key}")).to_be_visible()
    assert key not in {i["key"] for i in page.request.get(f"{API}/plans/{sprint2['key']}").json()["items"]}
    # burn-down by estimate
    page.get_by_test_id("plan-tab-overview").click()
    page.get_by_test_id("plan-chart-kind").get_by_text("Burn-down").click()
    page.get_by_test_id("plan-chart-metric").get_by_text("Estimate").click()
    expect(page.get_by_test_id("burnup")).to_be_visible()


def test_timeline_baseline_reschedule_and_dependency(page: Page):
    login(page, "max", DEMO_PW)
    rows = {r["title"]: r for r in page.request.get(f"{API}/timeline").json()["rows"]}
    qual, pilot, proto = rows["Temperature qualification"], rows["Pilot production preparation"], rows["Build B-samples"]
    page.goto("/p/DEMO/timeline")
    expect(page.get_by_test_id("tl-conflicts")).to_contain_text(f"{rows['Design review DR2']['key']} starts")
    expect(page.get_by_test_id(f"tl-row-{qual['key']}")).to_have_class(re.compile("is-critical"))
    page.get_by_test_id("tl-baseline").click()
    page.get_by_role("option", name="Schedule baseline").click()
    expect(page.get_by_test_id(f"tl-base-{qual['key']}")).to_be_attached()
    shot(page, "54-timeline")
    # drag the pilot preparation by one week (26 px per day in the week zoom)
    bar = page.get_by_test_id(f"tl-bar-{pilot['key']}")
    bar.scroll_into_view_if_needed()
    box = bar.bounding_box()
    days = 7 if box["x"] + 30 + 7 * 26 + 20 < 1440 else -7  # stay inside the window
    drag(page, bar, None, dx=days * 26)
    shifted = (date.fromisoformat(pilot["start_date"]) + timedelta(days=days)).isoformat()
    expect(page.get_by_text(re.compile(rf"{pilot['key']}: {shifted}"))).to_be_visible()
    assert page.request.get(f"{API}/items/{pilot['key']}").json()["fields"]["start_date"] == shifted
    # a new task gets a predecessor through the row menu
    task = page.request.post(f"{API}/items", data={"type": "task", "title": "Write safety manual",
                                                    "fields": {"start_date": pilot["start_date"], "due_date": pilot["due_date"]}}).json()["key"]
    page.reload()
    page.get_by_test_id(f"tl-menu-{task}").click()
    page.get_by_test_id("tl-add-dep").click()
    page.get_by_test_id("tl-dep-picker").click()
    page.get_by_test_id("tl-dep-picker").fill(proto["key"])
    page.get_by_role("option", name=re.compile(proto["key"])).click()
    page.get_by_test_id("tl-dep-save").click()
    expect(page.get_by_text(f"{task} now starts after {proto['key']} finishes")).to_be_visible()
    assert {r["key"]: r for r in page.request.get(f"{API}/timeline").json()["rows"]}[task]["depends_on"] == [proto["key"]]


def test_workflow_viewer_shows_state_and_next_steps(page: Page):
    login(page, "alex", DEMO_PW)
    key = create(page, "system_requirement", f"Workflow {uuid.uuid4().hex[:4]}")
    page.goto(f"/p/DEMO/items/{key}")
    viewer = page.get_by_test_id("workflow-card")
    expect(viewer.get_by_test_id("wf-state-draft")).to_have_attribute("data-current", "true")
    expect(viewer.get_by_test_id("wf-next-in_review")).to_be_attached()
    page.request.post(f"{API}/items/{key}/transitions/submit", data={})
    page.reload()
    expect(page.get_by_test_id("workflow-card").get_by_test_id("wf-state-in_review")).to_have_attribute("data-current", "true")
