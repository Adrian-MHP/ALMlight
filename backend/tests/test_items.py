import io

from conftest import new_item


def test_create_item_with_defaults_and_key_sequence(team, project):
    c = team["contributor"]
    a = new_item(c, project, "system_requirement", "Measure process pressure", description="0-10 bar")
    b = new_item(c, project, "system_requirement", "Provide 4-20 mA output")
    assert a["key"] == "SYS-1" and b["key"] == "SYS-2"
    assert a["version"] == "A.1" and a["lifecycle"]["state"] == "draft"
    assert a["fields"]["priority"] == "should" and a["fields"]["verification_method"] == "test"
    assert a["owner"]["username"] == "carla"
    el = new_item(c, project, "system_element", "Sensor unit", fields={"level": "subsystem"})
    assert el["key"] == "SE-1"


def test_field_validation(team, project):
    c = team["contributor"]
    url = f"/projects/{project}/items"
    c.post(url, {"type": "system_requirement", "title": ""}, expect=422)
    c.post(url, {"type": "unknown_type", "title": "x"}, expect=422)
    err = c.post(url, {"type": "system_requirement", "title": "x", "fields": {"priority": "urgent"}}, expect=422)
    assert "priority" in err["error"]["details"]["fields"]
    err = c.post(url, {"type": "system_requirement", "title": "x", "fields": {"nope": 1}}, expect=422)
    assert "nope" in err["error"]["details"]["fields"]
    c.post(url, {"type": "system_requirement", "title": "x", "fields": {"safety_relevant": "maybe"}}, expect=422)
    c.post(url, {"type": "feature", "title": "f", "fields": {"code": "1bad"}}, expect=422)
    c.post(url, {"type": "test_run", "title": "r", "fields": {"planned_date": "31.12.2026"}}, expect=422)
    c.post(url, {"type": "system_requirement", "title": "x", "applicability": "A and (B or"}, expect=422)


def test_edit_creates_versions_and_history(team, project):
    c = team["contributor"]
    item = new_item(c, project, "system_requirement", "Measure pressure")
    url = f"/projects/{project}/items/{item['key']}"
    v2 = c.patch(url, {"title": "Measure process pressure", "fields": {"priority": "must"}, "change_note": "x"})
    assert v2["version"] == "A.2" and v2["fields"]["priority"] == "must"
    same = c.patch(url, {"title": "Measure process pressure"})
    assert same["version"] == "A.2"  # no-op edits do not create versions
    v3 = c.patch(url, {"description": "line 1\nline 2", "fields": {"priority": None}})
    assert v3["version"] == "A.3" and "priority" not in v3["fields"]
    versions = c.get(f"{url}/versions")
    assert [v["version"] for v in versions] == ["A.3", "A.2", "A.1"]
    assert versions[1]["change_note"] == "x"
    diff = c.get(f"{url}/diff?from=1&to=3")
    fields = {ch["field"] for ch in diff["changes"]}
    assert {"title", "description"} <= fields
    history = c.get(f"{url}/history")
    assert {"item.created", "item.updated"} <= {h["action"] for h in history}


def test_optimistic_locking(team, project):
    c = team["contributor"]
    item = new_item(c, project, "system_requirement", "R")
    url = f"/projects/{project}/items/{item['key']}"
    c.patch(url, {"title": "R1", "expected_version": 1})
    err = c.patch(url, {"title": "R2", "expected_version": 1}, expect=409)
    assert err["error"]["details"]["current_version_no"] == 2


def test_restore_version(team, project):
    c = team["contributor"]
    item = new_item(c, project, "system_requirement", "Original")
    url = f"/projects/{project}/items/{item['key']}"
    c.patch(url, {"title": "Changed"})
    restored = c.post(f"{url}/restore", {"version_no": 1})
    assert restored["title"] == "Original" and restored["version"] == "A.3"
    assert c.get(f"{url}/versions")[0]["kind"] == "restore"


def test_owner_change_is_metadata(team, project):
    c = team["contributor"]
    item = new_item(c, project, "system_requirement", "R")
    url = f"/projects/{project}/items/{item['key']}"
    updated = c.patch(url, {"owner_id": team["users"]["reviewer"]["id"]})
    assert updated["owner"]["username"] == "rene" and updated["version"] == "A.1"


def test_search_and_filters(team, project):
    c = team["contributor"]
    new_item(c, project, "system_requirement", "Measure process pressure", fields={"priority": "must"})
    new_item(c, project, "system_requirement", "Display the temperature")
    new_item(c, project, "stakeholder_requirement", "Reliable pressure monitoring")
    base = f"/projects/{project}/items"
    assert c.get(f"{base}?q=pressure")["total"] == 2
    assert c.get(f"{base}?q=SYS-2")["items"][0]["title"] == "Display the temperature"
    assert c.get(f"{base}?type=stakeholder_requirement")["total"] == 1
    assert c.get(f"{base}?field.priority=must")["total"] == 1
    assert c.get(f"{base}?state=draft&limit=1")["total"] == 3
    hits = c.get("/search?q=pressure")
    assert len(hits) == 2


def test_attachments_versioned(team, project):
    c = team["contributor"]
    doc = new_item(c, project, "document", "Datasheet", fields={"doc_kind": "datasheet"})
    url = f"/projects/{project}/items/{doc['key']}"
    up = c.post(f"{url}/attachments", files={"file": ("sheet.pdf", io.BytesIO(b"%PDF-1.4 test"), "application/pdf")},
                expect=201)
    assert up["version"] == "A.2" and up["attachments"][0]["filename"] == "sheet.pdf"
    att = up["attachments"][0]
    resp = c.get(f"{url}/attachments/{att['id']}")
    assert resp.content == b"%PDF-1.4 test"
    removed = c.delete(f"{url}/attachments/{att['id']}")
    assert removed["attachments"] == [] and removed["version"] == "A.3"
    # The file is still reachable through the version that contained it.
    old = c.get(f"{url}/attachments/{att['id']}?version=2")
    assert old.content == b"%PDF-1.4 test"
    c.get(f"{url}/attachments/{att['id']}", expect=404)


def test_comments(team, project):
    c, r = team["contributor"], team["reviewer"]
    item = new_item(c, project, "system_requirement", "R")
    url = f"/projects/{project}/items/{item['key']}/comments"
    com = r.post(url, {"body": "Please clarify the range"}, expect=201)
    c.post(url, {"body": "   "}, expect=422)
    assert len(c.get(url)) == 1
    c.delete(f"{url}/{com['id']}", expect=403)
    team["manager"].delete(f"{url}/{com['id']}")
    assert c.get(url) == []


def test_delete_item(team, project):
    c, m = team["contributor"], team["manager"]
    a = new_item(c, project, "system_requirement", "A")
    b = new_item(c, project, "stakeholder_requirement", "B")
    c.post(f"/projects/{project}/links", {"type": "derives_from", "source": a["key"], "target": b["key"]})
    m.delete(f"/projects/{project}/items/{a['key']}")
    c.get(f"/projects/{project}/items/{a['key']}", expect=404)
    assert c.get(f"/projects/{project}/items/{b['key']}/links") == []


def test_document_tree(team, project):
    c = team["contributor"]
    spec = new_item(c, project, "specification", "System specification")
    h1 = new_item(c, project, "heading", "1 Measurement", parent=spec["key"])
    r1 = new_item(c, project, "system_requirement", "Measure pressure", parent=h1["key"])
    r2 = new_item(c, project, "system_requirement", "Measure temperature", parent=h1["key"])
    tree = c.get(f"/projects/{project}/items/{spec['key']}/tree?content=true")
    assert tree["children"][0]["key"] == h1["key"]
    assert [n["key"] for n in tree["children"][0]["children"]] == [r1["key"], r2["key"]]
    c.post(f"/projects/{project}/items/{r2['key']}/move", {"parent": h1["key"], "position": 0.5})
    tree = c.get(f"/projects/{project}/items/{spec['key']}/tree")
    assert [n["key"] for n in tree["children"][0]["children"]] == [r2["key"], r1["key"]]
