from conftest import approve, new_item


def _link(api, project, type_, source, target, expect=(200, 201), **extra):
    return api.post(f"/projects/{project}/links", {"type": type_, "source": source, "target": target, **extra},
                    expect=expect)


def test_link_rules(team, project):
    c = team["contributor"]
    stk = new_item(c, project, "stakeholder_requirement", "Monitor pressure reliably")
    sys = new_item(c, project, "system_requirement", "Measure 0-10 bar")
    tc = new_item(c, project, "test_case", "Range test")
    _link(c, project, "derives_from", sys["key"], stk["key"])
    _link(c, project, "derives_from", sys["key"], stk["key"], expect=409)  # duplicate
    err = _link(c, project, "derives_from", stk["key"], tc["key"], expect=422)  # type pair not allowed
    assert "does not allow" in err["error"]["message"]
    _link(c, project, "verifies", tc["key"], sys["key"])
    _link(c, project, "nope", tc["key"], sys["key"], expect=422)
    _link(c, project, "relates_to", tc["key"], tc["key"], expect=422)  # self link
    links = c.get(f"/projects/{project}/items/{sys['key']}/links")
    by_dir = {(lk["direction"], lk["type"]) for lk in links}
    assert by_dir == {("outgoing", "derives_from"), ("incoming", "verifies")}
    incoming = next(lk for lk in links if lk["direction"] == "incoming")
    assert incoming["label"] == "verified by"


def test_cycle_prevention(team, project):
    c = team["contributor"]
    a = new_item(c, project, "system_requirement", "A")
    b = new_item(c, project, "system_requirement", "B")
    d = new_item(c, project, "system_requirement", "D")
    _link(c, project, "derives_from", a["key"], b["key"])
    _link(c, project, "derives_from", b["key"], d["key"])
    err = _link(c, project, "derives_from", d["key"], a["key"], expect=422)
    assert "cycle" in err["error"]["message"]


def test_suspect_links_and_confirmation(team, project):
    c = team["contributor"]
    sys = new_item(c, project, "system_requirement", "Measure 0-10 bar")
    tc = new_item(c, project, "test_case", "Range test")
    _link(c, project, "verifies", tc["key"], sys["key"])
    c.patch(f"/projects/{project}/items/{sys['key']}", {"title": "Measure 0-16 bar"})
    links = c.get(f"/projects/{project}/items/{tc['key']}/links")
    assert links[0]["suspect"] is True and "A.2" in links[0]["suspect_reason"]
    suspects = c.get(f"/projects/{project}/suspects")
    assert suspects[0]["source"] == tc["key"]
    assert c.get(f"/projects/{project}/items?suspect=true")["total"] == 1
    c.post(f"/projects/{project}/links/{links[0]['id']}/confirm", {"comment": "test still valid"})
    assert c.get(f"/projects/{project}/suspects") == []
    # Changing the source (test case) does not make the link suspect.
    c.patch(f"/projects/{project}/items/{tc['key']}", {"title": "Range test 16 bar"})
    assert c.get(f"/projects/{project}/suspects") == []


def test_frozen_source_cannot_change_links(team, project):
    c, r = team["contributor"], team["reviewer"]
    sys = new_item(c, project, "system_requirement", "R")
    stk = new_item(c, project, "stakeholder_requirement", "S")
    c.post(f"/projects/{project}/items/{sys['key']}/transitions/submit", {})
    err = _link(c, project, "derives_from", sys["key"], stk["key"], expect=423)
    assert err["error"]["code"] == "locked"
    # relates_to is allowed on frozen sources by configuration
    _link(c, project, "relates_to", sys["key"], stk["key"])
    approve(sys["key"], project, c, r)


def test_impact_analysis(team, project):
    c = team["contributor"]
    stk = new_item(c, project, "stakeholder_requirement", "Monitor pressure")
    sys = new_item(c, project, "system_requirement", "Measure pressure")
    mrq = new_item(c, project, "element_requirement", "Sensor cell range")
    el = new_item(c, project, "system_element", "Sensor unit", fields={"level": "subsystem"})
    product = new_item(c, project, "system_element", "Transmitter", fields={"level": "product"})
    tc = new_item(c, project, "test_case", "Range test")
    _link(c, project, "derives_from", sys["key"], stk["key"])
    _link(c, project, "derives_from", mrq["key"], sys["key"])
    _link(c, project, "satisfies", el["key"], mrq["key"])
    _link(c, project, "verifies", tc["key"], sys["key"])
    _link(c, project, "contains", product["key"], el["key"], attributes={"quantity": 1})
    impact = c.get(f"/projects/{project}/items/{stk['key']}/impact")
    keys = {r["item"]["key"]: r for r in impact["impacted"]}
    assert set(keys) == {sys["key"], mrq["key"], el["key"], tc["key"], product["key"]}
    assert keys[sys["key"]]["depth"] == 1 and keys[el["key"]]["depth"] == 3
    assert keys[product["key"]]["relation"] == "where_used"


def test_trace_matrix(team, project):
    c = team["contributor"]
    s1 = new_item(c, project, "system_requirement", "R1")
    new_item(c, project, "system_requirement", "R2")
    t1 = new_item(c, project, "test_case", "T1")
    _link(c, project, "verifies", t1["key"], s1["key"])
    m = c.get(f"/projects/{project}/trace-matrix?rows=system_requirement&cols=test_case")
    assert len(m["rows"]) == 2 and len(m["cols"]) == 1 and len(m["cells"]) == 1


def test_cross_project_link_requires_access(team, project, admin, make_user):
    admin.post("/projects", {"key": "PLAT", "name": "Platform", "template": "systems_engineering"})
    module = new_item(admin, "PLAT", "system_element", "Common electronics", fields={"level": "module"})
    product = new_item(team["contributor"], project, "system_element", "Product", fields={"level": "product"})
    _link(team["contributor"], project, "contains", product["key"], f"PLAT:{module['key']}", expect=404)
    admin.put("/projects/PLAT/members", {"user_id": team["users"]["contributor"]["id"], "role": "viewer"})
    _link(team["contributor"], project, "contains", product["key"], f"PLAT:{module['key']}")
    tree = team["contributor"].get(f"/projects/{project}/items/{product['key']}/tree")
    assert tree["children"][0]["project_key"] == "PLAT"


def test_link_attributes_and_delete(team, project):
    c = team["contributor"]
    p = new_item(c, project, "system_element", "P", fields={"level": "product"})
    m = new_item(c, project, "system_element", "M", fields={"level": "module"})
    link = _link(c, project, "contains", p["key"], m["key"], attributes={"quantity": 2})
    c.patch(f"/projects/{project}/links/{link['id']}", {"attributes": {"quantity": "x"}}, expect=422)
    updated = c.patch(f"/projects/{project}/links/{link['id']}", {"attributes": {"quantity": 3}, "applicability": "HART"})
    assert updated["id"] != link["id"]  # links are versioned: the old row is closed, a new one carries the change
    tree = c.get(f"/projects/{project}/items/{p['key']}/tree")
    assert tree["children"][0]["link"]["attributes"]["quantity"] == 3
    c.delete(f"/projects/{project}/links/{link['id']}", expect=404)
    c.delete(f"/projects/{project}/links/{updated['id']}")
    c.delete(f"/projects/{project}/links/{updated['id']}", expect=404)
