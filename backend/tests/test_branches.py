from conftest import approve, new_item


def _spec(c, project):
    spec = new_item(c, project, "specification", "System spec")
    h = new_item(c, project, "heading", "1 Measurement", parent=spec["key"])
    r1 = new_item(c, project, "system_requirement", "Measure 0-10 bar", parent=h["key"], fields={"priority": "must"})
    r2 = new_item(c, project, "system_requirement", "Accuracy 0.1 %", parent=h["key"])
    stk = new_item(c, project, "stakeholder_requirement", "Monitor pressure")
    c.post(f"/projects/{project}/links", {"type": "derives_from", "source": r1["key"], "target": stk["key"]})
    return spec, h, r1, r2, stk


def _branch(c, project, spec_key, name="Variant X"):
    return c.post(f"/projects/{project}/items/{spec_key}/branch", {"name": name}, expect=201)


def _tree_keys(node):
    return [node["key"], *[k for ch in node["children"] for k in _tree_keys(ch)]]


def test_branch_copies_outline_and_traces(team, project):
    c = team["contributor"]
    p = f"/projects/{project}"
    spec, h, r1, r2, stk = _spec(c, project)
    br = _branch(c, project, spec["key"])
    assert br["source_root"] == spec["key"]
    tree = c.get(f"{p}/items/{br['branch_root']}/tree")
    assert tree["title"] == "Variant X"
    copied = tree["children"][0]["children"]
    assert [n["title"] for n in copied] == ["Measure 0-10 bar", "Accuracy 0.1 %"]
    assert copied[0]["key"] not in (r1["key"], r2["key"]) and copied[0]["fields"]["priority"] == "must"
    links = c.get(f"{p}/items/{copied[0]['key']}/links")
    assert any(lk["type"] == "derives_from" and lk["other"]["key"] == stk["key"] for lk in links)
    assert c.get(f"{p}/items/{spec['key']}/branches")[0]["branch_root"] == br["branch_root"]
    preview = c.get(f"{p}/branches/{br['id']}/preview")
    assert {pp["status"] for pp in preview["pairs"]} == {"unchanged"}


def test_merge_branch_changes_into_source(team, project):
    c = team["contributor"]
    p = f"/projects/{project}"
    spec, h, r1, r2, _ = _spec(c, project)
    br = _branch(c, project, spec["key"])
    tree = c.get(f"{p}/items/{br['branch_root']}/tree")
    b1 = tree["children"][0]["children"][0]["key"]
    c.patch(f"{p}/items/{b1}", {"title": "Measure 0-16 bar", "fields": {"priority": "should"}})
    preview = c.get(f"{p}/branches/{br['id']}/preview")
    changed = next(pp for pp in preview["pairs"] if pp["branch"] == b1)
    assert changed["status"] == "branch_changed" and {ch["field"] for ch in changed["changes"]} == {"title", "fields.priority"}
    res = c.post(f"{p}/branches/{br['id']}/merge", {"direction": "to_source"})
    assert res["updated"] == [r1["key"]]
    src = c.get(f"{p}/items/{r1['key']}")
    assert src["title"] == "Measure 0-16 bar" and src["fields"]["priority"] == "should" and src["version"] == "A.2"
    # After the merge both sides agree.
    assert {pp["status"] for pp in c.get(f"{p}/branches/{br['id']}/preview")["pairs"]} == {"unchanged"}


def test_source_changes_flow_to_branch_and_conflicts(team, project):
    c = team["contributor"]
    p = f"/projects/{project}"
    spec, h, r1, r2, _ = _spec(c, project)
    br = _branch(c, project, spec["key"])
    tree = c.get(f"{p}/items/{br['branch_root']}/tree")
    b1, b2 = (n["key"] for n in tree["children"][0]["children"])
    # r2 changes only in the source; r1 in both (title in source, description in branch); conflict on r1 title later.
    c.patch(f"{p}/items/{r2['key']}", {"description": "At reference conditions"})
    c.patch(f"{p}/items/{r1['key']}", {"title": "Measure 0-10 bar gauge"})
    c.patch(f"{p}/items/{b1}", {"description": "Variant X needs a vacuum range"})
    pv = {pp["branch"]: pp for pp in c.get(f"{p}/branches/{br['id']}/preview")["pairs"]}
    assert pv[b2]["status"] == "source_changed" and pv[b1]["status"] == "both_changed"
    res = c.post(f"{p}/branches/{br['id']}/merge", {"direction": "from_source"})
    assert set(res["updated"]) == {b1, b2}
    b1_now = c.get(f"{p}/items/{b1}")
    assert b1_now["title"] == "Measure 0-10 bar gauge" and b1_now["description"] == "Variant X needs a vacuum range"
    # Branch-only change is still pending for the source; now create a real conflict on the title.
    c.patch(f"{p}/items/{r1['key']}", {"title": "Source title"})
    c.patch(f"{p}/items/{b1}", {"title": "Branch title"})
    pv = {pp["branch"]: pp for pp in c.get(f"{p}/branches/{br['id']}/preview")["pairs"]}
    assert pv[b1]["status"] == "conflict"
    err = c.post(f"{p}/branches/{br['id']}/merge", {"direction": "to_source"}, expect=422)
    assert f"{b1}: title" in err["error"]["details"]["conflicts"]
    c.post(f"{p}/branches/{br['id']}/merge", {"direction": "to_source", "resolutions": {b1: {"title": "branch"}}})
    merged = c.get(f"{p}/items/{r1['key']}")
    assert merged["title"] == "Branch title" and merged["description"] == "Variant X needs a vacuum range"


def test_merge_respects_lifecycle_and_adds_new_items(team, project):
    c, r = team["contributor"], team["reviewer"]
    p = f"/projects/{project}"
    spec, h, r1, r2, _ = _spec(c, project)
    br = _branch(c, project, spec["key"])
    tree = c.get(f"{p}/items/{br['branch_root']}/tree")
    b_heading = tree["children"][0]["key"]
    b1 = tree["children"][0]["children"][0]["key"]
    new_item(c, project, "system_requirement", "Vacuum range", parent=b_heading)
    c.patch(f"{p}/items/{b1}", {"title": "Changed in branch"})
    c.post(f"{p}/items/{r1['key']}/transitions/submit", {})
    approve(r1["key"], project, c, r)  # the source requirement is now released (frozen)
    err = c.post(f"{p}/branches/{br['id']}/merge", {"direction": "to_source"}, expect=423)
    assert err["error"]["code"] == "locked"
    # All-or-nothing: the failed merge did not add the new requirement to the source either.
    assert len(c.get(f"{p}/items/{h['key']}/tree")["children"]) == 2
    # Merge only the new item; it is created below the corresponding source heading.
    added = c.get(f"{p}/branches/{br['id']}/preview")["added_in_branch"]
    assert added[0]["parent_in_source"] == h["key"]
    res = c.post(f"{p}/branches/{br['id']}/merge", {"direction": "to_source", "items": [added[0]["branch"]]})
    assert len(res["created"]) == 1 and res["updated"] == []
    titles = [n["title"] for n in c.get(f"{p}/items/{h['key']}/tree")["children"]]
    assert titles[-1] == "Vacuum range"
    assert c.get(f"{p}/branches/{br['id']}/preview")["added_in_branch"] == []


def test_branch_permissions_and_validation(team, project):
    spec, *_ = _spec(team["contributor"], project)
    team["viewer"].post(f"/projects/{project}/items/{spec['key']}/branch", {"name": "x"}, expect=403)
    team["contributor"].post(f"/projects/{project}/items/{spec['key']}/branch", {"name": " "}, expect=422)
    br = _branch(team["contributor"], project, spec["key"])
    team["contributor"].post(f"/projects/{project}/branches/{br['id']}/merge", {"direction": "sideways"}, expect=422)
    assert len(team["viewer"].get(f"/projects/{project}/branches")) == 1
