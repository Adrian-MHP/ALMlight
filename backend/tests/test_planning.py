"""Plans 2.0 (hierarchy, estimates, capacity, roll-up, burn-down), timeline (dependencies, slack, critical path,
conflicts, baseline comparison) and Kanban boards."""

from conftest import approve, new_item


def _link(api, project, type_, source, target, expect=201):
    return api.post(f"/projects/{project}/links", {"type": type_, "source": source, "target": target}, expect=expect)


def test_plan_hierarchy_estimates_capacity_and_rollup(team, project):
    c, r = team["contributor"], team["reviewer"]
    p = f"/projects/{project}"
    rel = new_item(c, project, "release", "R 1.0", fields={"capacity": 40, "start_date": "2026-01-05",
                                                           "due_date": "2026-03-27"})["key"]
    s1 = new_item(c, project, "release", "Sprint 1", fields={"kind": "iteration", "capacity": 20,
                                                             "start_date": "2026-01-05", "due_date": "2026-02-13"})["key"]
    s2 = new_item(c, project, "release", "Sprint 2", fields={"kind": "iteration", "capacity": 20,
                                                             "start_date": "2026-02-16", "due_date": "2026-03-27"})["key"]
    _link(c, project, "part_of", s1, rel)
    _link(c, project, "part_of", s2, rel)
    _link(c, project, "part_of", rel, s1, expect=(409, 422))  # plans form a tree, no cycles
    a = new_item(c, project, "system_requirement", "A", fields={"estimate": 8})["key"]
    b = new_item(c, project, "system_requirement", "B", fields={"estimate": 5})["key"]
    d = new_item(c, project, "system_requirement", "C", fields={"estimate": 3})["key"]
    _link(c, project, "planned_in", a, s1)
    _link(c, project, "planned_in", b, s2)
    _link(c, project, "planned_in", d, rel)
    c.post(f"{p}/items/{a}/transitions/submit", {})
    approve(a, project, c, r)
    top = c.get(f"{p}/plans/{rel}")
    assert top["total"] == 3 and top["done"] == 1 and top["estimate"] == 16 and top["estimate_done"] == 8
    assert top["progress"] == 0.5 and top["capacity"] == 40 and top["load"] == 0.4
    assert top["children"] == [s1, s2] and {x["key"] for x in top["child_plans"]} == {s1, s2}
    assert {i["key"]: i["plan"] for i in top["items"]} == {a: s1, b: s2, d: rel}
    assert top["burnup"][-1]["remaining_estimate"] in (8, 16)  # depending on whether today is inside the plan
    sprint = c.get(f"{p}/plans/{s1}")
    assert sprint["parent"] == rel and sprint["kind"] == "iteration" and sprint["progress"] == 1.0
    listed = {x["key"]: x for x in c.get(f"{p}/plans")["releases"]}
    assert listed[s2]["parent"] == rel and listed[rel]["children"] == [s1, s2] and listed[s2]["load"] == 0.25


def test_timeline_critical_path_conflicts_and_baseline(team, project):
    c, m = team["contributor"], team["manager"]
    p = f"/projects/{project}"
    rel = new_item(c, project, "release", "R1", fields={"start_date": "2026-11-02", "due_date": "2026-12-18"})["key"]
    t1 = new_item(c, project, "task", "Design", fields={"start_date": "2026-11-02", "due_date": "2026-11-06"})["key"]
    t2 = new_item(c, project, "task", "Build", fields={"start_date": "2026-11-09", "due_date": "2026-11-13"})["key"]
    t3 = new_item(c, project, "task", "Test", fields={"start_date": "2026-11-16", "due_date": "2026-11-20"})["key"]
    ms = new_item(c, project, "release", "Design freeze", fields={"kind": "milestone", "due_date": "2026-11-20"})["key"]
    t4 = new_item(c, project, "task", "Docs", fields={"start_date": "2026-11-02", "due_date": "2026-11-04",
                                                     "progress": 50})["key"]
    _link(c, project, "depends_on", t2, t1)
    _link(c, project, "depends_on", t3, t2)
    _link(c, project, "depends_on", ms, t3)
    _link(c, project, "depends_on", t1, t3, expect=(409, 422))  # no circular dependencies
    _link(c, project, "planned_in", t4, rel)
    tl = c.get(f"{p}/timeline")
    rows = {r["key"]: r for r in tl["rows"]}
    assert tl["enabled"] and rows[t2]["depends_on"] == [t1] and rows[t4]["parent"] == rel
    assert rows[ms]["kind"] == "milestone" and rows[ms]["start_date"] == "2026-11-20"
    assert {k for k, r in rows.items() if r["critical"]} == {t1, t2, t3, ms}
    assert rows[t4]["slack"] > 30 and rows[t4]["progress"] == 0.5 and not rows[t4]["critical"]
    assert tl["conflicts"] == []
    # baseline the schedule, then slip the build by a week: conflicts and negative slack appear
    bl = m.post(f"{p}/baselines", {"name": "Schedule baseline"})
    c.patch(f"{p}/items/{t2}", {"fields": {"start_date": "2026-11-16", "due_date": "2026-11-20"}})
    tl = c.get(f"{p}/timeline?baseline={bl['id']}")
    rows = {r["key"]: r for r in tl["rows"]}
    assert rows[t2]["baseline"] == {"start_date": "2026-11-09", "due_date": "2026-11-13"}
    assert rows[t2]["slack"] < 0 and rows[t1]["slack"] == 0
    assert [x["item"] for x in tl["conflicts"]] == [t3]
    c.post(f"{p}/items/{t1}/transitions/finish", {})
    assert {r["key"]: r for r in c.get(f"{p}/timeline")["rows"]}[t1]["progress"] == 1.0


def test_boards_crud_validation_and_sharing(team, project):
    c, v, m = team["contributor"], team["viewer"], team["manager"]
    p = f"/projects/{project}"
    cfg = {"types": ["system_requirement"], "columns_by": "state", "swimlanes_by": "owner", "wip": {"draft": 2},
           "card_fields": ["priority"], "conditions": [{"field": "field.priority", "op": "in", "values": ["must"]}]}
    b = c.post(f"{p}/boards", {"name": "Requirements", "shared": True, "config": cfg}, expect=201)
    assert b["config"]["wip"] == {"draft": 2} and b["can_edit"]
    for bad in ({"columns_by": "field.nope"}, {"columns_by": "field.rationale"}, {"columns_by": "owner",
                                                                                   "swimlanes_by": "owner"},
                {"types": ["unknown"]}, {"conditions": [{"field": "nope"}]}, {"wip": {"draft": -1}},
                {"card_fields": ["nope"]}):
        c.post(f"{p}/boards", {"name": "x", "config": {**cfg, **bad}}, expect=422)
    risk_board = c.post(f"{p}/boards", {"name": "Risks by level", "config": {"types": ["risk"],
                                                                              "columns_by": "field.risk_level"}},
                        expect=201)
    assert not risk_board["shared"]
    v.post(f"{p}/boards", {"name": "mine", "shared": True, "config": cfg}, expect=403)
    mine = v.post(f"{p}/boards", {"name": "mine", "config": cfg}, expect=201)
    names = {x["name"]: x for x in v.get(f"{p}/boards")}
    assert set(names) == {"Requirements", "mine"}  # c's personal risk board stays personal
    assert not names["Requirements"]["can_edit"]
    v.put(f"{p}/boards/{b['id']}", {"name": "hijack", "config": cfg}, expect=403)
    m.put(f"{p}/boards/{b['id']}", {"name": "Requirements (CCB)", "shared": True, "config": cfg})
    assert c.get(f"{p}/boards/{b['id']}")["name"] == "Requirements (CCB)"
    c.get(f"{p}/boards/{mine['id']}", expect=404)
    v.delete(f"{p}/boards/{b['id']}", expect=403)
    c.delete(f"{p}/boards/{b['id']}")
