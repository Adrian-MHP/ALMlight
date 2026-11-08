"""Architecture diagrams in the browser: build a view of the model, draw a relationship that becomes a real
link, move an element, and check that taking it off the diagram leaves the item alone."""

import re

from playwright.sync_api import Page, expect

from conftest import choose, login, shot

DEMO_PW = "demo1234"
API = "/api/v1/projects/DEMO"


def test_a_diagram_is_built_and_drawing_a_relationship_creates_a_link(page: Page):
    login(page, "alex", DEMO_PW)
    page.goto("/p/DEMO/architecture")
    page.get_by_test_id("diagram-new").click()
    page.get_by_test_id("diagram-title").fill("Sensor system — internal")
    choose(page, "diagram-viewpoint", "Internal structure and interfaces")
    page.get_by_test_id("diagram-create").click()
    expect(page.get_by_test_id("diagram-canvas")).to_be_visible()
    key = re.search(r"/architecture/(DIA-\d+)", page.url).group(1)

    # put two elements of the project on the canvas
    items = page.request.get(f"{API}/items?type=system_element&limit=2&sort=key").json()["items"]
    first, second = items[0], items[1]
    for item in (first, second):
        page.get_by_test_id("diagram-add").click()
        picker = page.get_by_test_id("item-picker")
        picker.click()
        picker.fill(item["key"])
        option = page.get_by_role("option", name=re.compile(rf"^{item['key']} "))  # the list loads debounced
        expect(option).to_be_visible()
        option.click()
        page.get_by_test_id("add-picked").click()
        expect(page.get_by_test_id("item-picker")).to_have_count(0)
    expect(page.get_by_test_id(f"node-{first['key']}")).to_be_visible()
    expect(page.get_by_test_id(f"node-{second['key']}")).to_be_visible()

    # draw a relationship: pick the source, then the target, then the type
    page.get_by_test_id(f"node-{first['key']}").click()
    page.get_by_test_id("diagram-connect").click()
    expect(page.get_by_test_id("diagram-connecting")).to_be_visible()
    page.get_by_test_id(f"node-{second['key']}").click()
    page.get_by_test_id("connect-relates_to").click()
    expect(page.get_by_test_id("edge-relates_to")).to_be_visible()
    expect(page.get_by_test_id("edge-contains")).to_be_visible()  # the link the two already had
    shot(page, "79-architecture")

    # it is a real link of the project, visible on the item itself
    links = page.request.get(f"{API}/items/{first['key']}/links").json()
    assert any(link["type"] == "relates_to" and link["other"]["key"] == second["key"] for link in links)

    # moving an element makes the diagram dirty and the save keeps the new place
    node = page.get_by_test_id(f"node-{first['key']}")
    box = node.bounding_box()
    page.mouse.move(box["x"] + 40, box["y"] + 20)
    page.mouse.down()
    page.mouse.move(box["x"] + 240, box["y"] + 160, steps=8)
    page.mouse.up()
    moved_on_screen = node.bounding_box()
    assert moved_on_screen["x"] > box["x"] + 100, "the element did not follow the pointer"
    save = page.get_by_test_id("diagram-save")
    expect(save).to_be_enabled()
    with page.expect_response(lambda r: r.request.method == "PUT" and "/diagrams/" in r.url) as answer:
        save.click()
    assert answer.value.ok
    expect(save).to_be_disabled()
    placed = page.request.get(f"{API}/diagrams/{key}").json()
    moved = next(n for n in placed["nodes"] if n["item"] == first["key"])
    assert moved["x"] > 100
    # the link these two already had was drawn by itself, next to the one that was drawn by hand
    assert {e["type"] for e in placed["edges"]} == {"contains", "relates_to"}

    # the picture can be downloaded and shows what is on the canvas
    svg = page.request.get(f"{API}/diagrams/{key}.svg")
    assert svg.ok and svg.headers["content-type"].startswith("image/svg+xml")
    assert first["key"] in svg.text() and "relates to" in svg.text()

    # taking an element off the diagram leaves the item and its link in the project
    page.get_by_test_id(f"node-{first['key']}").click()
    page.get_by_test_id("diagram-remove").click()
    expect(page.get_by_test_id(f"node-{first['key']}")).to_have_count(0)
    assert page.request.get(f"{API}/items/{first['key']}").ok
    assert page.request.get(f"{API}/items/{first['key']}/links").json()


def test_a_reader_can_look_at_a_diagram_but_not_change_it(page: Page, playwright):
    from conftest import ADMIN_PASSWORD, BASE_URL

    admin = playwright.request.new_context(base_url=BASE_URL)
    assert admin.post("/api/v1/auth/login", data={"username": "admin", "password": ADMIN_PASSWORD}).ok
    created = admin.post("/api/v1/users", data={"username": "ria", "display_name": "Ria Reader",
                                                "password": "reader-password-2"})
    if created.ok:
        admin.put("/api/v1/projects/DEMO/members", data={"user_id": created.json()["id"], "role": "viewer"})
    diagram = admin.post("/api/v1/projects/DEMO/items",
                         data={"type": "diagram", "title": "Read only view", "fields": {"viewpoint": "context"}})
    key = diagram.json()["key"]
    element = admin.get(f"{API}/items?type=system_element&limit=1").json()["items"][0]["key"]
    admin.post(f"{API}/diagrams/{key}/items", data={"keys": [element], "nodes": [], "edges": []})
    admin.dispose()

    login(page, "ria", "reader-password-2")
    page.goto(f"/p/DEMO/architecture/{key}")
    expect(page.get_by_test_id(f"node-{element}")).to_be_visible()
    expect(page.get_by_test_id("diagram-add")).to_have_count(0)
    expect(page.get_by_test_id("diagram-save")).to_have_count(0)
    page.get_by_test_id(f"node-{element}").click()
    expect(page.get_by_test_id("diagram-panel")).to_contain_text(element)
    expect(page.get_by_test_id("diagram-remove")).to_have_count(0)
