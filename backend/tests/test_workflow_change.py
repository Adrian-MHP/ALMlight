from conftest import approve, new_item


def _submit(api, project, key):
    return api.post(f"/projects/{project}/items/{key}/transitions/submit", {})


def test_review_freezes_content(team, project):
    c = team["contributor"]
    item = new_item(c, project, "system_requirement", "R")
    url = f"/projects/{project}/items/{item['key']}"
    opts = {t["key"]: t for t in c.get(f"{url}/transitions")}
    assert opts["submit"]["allowed"] is True
    assert _submit(c, project, item["key"])["state"] == "in_review"
    err = c.patch(url, {"title": "changed"}, expect=423)
    assert err["error"]["code"] == "locked"
    c.post(f"{url}/transitions/rework", {}, expect=422)  # comment required
    c.post(f"{url}/transitions/rework", {"comment": "needs a range"})
    assert c.patch(url, {"title": "changed"})["version"] == "A.2"


def test_approval_four_eyes_and_signature(team, project):
    c, r = team["contributor"], team["reviewer"]
    item = new_item(c, project, "system_requirement", "R")
    key = item["key"]
    _submit(c, project, key)
    req = c.post(f"/projects/{project}/items/{key}/transitions/approve", {})
    assert req["status"] == "approval_requested"
    rid = req["request_id"]
    # The contributor lacks the reviewer role; the requester may never approve their own request.
    c.post(f"/projects/{project}/approvals/{rid}/vote", {"decision": "approve", "password": "password-123"},
           expect=403)
    r.post(f"/projects/{project}/approvals/{rid}/vote", {"decision": "approve", "password": "wrong"}, expect=403)
    inbox = r.get("/approvals")
    assert [a["item_key"] for a in inbox] == [key] and inbox[0]["can_vote"] is True
    res = r.post(f"/projects/{project}/approvals/{rid}/vote", {"decision": "approve", "password": "password-123"})
    assert res == {"status": "approved", "state": "approved"}
    detail = c.get(f"/projects/{project}/items/{key}")
    assert detail["lifecycle"]["released"] is True and detail["released_version"] == "A.1"
    history = c.get(f"/projects/{project}/items/{key}/approvals")
    assert history[0]["votes"][0]["signed"] is True
    assert r.get("/approvals") == []


def test_self_approval_blocked_even_for_reviewer(team, project):
    r = team["reviewer"]
    item = new_item(r, project, "system_requirement", "R")
    _submit(r, project, item["key"])
    rid = r.post(f"/projects/{project}/items/{item['key']}/transitions/approve", {})["request_id"]
    err = r.post(f"/projects/{project}/approvals/{rid}/vote", {"decision": "approve", "password": "password-123"},
                 expect=403)
    assert "four-eyes" in err["error"]["message"]


def test_rejection_returns_to_draft(team, project):
    c, r = team["contributor"], team["reviewer"]
    item = new_item(c, project, "system_requirement", "R")
    _submit(c, project, item["key"])
    rid = c.post(f"/projects/{project}/items/{item['key']}/transitions/approve", {})["request_id"]
    r.post(f"/projects/{project}/approvals/{rid}/vote", {"decision": "reject", "password": "password-123"},
           expect=422)  # rejection needs a comment
    res = r.post(f"/projects/{project}/approvals/{rid}/vote",
                 {"decision": "reject", "comment": "unclear", "password": "password-123"})
    assert res["state"] == "draft"


def test_transition_from_wrong_state_and_duplicate_request(team, project):
    c = team["contributor"]
    item = new_item(c, project, "system_requirement", "R")
    c.post(f"/projects/{project}/items/{item['key']}/transitions/approve", {}, expect=409)
    c.post(f"/projects/{project}/items/{item['key']}/transitions/nope", {}, expect=404)
    _submit(c, project, item["key"])
    c.post(f"/projects/{project}/items/{item['key']}/transitions/approve", {})
    c.post(f"/projects/{project}/items/{item['key']}/transitions/approve", {}, expect=409)


def test_viewer_cannot_transition(team, project):
    item = new_item(team["contributor"], project, "system_requirement", "R")
    team["viewer"].post(f"/projects/{project}/items/{item['key']}/transitions/submit", {}, expect=403)


def _released_requirement(team, project, title="R"):
    c, r = team["contributor"], team["reviewer"]
    item = new_item(c, project, "system_requirement", title)
    _submit(c, project, item["key"])
    approve(item["key"], project, c, r)
    return item["key"]


def test_released_items_cannot_be_deleted_or_edited(team, project):
    key = _released_requirement(team, project)
    team["manager"].delete(f"/projects/{project}/items/{key}", expect=409)
    team["contributor"].patch(f"/projects/{project}/items/{key}", {"title": "x"}, expect=423)


def test_change_controlled_revision_needs_change_order(team, project):
    key = _released_requirement(team, project)
    err = team["contributor"].post(f"/projects/{project}/items/{key}/revise", {}, expect=422)
    assert err["error"]["details"]["change_order_required"] is True


def test_closed_loop_change(team, project):
    """Change request (approved by the CCB) -> change order -> revise -> release via the change order."""
    c, m = team["contributor"], team["manager"]
    req_key = _released_requirement(team, project, "Measure 0-10 bar")
    p = f"/projects/{project}"

    cr = new_item(c, project, "change_request", "Extend range to 16 bar", fields={"reason": "customer_request"})
    c.post(f"{p}/items/{cr['key']}/transitions/analyse", {})
    blocked = c.post(f"{p}/items/{cr['key']}/transitions/approve", {}, expect=409)
    assert "affected" in blocked["error"]["details"]["blocked_by"][0]
    c.post(f"{p}/links", {"type": "affects", "source": cr["key"], "target": req_key})
    approve(cr["key"], project, c, m)  # CCB decision by a manager
    assert c.get(f"{p}/items/{cr['key']}")["lifecycle"]["state"] == "approved"

    co = new_item(c, project, "change_order", "Implement 16 bar range")
    c.post(f"{p}/links", {"type": "implements", "source": co["key"], "target": cr["key"]})
    c.post(f"{p}/links", {"type": "affects", "source": co["key"], "target": req_key,
                          "attributes": {"action": "revise"}})
    # Revising under a CO that is not yet in work is refused.
    c.post(f"{p}/items/{req_key}/revise", {"change_order": co["key"]}, expect=409)
    c.post(f"{p}/items/{co['key']}/transitions/start_work", {})
    blocked = c.post(f"{p}/items/{co['key']}/transitions/submit", {}, expect=409)
    assert req_key in blocked["error"]["details"]["blocked_by"][0]

    revised = c.post(f"{p}/items/{req_key}/revise", {"change_order": co["key"], "change_note": "16 bar"})
    assert revised["version"] == "B.1" and revised["lifecycle"]["state"] == "draft"
    assert revised["change_order"] == co["key"] and revised["released_version"] == "A.1"
    edited = c.patch(f"{p}/items/{req_key}", {"title": "Measure 0-16 bar"})
    assert edited["version"] == "B.2" and edited["change_order"] == co["key"]

    c.post(f"{p}/items/{co['key']}/transitions/submit", {})
    approve(co["key"], project, c, m, transition="release")
    final = c.get(f"{p}/items/{req_key}")
    assert final["lifecycle"]["state"] == "approved"
    assert final["released_version"] == "B.2"
    events = c.get(f"{p}/items/{req_key}/workflow-events")
    assert events[0]["via"] == "change_order"
    versions = c.get(f"{p}/items/{req_key}/versions")
    assert [v["version"] for v in versions if v["released"]] == ["B.2"]


def test_revise_non_controlled_type(team, project):
    c, r = team["contributor"], team["reviewer"]
    fn = new_item(c, project, "function", "Acquire pressure")
    c.post(f"/projects/{project}/items/{fn['key']}/transitions/freeze", {})
    approve(fn["key"], project, c, r, transition="release")
    revised = c.post(f"/projects/{project}/items/{fn['key']}/revise", {})
    assert revised["version"] == "B.1" and revised["lifecycle"]["state"] == "in_work"
    c.post(f"/projects/{project}/items/{fn['key']}/revise", {}, expect=409)


def test_specification_release_guard(team, project):
    c, r = team["contributor"], team["reviewer"]
    spec = new_item(c, project, "specification", "System spec")
    req = new_item(c, project, "system_requirement", "R", parent=spec["key"])
    c.post(f"/projects/{project}/items/{spec['key']}/transitions/freeze", {})
    opts = {t["key"]: t for t in c.get(f"/projects/{project}/items/{spec['key']}/transitions")}
    assert opts["release"]["allowed"] is False
    assert req["key"] in opts["release"]["blocked_by"][0]
    c.post(f"/projects/{project}/items/{spec['key']}/transitions/release", {}, expect=409)
    _submit(c, project, req["key"])
    approve(req["key"], project, c, r)
    approve(spec["key"], project, c, r, transition="release")
    assert c.get(f"/projects/{project}/items/{spec['key']}")["lifecycle"]["state"] == "released"


def test_cancel_approval_request(team, project):
    c, r = team["contributor"], team["reviewer"]
    item = new_item(c, project, "system_requirement", "R")
    _submit(c, project, item["key"])
    rid = c.post(f"/projects/{project}/items/{item['key']}/transitions/approve", {})["request_id"]
    team["viewer"].post(f"/projects/{project}/approvals/{rid}/cancel", expect=403)
    c.post(f"/projects/{project}/approvals/{rid}/cancel")
    r.post(f"/projects/{project}/approvals/{rid}/vote", {"decision": "approve", "password": "password-123"},
           expect=403)
