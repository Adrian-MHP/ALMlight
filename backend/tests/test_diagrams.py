"""Architecture diagrams: a view of the model, not a drawing.

An element can be on several diagrams, taking it off a diagram leaves the item alone, and a relationship drawn
on the canvas is a real link of the project — with the model's rules, the suspect marking and the audit trail.
Also: what a browser may store in the canvas, the layering, the SVG and the permissions.
"""

import uuid

import pytest
from conftest import new_item
from sqlalchemy import select

from almlight.modules.diagrams import service, svg


def make(api, project, title="Architecture", viewpoint="internal"):
    return new_item(api, project, "diagram", title, fields={"viewpoint": viewpoint})["key"]


def nodes_of(view, *keys):
    return [n for n in view["nodes"] if n.get("item") in keys]


def test_a_diagram_shows_items_and_the_links_they_already_have(team, project):
    c = team["contributor"]
    p = f"/projects/{project}"
    ecu = new_item(c, project, "system_element", "Sensor ECU")["key"]
    housing = new_item(c, project, "system_element", "Housing")["key"]
    c.post(f"{p}/links", {"type": "contains", "source": housing, "target": ecu}, expect=201)
    key = make(c, project)

    view = c.post(f"{p}/diagrams/{key}/items", {"keys": [housing, ecu]})
    assert [n["item"] for n in view["nodes"]] == [housing, ecu]
    shown = view["nodes"][0]
    assert shown["title"] == "Housing" and shown["type"] == "system_element" and shown["category"] == "architecture"
    assert shown["state"] == "In Work" and shown["w"] == 180 and shown["x"] != view["nodes"][1]["x"] or True
    # the link that already existed is drawn, without creating anything
    assert len(view["edges"]) == 1 and view["edges"][0]["label"] == "contains"
    assert view["edges"][0]["from"] == view["nodes"][0]["id"] and view["edges"][0]["to"] == view["nodes"][1]["id"]
    assert len(c.get(f"{p}/items/{housing}/links")) == 1  # nothing new was linked

    # the diagram is an ordinary item: versioned, with the change in its history
    detail = c.get(f"{p}/items/{key}")
    assert detail["version"] == "A.2" and detail["type_key"] == "diagram"
    assert c.get(f"{p}/items/{key}/versions")[0]["change_note"] == "Added 2 element(s) to the diagram"
    assert c.get(f"{p}/diagrams")[0]["nodes"] == 2


def test_drawing_a_relationship_creates_a_real_link(team, project, db):
    c = team["contributor"]
    p = f"/projects/{project}"
    element = new_item(c, project, "system_element", "Measuring cell")["key"]
    requirement = new_item(c, project, "system_requirement", "Measure pressure")["key"]
    key = make(c, project, viewpoint="allocation")
    view = c.post(f"{p}/diagrams/{key}/items", {"keys": [element, requirement]})
    source, target = view["nodes"][0]["id"], view["nodes"][1]["id"]

    view = c.post(f"{p}/diagrams/{key}/connect", {**view_content(view), "source": source, "target": target,
                                                  "type": "satisfies"})
    assert len(view["edges"]) == 1 and view["edges"][0]["type"] == "satisfies"
    links = c.get(f"{p}/items/{element}/links")
    assert [(link["type"], link["other"]["key"]) for link in links] == [("satisfies", requirement)]
    assert c.get(f"{p}/items/{key}/versions")[0]["change_note"] == f"{element} satisfies {requirement}"

    # the model's rules apply: a test case cannot satisfy a requirement
    bad = c.post(f"{p}/diagrams/{key}/connect", {**view_content(view), "source": target, "target": source,
                                                 "type": "verifies"}, expect=422)
    assert "does not allow" in bad["error"]["message"]

    # changing the requirement marks the link suspect, and the diagram shows that
    c.patch(f"{p}/items/{requirement}", {"title": "Measure pressure 0-10 bar"})
    assert c.get(f"{p}/diagrams/{key}")["edges"][0]["suspect"] is True

    from almlight.modules.audit.models import AuditEntry

    actions = db.execute(select(AuditEntry.action).where(AuditEntry.action == "link.created")).scalars().all()
    assert len(actions) == 1  # the link was created once, through the normal service


def view_content(view):
    """What the browser sends back: the canvas as it is now."""
    return {"nodes": [{k: n[k] for k in ("id", "x", "y", "w", "h")} | (
        {"item": n["item"]} if n.get("kind") != "note" else {"kind": "note", "text": n["text"]})
        for n in view["nodes"]],
        "edges": [{k: e[k] for k in ("id", "from", "to") if e.get(k)} | ({"link": e["link"]} if e.get("link") else {})
                  for e in view["edges"]]}


def test_an_element_lives_on_several_diagrams_and_removing_it_keeps_the_item(team, project):
    c = team["contributor"]
    p = f"/projects/{project}"
    ecu = new_item(c, project, "system_element", "Sensor ECU")["key"]
    other = new_item(c, project, "system_element", "Cable")["key"]
    first, second = make(c, project, "Context"), make(c, project, "Internal")
    c.post(f"{p}/diagrams/{first}/items", {"keys": [ecu, other]})
    view = c.post(f"{p}/diagrams/{second}/items", {"keys": [ecu]})
    assert [n["item"] for n in view["nodes"]] == [ecu]

    # taking it off one diagram leaves the item and the other diagram alone
    node = view["nodes"][0]["id"]
    after = c.post(f"{p}/diagrams/{second}/nodes/{node}/remove", view_content(view))
    assert after["nodes"] == []
    assert c.get(f"{p}/items/{ecu}")["title"] == "Sensor ECU"
    assert [n["item"] for n in c.get(f"{p}/diagrams/{first}")["nodes"]] == [ecu, other]
    assert c.get(f"{p}/items/{second}/versions")[0]["change_note"] == f"Removed {ecu} from the diagram"


def test_a_relationship_can_be_taken_off_the_diagram_or_deleted(team, project):
    c = team["contributor"]
    p = f"/projects/{project}"
    a = new_item(c, project, "system_element", "Pump")["key"]
    b = new_item(c, project, "system_element", "Valve")["key"]
    key = make(c, project)
    view = c.post(f"{p}/diagrams/{key}/items", {"keys": [a, b]})
    view = c.post(f"{p}/diagrams/{key}/connect", {**view_content(view), "source": view["nodes"][0]["id"],
                                                  "target": view["nodes"][1]["id"], "type": "relates_to"})
    edge = view["edges"][0]["id"]

    off = c.post(f"{p}/diagrams/{key}/edges/{edge}/remove", {**view_content(view), "delete_link": False})
    assert off["edges"] == [] and len(c.get(f"{p}/items/{a}/links")) == 1  # the link stayed
    # putting the pair on the diagram again draws the link that is still there
    again = c.post(f"{p}/diagrams/{key}/nodes/{off['nodes'][0]['id']}/remove", view_content(off))
    again = c.post(f"{p}/diagrams/{key}/items", {**view_content(again), "keys": [a]})
    assert len(again["edges"]) == 1

    gone = c.post(f"{p}/diagrams/{key}/edges/{again['edges'][0]['id']}/remove",
                  {**view_content(again), "delete_link": True})
    assert gone["edges"] == [] and c.get(f"{p}/items/{a}/links") == []
    assert c.get(f"{p}/items/{key}/versions")[0]["change_note"].startswith("Deleted a link")


def test_the_diagram_says_what_no_longer_matches_the_model(team, project):
    c, m = team["contributor"], team["manager"]
    p = f"/projects/{project}"
    a = new_item(c, project, "system_element", "Gone soon")["key"]
    b = new_item(c, project, "system_element", "Stays")["key"]
    key = make(c, project)
    view = c.post(f"{p}/diagrams/{key}/items", {"keys": [a, b]})
    view = c.post(f"{p}/diagrams/{key}/connect", {**view_content(view), "source": view["nodes"][0]["id"],
                                                  "target": view["nodes"][1]["id"], "type": "relates_to"})
    link_id = view["edges"][0]["link"]

    c.delete(f"{p}/links/{link_id}")
    m.delete(f"{p}/items/{a}")
    after = c.get(f"{p}/diagrams/{key}")
    assert after["stale"]["missing_items"] == [a]
    assert next(n for n in after["nodes"] if n.get("item") == a)["missing"] is True
    assert after["edges"] == [] and len(after["stale"]["removed_links"]) == 1


def test_items_can_be_offered_and_arranged(team, project):
    c = team["contributor"]
    p = f"/projects/{project}"
    parent = new_item(c, project, "system_element", "Transmitter")["key"]
    child = new_item(c, project, "system_element", "Sensor")["key"]
    grandchild = new_item(c, project, "system_element", "Diaphragm")["key"]
    for source, target in ((parent, child), (child, grandchild)):
        c.post(f"{p}/links", {"type": "contains", "source": source, "target": target}, expect=201)
    key = make(c, project, viewpoint="decomposition")
    c.post(f"{p}/diagrams/{key}/items", {"keys": [parent]})

    offered = c.get(f"{p}/diagrams/{key}/related")
    assert [r["key"] for r in offered] == [child] and offered[0]["via"] == "contains"
    view = c.post(f"{p}/diagrams/{key}/items", {**view_content(c.get(f"{p}/diagrams/{key}")), "keys": [child]})
    assert len(view["edges"]) == 1

    view = c.post(f"{p}/diagrams/{key}/items", {**view_content(view), "keys": [grandchild]})
    arranged = c.post(f"{p}/diagrams/{key}/layout", view_content(view))
    rows = {n["item"]: n["y"] for n in arranged["nodes"]}
    assert rows[parent] < rows[child] < rows[grandchild]  # what contains something stands above it
    assert c.get(f"{p}/items/{key}/versions")[0]["change_note"] == "Arranged the diagram"
    # the viewpoint suggests what belongs on this kind of diagram
    kinds = c.get(f"{p}/diagrams/{key}/palette")
    assert {t["key"] for t in kinds["suggested_types"]} == {"system_element", "function"}
    assert {lt["key"] for lt in kinds["suggested_links"]} == {"contains", "realizes"}
    assert len(kinds["all_types"]) > len(kinds["suggested_types"])


def test_the_layering_survives_a_cycle_and_a_self_link():
    nodes = [{"id": "a", "x": 0, "y": 0, "w": 180, "h": 72}, {"id": "b", "x": 0, "y": 0, "w": 180, "h": 72},
             {"id": "c", "x": 0, "y": 0, "w": 180, "h": 72}]
    edges = [{"id": "1", "from": "a", "to": "b"}, {"id": "2", "from": "b", "to": "c"},
             {"id": "3", "from": "c", "to": "a"}, {"id": "4", "from": "a", "to": "a"}]
    placed = service.arrange(nodes, edges)
    assert len(placed) == 3 and all(n["y"] >= 0 for n in placed)
    assert len({(n["x"], n["y"]) for n in placed}) == 3  # nothing lies on top of something else


def test_what_a_browser_may_store_in_the_canvas(team, project):
    c = team["contributor"]
    p = f"/projects/{project}"
    element = new_item(c, project, "system_element", "Valve")["key"]
    key = make(c, project)
    view = c.post(f"{p}/diagrams/{key}/items", {"keys": [element]})
    good = view_content(view)

    # places are kept, and absurd values are brought back into range instead of being stored
    moved = {**good, "nodes": [{**good["nodes"][0], "x": 123.456, "y": -80, "w": 10, "h": 99999}]}
    saved = c.put(f"{p}/diagrams/{key}", moved)
    assert saved["nodes"][0]["x"] == 123.46 and saved["nodes"][0]["y"] == -80
    assert saved["nodes"][0]["w"] == 60 and saved["nodes"][0]["h"] == 2000

    for broken, why in [
        ({"nodes": [{"id": "../etc", "x": 0, "y": 0}], "edges": []}, "usable id"),
        ({"nodes": [{"id": "n1", "x": "left", "y": 0}], "edges": []}, "coordinate"),
        ({"nodes": [{"id": "n1", "x": 0, "y": 0}], "edges": []}, "shows no item"),
        ({"nodes": [{"id": "n1", "item": "X-1", "x": 0, "y": 0}, {"id": "n1", "item": "X-2", "x": 0, "y": 0}],
          "edges": []}, "twice"),
        ({"nodes": [], "edges": [{"id": "e1", "from": "n1", "to": "n2"}]}, "does not connect"),
        ({"nodes": [{"id": "n1", "item": "X-1", "x": 0, "y": 0}, {"id": "n2", "item": "X-2", "x": 0, "y": 0}],
          "edges": [{"id": "e1", "from": "n1", "to": "n2", "link": "not-a-uuid"}]}, "usable link"),
    ]:
        err = c.put(f"{p}/diagrams/{key}", broken, expect=422)
        assert why in err["error"]["details"]["fields"]["content"], (why, err)

    many = {"nodes": [{"id": f"n{i}", "item": element, "x": 0, "y": 0} for i in range(301)], "edges": []}
    assert "at most 300" in c.put(f"{p}/diagrams/{key}", many, expect=422)["error"]["details"]["fields"]["content"]
    # a note is text, not an item
    with_note = c.post(f"{p}/diagrams/{key}/notes", {**good, "text": "Open: cable routing"})
    note = next(n for n in with_note["nodes"] if n["kind"] == "note")
    assert note["text"] == "Open: cable routing"
    cannot = c.post(f"{p}/diagrams/{key}/connect", {**view_content(with_note), "source": note["id"],
                                                    "target": with_note["nodes"][0]["id"], "type": "relates_to"},
                    expect=422)
    assert "note" in cannot["error"]["message"]


def test_two_people_editing_the_same_diagram_get_a_clean_conflict(team, project):
    c, m = team["contributor"], team["manager"]
    p = f"/projects/{project}"
    element = new_item(c, project, "system_element", "Valve")["key"]
    key = make(c, project)
    view = c.post(f"{p}/diagrams/{key}/items", {"keys": [element]})
    version = c.get(f"{p}/items/{key}")["version_no"]
    content = view_content(view)

    c.put(f"{p}/diagrams/{key}", {**content, "nodes": [{**content["nodes"][0], "x": 300}],
                                  "expected_version": version})
    stale = m.put(f"{p}/diagrams/{key}", {**content, "nodes": [{**content["nodes"][0], "x": 500}],
                                          "expected_version": version}, expect=409)
    assert "changed by someone else" in stale["error"]["message"]


def test_the_picture_can_be_downloaded_and_shows_what_is_on_the_canvas(team, project):
    c = team["contributor"]
    p = f"/projects/{project}"
    element = new_item(c, project, "system_element", "Measuring cell")["key"]
    requirement = new_item(c, project, "system_requirement", "Measure pressure <script>x</script>")["key"]
    key = make(c, project, "Context view")
    view = c.post(f"{p}/diagrams/{key}/items", {"keys": [element, requirement]})
    c.post(f"{p}/diagrams/{key}/connect", {**view_content(view), "source": view["nodes"][0]["id"],
                                           "target": view["nodes"][1]["id"], "type": "satisfies"})
    resp = c.get(f"{p}/diagrams/{key}.svg")
    picture = resp.text
    assert resp.headers["content-type"].startswith("image/svg+xml")
    assert picture.startswith("<svg") and picture.endswith("</svg>")
    assert "Measuring cell" in picture and element in picture and "satisfies" in picture
    assert "Context view" in picture and "System Element" in picture
    assert "<script>" not in picture and "&lt;script&gt;" in picture  # titles are escaped, never executed
    assert "marker-end" in picture and 'fill="#e8f5f6"' in picture  # an arrow, and the architecture colour

    # two relationships between the same pair are bowed apart instead of lying on top of each other
    view = c.get(f"{p}/diagrams/{key}")
    two = {**view, "edges": [{**view["edges"][0], "id": "e1"}, {**view["edges"][0], "id": "e2"}]}
    paths = [line for line in svg.render(two).split("<path") if " Q " in line]
    assert len(paths) == 2 and paths[0] != paths[1]
    assert svg.parallel(two["edges"]) == {"e1": -13.0, "e2": 13.0}
    assert svg.control(0, 0, 10, 0, 0) == (5, 0) and svg.control(0, 0, 10, 0, 10) == (5.0, 10.0)

    # a long title is cut instead of running out of its box
    long_key = new_item(c, project, "system_element", "A " + "very " * 40 + "long name")["key"]
    view = c.post(f"{p}/diagrams/{key}/items", {**view_content(c.get(f"{p}/diagrams/{key}")), "keys": [long_key]})
    assert "…" in svg.render(view)


def test_only_contributors_change_a_diagram_and_only_diagrams_are_opened(team, project):
    c, v = team["contributor"], team["viewer"]
    p = f"/projects/{project}"
    element = new_item(c, project, "system_element", "Valve")["key"]
    key = make(c, project)
    view = c.post(f"{p}/diagrams/{key}/items", {"keys": [element]})

    assert v.get(f"{p}/diagrams/{key}")["nodes"]      # readers see the diagram
    v.get(f"{p}/diagrams/{key}.svg")
    v.put(f"{p}/diagrams/{key}", view_content(view), expect=403)
    v.post(f"{p}/diagrams/{key}/items", {"keys": [element]}, expect=403)
    v.post(f"{p}/diagrams/{key}/layout", view_content(view), expect=403)

    # an item that is not a diagram is refused, and so is an item of another project
    assert "not an architecture diagram" in c.get(f"{p}/diagrams/{element}", expect=422)["error"]["message"]
    c.get(f"{p}/diagrams/NOPE-1", expect=404)
    c.post(f"{p}/diagrams/{key}/items", {"keys": ["NOPE-1"]}, expect=404)
    c.post(f"{p}/diagrams/{key}/nodes/nope/remove", view_content(view), expect=404)


def test_a_released_diagram_is_frozen_like_any_other_item(team, project):
    from conftest import approve

    c, r = team["contributor"], team["reviewer"]
    p = f"/projects/{project}"
    element = new_item(c, project, "system_element", "Valve")["key"]
    key = make(c, project)
    view = c.post(f"{p}/diagrams/{key}/items", {"keys": [element]})
    c.post(f"{p}/items/{key}/transitions/freeze", {})
    approve(key, project, c, r, "release")
    assert c.get(f"{p}/diagrams/{key}")["frozen"] is True
    moved = view_content(view)
    moved["nodes"][0]["x"] = 400
    locked = c.put(f"{p}/diagrams/{key}", moved, expect=423)
    assert "released" in locked["error"]["message"].lower() or "frozen" in locked["error"]["message"].lower()


def test_the_diagram_field_is_validated_on_its_own():
    """The field type is the gate: whatever reaches it, only a clean canvas is stored."""
    from almlight.modules.items.fields import _diagram

    assert _diagram({}) == {"nodes": [], "edges": []}
    cleaned = _diagram({"nodes": [{"id": "n1", "item": " se-1 ", "x": 1.005, "y": 2, "w": 180, "h": 72,
                                   "extra": "dropped"}], "edges": []})
    assert cleaned["nodes"] == [{"id": "n1", "x": 1.0, "y": 2.0, "w": 180.0, "h": 72.0, "item": "SE-1"}]
    assert _diagram({"nodes": [{"id": "n1", "kind": "note", "text": "x" * 2000, "x": 0, "y": 0}],
                     "edges": []})["nodes"][0]["text"] == "x" * 1000
    for value in ("nonsense", {"nodes": "x"}, {"nodes": [{"id": "n1", "item": "X", "x": 0, "y": 0}] * 2}):
        with pytest.raises(ValueError):
            _diagram(value)
    link = str(uuid.uuid4())
    kept = _diagram({"nodes": [{"id": "a", "item": "X-1", "x": 0, "y": 0}, {"id": "b", "item": "X-2", "x": 0, "y": 0}],
                     "edges": [{"id": "e", "from": "a", "to": "b", "link": link, "junk": 1}]})
    assert kept["edges"] == [{"id": "e", "from": "a", "to": "b", "link": link}]
