"""Query builder and query language: conditions on built-in and custom fields, links, planning, negation,
sorting, parse/format round trip, saved queries and export."""

import csv
import io
import json
import urllib.parse

from conftest import new_item


def _keys(api, project, **params):
    qs = urllib.parse.urlencode({**params, "limit": 500}, doseq=True)
    return {i["key"] for i in api.get(f"/projects/{project}/items?{qs}")["items"]}


def _cond(api, project, conditions, **params):
    return _keys(api, project, cond=json.dumps(conditions), **params)


def _ql(api, project, text, **params):
    return _keys(api, project, ql=text, **params)


def _setup(team, project):
    c, m = team["contributor"], team["manager"]
    a = new_item(c, project, "system_requirement", "Measure pressure", fields={"priority": "must", "safety_relevant": True})
    b = new_item(c, project, "system_requirement", "Report diagnostics", fields={"priority": "should"},
                 description="<p>NAMUR NE 107 status</p>")
    d = new_item(m, project, "system_requirement", "Withstand vibration", fields={"priority": "could"})
    tc = new_item(c, project, "test_case", "Range test")
    c.post(f"/projects/{project}/links", {"type": "verifies", "source": tc["key"], "target": a["key"]}, expect=201)
    r1 = new_item(c, project, "risk", "Burst", fields={"severity": 9, "occurrence": 5, "detection": 5})
    r2 = new_item(c, project, "risk", "Drift", fields={"severity": 4, "occurrence": 3, "detection": 2})
    rel = new_item(c, project, "release", "R1", fields={"start_date": "2026-01-01", "due_date": "2026-06-30"})
    rel2 = new_item(c, project, "release", "R2", fields={"start_date": "2026-07-01", "due_date": "2026-12-31"})
    c.post(f"/projects/{project}/links", {"type": "planned_in", "source": a["key"], "target": rel["key"]}, expect=201)
    c.patch(f"/projects/{project}/items/{d['key']}", {"owner_id": None})
    return {"a": a["key"], "b": b["key"], "d": d["key"], "tc": tc["key"], "r1": r1["key"], "r2": r2["key"],
            "rel": rel["key"], "rel2": rel2["key"]}


def test_conditions_on_builtin_custom_link_and_planning(team, project):
    c, v = team["contributor"], team["viewer"]
    k = _setup(team, project)
    req = {"field": "type", "op": "in", "values": ["system_requirement"]}
    assert _cond(c, project, [req]) == {k["a"], k["b"], k["d"]}
    assert _cond(c, project, [req, {"field": "field.priority", "op": "in", "values": ["must", "should"]}]) == {k["a"], k["b"]}
    # negation keeps items without a value (Polarion semantics)
    assert _cond(c, project, [req, {"field": "field.priority", "op": "in", "values": ["must"], "not": True}]) == {k["b"], k["d"]}
    assert _cond(c, project, [req, {"field": "field.safety_relevant", "op": "is", "values": [True]}]) == {k["a"]}
    # numbers: computed RPN ranges and exact values
    assert _cond(c, project, [{"field": "field.rpn", "op": "between", "values": [100, None]}]) == {k["r1"]}
    assert _cond(c, project, [{"field": "field.severity", "op": "in", "values": ["4"]}]) == {k["r2"]}
    # dates in custom fields
    assert _cond(c, project, [{"field": "field.due_date", "op": "between", "values": ["2026-06-01", "2026-07-31"]}]) == {k["rel"]}
    # traceability gaps and specific links
    gap = {"field": "link.verifies.in", "op": "exists", "values": [True], "not": True}
    assert _cond(c, project, [req, gap]) == {k["b"], k["d"]}
    assert _cond(c, project, [{"field": "link.verifies.out", "op": "in", "values": [k["a"]]}]) == {k["tc"]}
    # planning
    assert _cond(c, project, [req, {"field": "release", "op": "in", "values": [k["rel"]]}]) == {k["a"]}
    assert _cond(c, project, [req, {"field": "release", "op": "in", "values": ["none"]}]) == {k["b"], k["d"]}
    # users: me, user names, none; created relative dates; text
    assert _cond(c, project, [req, {"field": "owner", "op": "in", "values": ["none"]}]) == {k["d"]}
    assert _cond(c, project, [req, {"field": "author", "op": "in", "values": ["me"]}]) == {k["a"], k["b"]}
    assert _cond(v, project, [req, {"field": "author", "op": "in", "values": ["mia"]}]) == {k["d"]}
    assert _cond(c, project, [req, {"field": "created", "op": "between", "values": ["-1d", "today"]}]) == {k["a"], k["b"], k["d"]}
    assert _cond(c, project, [req, {"field": "created", "op": "between", "values": ["+1d", None]}]) == set()
    assert _cond(c, project, [{"field": "text", "op": "contains", "values": ["namur"]}]) == {k["b"]}
    assert _cond(c, project, [{"field": "category", "op": "in", "values": ["open"]}]) >= {k["r1"], k["r2"], k["rel"]}
    # watching
    v.put(f"/projects/{project}/items/{k['b']}/watch")
    assert _cond(v, project, [{"field": "watched", "op": "is", "values": [True]}]) == {k["b"]}
    assert _cond(c, project, [{"field": "watched", "op": "is", "values": [True]}]) == set()
    # validation
    bad = c.get(f"/projects/{project}/items?cond=" + urllib.parse.quote(json.dumps([{"field": "nope"}])), expect=422)
    assert "Unknown query field" in bad["error"]["message"]
    c.get(f"/projects/{project}/items?cond=" + urllib.parse.quote(json.dumps([{"field": "type", "op": "like"}])), expect=422)
    c.get(f"/projects/{project}/items?cond=not-json", expect=422)


def test_query_language_round_trip_and_sorting(team, project):
    c = team["contributor"]
    k = _setup(team, project)
    text = 'type:system_requirement priority:(must OR should) NOT link.verifies.in:* updated:[-30d TO *]'
    assert _ql(c, project, text) == {k["b"]}
    parsed = c.post(f"/projects/{project}/query/parse", {"text": text})
    assert parsed["q"] is None and [x["field"] for x in parsed["conditions"]] == ["type", "field.priority",
                                                                                   "link.verifies.in", "updated"]
    assert parsed["conditions"][2] == {"field": "link.verifies.in", "op": "exists", "values": [True], "not": True}
    formatted = c.post(f"/projects/{project}/query/format", parsed)["text"]
    assert formatted == "type:system_requirement priority:(must OR should) NOT link.verifies.in:* updated:[-30d TO *]"
    assert _ql(c, project, '-priority:must type:system_requirement') == {k["b"], k["d"]}
    assert _ql(c, project, 'type:risk rpn:[100 TO *]') == {k["r1"]}
    assert _ql(c, project, 'pressure') == {k["a"]}
    assert _ql(c, project, 'owner:none type:system_requirement') == {k["d"]}
    assert _ql(c, project, 'release:' + k["rel"]) == {k["a"]}
    for wrong, message in [("state:draft OR state:approved", "OR combines values"), ("color:red", "Unknown query field"),
                           ("rpn:[1 10]", "range"), ("priority:(must", "Expected ')'"), ("updated:[yesterday TO *]", "not a date")]:
        err = c.post(f"/projects/{project}/query/parse", {"text": wrong}, expect=422) if "date" not in message else \
            c.get(f"/projects/{project}/items?ql=" + urllib.parse.quote(wrong), expect=422)
        assert message in err["error"]["message"], (wrong, err)
    # sort by a custom number field (numeric, not alphabetic), descending
    ordered = [i["key"] for i in c.get(f"/projects/{project}/items?type=risk&sort=-field.rpn")["items"]]
    assert ordered == [k["r1"], k["r2"]]
    assert [i["key"] for i in c.get(f"/projects/{project}/items?type=risk&sort=field.rpn")["items"]] == [k["r2"], k["r1"]]
    c.get(f"/projects/{project}/items?sort=field.nope", expect=422)


def test_saved_query_and_export_with_conditions(team, project):
    c = team["contributor"]
    k = _setup(team, project)
    conds = [{"field": "type", "op": "in", "values": ["system_requirement"]},
             {"field": "link.verifies.in", "op": "exists", "values": [True], "not": True}]
    saved = c.post(f"/projects/{project}/queries", {"name": "Gaps", "query": {"conditions": conds,
                                                                                "columns": ["key", "title", "field.priority"]}},
                   expect=201)
    listed = next(x for x in c.get(f"/projects/{project}/queries") if x["id"] == saved["id"])
    assert listed["count"] == 2 and listed["query"]["columns"] == ["key", "title", "field.priority"]
    c.post(f"/projects/{project}/queries", {"name": "bad", "query": {"conditions": [{"field": "nope"}]}}, expect=422)
    rows = list(csv.reader(io.StringIO(c.get(f"/projects/{project}/export.csv?ql=" + urllib.parse.quote(
        "type:system_requirement NOT link.verifies.in:*")).content.decode("utf-8-sig"))))
    assert {r[0] for r in rows[1:]} == {k["b"], k["d"]}
