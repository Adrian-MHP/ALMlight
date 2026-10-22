from conftest import approve, new_item


def test_baseline_and_compare(team, project):
    c, r = team["contributor"], team["reviewer"]
    a = new_item(c, project, "system_requirement", "A")
    b = new_item(c, project, "system_requirement", "B")
    c.post(f"/projects/{project}/links", {"type": "derives_from", "source": a["key"], "target": b["key"]})
    c.post(f"/projects/{project}/baselines", {"name": "x"}, expect=403)  # needs reviewer
    bl1 = r.post(f"/projects/{project}/baselines", {"name": "PDR"}, expect=201)
    assert bl1["item_count"] == 2 and bl1["link_count"] == 1
    c.patch(f"/projects/{project}/items/{a['key']}", {"title": "A changed"})
    new_item(c, project, "system_requirement", "C")
    cmp = c.get(f"/projects/{project}/baselines/{bl1['id']}/compare")
    assert [x["key"] for x in cmp["items"]["changed"]] == [a["key"]]
    assert cmp["items"]["changed"][0]["from_version"] == "A.1"
    assert len(cmp["items"]["added"]) == 1 and cmp["items"]["unchanged"] == 1
    bl2 = r.post(f"/projects/{project}/baselines", {"name": "CDR"}, expect=201)
    cmp2 = c.get(f"/projects/{project}/baselines/{bl1['id']}/compare?to={bl2['id']}")
    assert cmp2["to"]["name"] == "CDR" and len(cmp2["items"]["changed"]) == 1
    detail = c.get(f"/projects/{project}/baselines/{bl1['id']}")
    snap = {i["key"]: i for i in detail["items"]}
    assert snap[a["key"]]["version"] == "A.1" and snap[a["key"]]["current_version"] == "A.2"
    r.post(f"/projects/{project}/baselines", {"name": "x", "revision_rule": "magic"}, expect=422)


def test_released_revision_rule(team, project):
    c, r = team["contributor"], team["reviewer"]
    fn = new_item(c, project, "function", "F1")
    new_item(c, project, "function", "F2")  # never released -> not in a 'released' baseline
    c.post(f"/projects/{project}/items/{fn['key']}/transitions/freeze", {})
    approve(fn["key"], project, c, r, transition="release")
    c.post(f"/projects/{project}/items/{fn['key']}/revise", {})
    c.patch(f"/projects/{project}/items/{fn['key']}", {"title": "F1 rev B"})
    bl = r.post(f"/projects/{project}/baselines", {"name": "Released", "revision_rule": "released"}, expect=201)
    detail = c.get(f"/projects/{project}/baselines/{bl['id']}")
    assert [(i["key"], i["version"], i["state"]) for i in detail["items"]] == [(fn["key"], "A.1", "released")]


def test_scoped_baseline(team, project):
    c, r = team["contributor"], team["reviewer"]
    spec = new_item(c, project, "specification", "Spec")
    inside = new_item(c, project, "system_requirement", "In", parent=spec["key"])
    new_item(c, project, "system_requirement", "Out")
    bl = r.post(f"/projects/{project}/baselines", {"name": "Spec v1", "scope": spec["key"]}, expect=201)
    assert bl["item_count"] == 2 and bl["scope"] == spec["key"]
    c.patch(f"/projects/{project}/items/{inside['key']}", {"title": "In changed"})
    cmp = c.get(f"/projects/{project}/baselines/{bl['id']}/compare")
    assert [x["key"] for x in cmp["items"]["changed"]] == [inside["key"]] and cmp["items"]["added"] == []


def _feature(api, project, code, title, parent=None, **fields):
    return new_item(api, project, "feature", title, fields={"code": code, **fields}, parent=parent)


def test_feature_model_and_variants(team, project):
    c = team["contributor"]
    p = f"/projects/{project}"
    root = _feature(c, project, "SENSOR", "Sensor family", feature_kind="mandatory", group="none")
    out = _feature(c, project, "OUTPUT", "Output signal", parent=root["key"], feature_kind="mandatory",
                   group="alternative")
    _feature(c, project, "OUT_420", "4-20 mA", parent=out["key"])
    hart = _feature(c, project, "OUT_HART", "4-20 mA + HART", parent=out["key"])
    sil = _feature(c, project, "SIL2", "SIL 2", parent=root["key"])
    c.post(f"{p}/links", {"type": "requires", "source": sil["key"], "target": hart["key"]})

    model = c.get(f"{p}/variants/feature-model")
    assert model["roots"][0]["code"] == "SENSOR"
    assert [x["code"] for x in model["roots"][0]["children"][0]["children"]] == ["OUT_420", "OUT_HART"]

    ok = c.post(f"{p}/variants/validate", {"selection": ["SENSOR", "OUTPUT", "OUT_HART", "SIL2"]})
    assert ok == {"valid": True, "errors": []}
    bad = c.post(f"{p}/variants/validate", {"selection": ["SENSOR", "OUTPUT", "OUT_420", "OUT_HART", "SIL2", "X"]})
    text = " ".join(bad["errors"])
    assert "exactly one" in text and "Unknown feature 'X'" in text
    bad2 = c.post(f"{p}/variants/validate", {"selection": ["SENSOR", "OUTPUT", "OUT_420", "SIL2"]})
    assert "'SIL2' requires 'OUT_HART'" in bad2["errors"]
    missing = c.post(f"{p}/variants/validate", {"selection": []})
    assert any("Mandatory feature 'SENSOR'" in e for e in missing["errors"])

    always = new_item(c, project, "system_requirement", "Measure pressure")
    hart_req = new_item(c, project, "system_requirement", "HART protocol", applicability="OUT_HART")
    sil_req = new_item(c, project, "system_requirement", "Safety function", applicability="SIL2 and OUT_HART")
    var = new_item(c, project, "variant", "Basic analog",
                   fields={"selection": ["SENSOR", "OUTPUT", "OUT_420"]})
    resolved = c.get(f"{p}/variants/{var['key']}/resolve")
    included = {i["key"] for i in resolved["included"]}
    assert always["key"] in included and hart_req["key"] not in included and sil_req["key"] not in included
    assert resolved["errors"] == []
    full = c.post(f"{p}/variants/configure", {"selection": ["SENSOR", "OUTPUT", "OUT_HART", "SIL2"]})
    assert {always["key"], hart_req["key"], sil_req["key"]} <= {i["key"] for i in full["included"]}

    check = c.post(f"{p}/variants/check-expression", {"expression": "OUT_HART and NOPE"})
    assert check["valid"] is True and check["unknown"] == ["NOPE"]
    assert c.post(f"{p}/variants/check-expression", {"expression": "OUT_HART and"})["valid"] is False
    new_item(c, project, "system_requirement", "Typo", applicability="OUT_HRT")
    model = c.get(f"{p}/variants/feature-model")
    assert model["unknown_codes"][0]["missing"] == ["OUT_HRT"]
    assert model["variants"][0]["errors"] == []
