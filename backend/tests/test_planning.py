"""Plans 2.0 (hierarchy, estimates, capacity, roll-up, burn-down), timeline (dependency types with lag, slack,
critical path, conflicts, baseline comparison, auto-scheduling) and Kanban boards."""

from conftest import approve, new_item


def _link(api, project, type_, source, target, expect=201, **attributes):
    return api.post(f"/projects/{project}/links", {"type": type_, "source": source, "target": target,
                                                   "attributes": attributes}, expect=expect)


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


def test_dependency_types_lag_and_auto_schedule(team, project):
    c, v = team["contributor"], team["viewer"]
    p = f"/projects/{project}"

    def task(title, start, due, **fields):
        return new_item(c, project, "task", title, fields={"start_date": start, "due_date": due, **fields})["key"]

    a = task("A", "2026-11-02", "2026-11-06")                         # Mon - Fri
    b = task("B finish-to-start +2", "2026-11-09", "2026-11-13")      # needs to start after Tue 11-10
    cc = task("C start-to-start +1", "2026-11-03", "2026-11-04")      # ok: starts Tue
    d = task("D finish-to-finish", "2026-11-02", "2026-11-05")        # finishes a day before A
    e = task("E start-to-finish", "2026-10-26", "2026-10-30")         # ok: finishes the day before A starts
    f = task("F finish-to-start", "2026-11-16", "2026-11-20")         # a week of float
    g = task("G started", "2026-11-02", "2026-11-03", progress=50)    # in progress: keeps its dates
    _link(c, project, "depends_on", b, a, dependency_type="fs", lag=2)
    _link(c, project, "depends_on", cc, a, dependency_type="ss", lag=1)
    _link(c, project, "depends_on", d, a, dependency_type="ff")
    _link(c, project, "depends_on", e, a, dependency_type="sf")
    _link(c, project, "depends_on", f, a)
    _link(c, project, "depends_on", g, a)
    _link(c, project, "depends_on", g, b, expect=422, dependency_type="xx")
    _link(c, project, "depends_on", g, b, expect=422, lag="soon")
    tl = c.get(f"{p}/timeline")
    rows = {r["key"]: r for r in tl["rows"]}
    assert tl["dependency_types"] is True
    assert rows[f]["dependencies"][0] | {"link_id": None} == {"key": a, "type": "fs", "lag": 0, "link_id": None}
    assert rows[b]["dependencies"][0]["type"] == "fs" and rows[b]["dependencies"][0]["lag"] == 2
    conflicts = {x["item"]: x for x in tl["conflicts"]}
    assert set(conflicts) == {b, d, g} and conflicts[d]["type"] == "ff"
    assert "finish-to-finish" in conflicts[d]["message"] and "lag +2" in conflicts[b]["message"]
    # slack against the project finish (F ends last): A could slip 3 working days before B pushes the finish;
    # the violated dependencies are conflicts, not slack
    assert rows[a]["slack"] == 3 and not rows[a]["critical"] and rows[f]["slack"] == 0 and rows[f]["critical"]
    # auto-schedule: the preview moves B and D later, the started task stays and keeps its conflict
    v.post(f"{p}/timeline/schedule", {}, expect=403)
    preview = c.post(f"{p}/timeline/schedule", {"mode": "push"})
    moves = {m["key"]: m for m in preview["moves"]}
    assert preview["dry_run"] and set(moves) == {b, d}
    assert moves[b]["start_date"] == ["2026-11-09", "2026-11-11"] and moves[b]["due_date"][1] == "2026-11-17"
    assert moves[d]["due_date"] == ["2026-11-05", "2026-11-06"] and moves[d]["shift"] == 1
    assert [x["item"] for x in preview["remaining_conflicts"]] == [g]
    assert "already started" in preview["remaining_conflicts"][0]["message"]
    assert c.get(f"{p}/items/{b}")["fields"]["start_date"] == "2026-11-09"  # nothing saved by the preview
    applied = c.post(f"{p}/timeline/schedule", {"mode": "push", "dry_run": False})
    assert applied["summary"] == {"ok": 2, "skipped": 0}
    assert c.get(f"{p}/items/{b}")["fields"]["start_date"] == "2026-11-11"
    assert [x["item"] for x in c.get(f"{p}/timeline")["conflicts"]] == [g]
    # as soon as possible pulls F in to the Monday after A; push alone leaves the float
    assert c.post(f"{p}/timeline/schedule", {"mode": "push"})["moves"] == []
    asap = {m["key"]: m for m in c.post(f"{p}/timeline/schedule", {"mode": "asap"})["moves"]}
    assert asap[f]["start_date"] == ["2026-11-16", "2026-11-09"] and asap[f]["shift"] == -5 and cc not in asap
    # limited to one plan: only work planned there moves
    rel = new_item(c, project, "release", "R", fields={"start_date": "2026-11-02", "due_date": "2026-12-18"})["key"]
    _link(c, project, "planned_in", f, rel)
    assert {m["key"] for m in c.post(f"{p}/timeline/schedule", {"mode": "asap", "plan": rel})["moves"]} == {f}
    c.post(f"{p}/timeline/schedule", {"mode": "later"}, expect=422)


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
