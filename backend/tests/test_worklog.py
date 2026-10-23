"""Time recording (work records, spent/remaining, privacy, weekly timesheet), resource load per person and week, and
resource levelling."""

from datetime import UTC, datetime, timedelta

from conftest import new_item


def _today():
    return datetime.now(UTC).date()


def test_work_records_spent_remaining_and_privacy(team, project):
    c, r, m, v = team["contributor"], team["reviewer"], team["manager"], team["viewer"]
    p = f"/projects/{project}"
    today = _today()
    yesterday = (today - timedelta(days=1)).isoformat()
    t = new_item(c, project, "task", "Implement driver", fields={"estimate": 10})["key"]
    version = c.get(f"{p}/items/{t}")["version_no"]
    rec = c.post(f"{p}/items/{t}/work", {"day": today.isoformat(), "hours": 3, "comment": "Bring-up"}, expect=201)
    c.post(f"{p}/items/{t}/work", {"day": yesterday, "hours": 2.5}, expect=201)
    r.post(f"{p}/items/{t}/work", {"day": today.isoformat(), "hours": 1}, expect=201)
    v.post(f"{p}/items/{t}/work", {"day": today.isoformat(), "hours": 1}, expect=403)
    future = c.post(f"{p}/items/{t}/work", {"day": (today + timedelta(days=1)).isoformat(), "hours": 1}, expect=422)
    assert "not for the future" in future["error"]["message"]
    c.post(f"{p}/items/{t}/work", {"day": yesterday, "hours": 0}, expect=422)
    too_much = c.post(f"{p}/items/{t}/work", {"day": today.isoformat(), "hours": 22}, expect=422)
    assert "at most 24 h" in too_much["error"]["message"]
    # totals for everybody, own records for the author, all records for managers
    mine = c.get(f"{p}/items/{t}/work")
    assert (mine["estimate"], mine["spent"], mine["remaining"], mine["mine"]) == (10, 6.5, 3.5, 5.5)
    assert len(mine["records"]) == 2 and "by_user" not in mine and not mine["all_visible"]
    managed = m.get(f"{p}/items/{t}/work")
    assert len(managed["records"]) == 3 and managed["all_visible"]
    assert managed["by_user"][0]["user"]["username"] == "carla" and managed["by_user"][0]["hours"] == 5.5
    seen = v.get(f"{p}/items/{t}/work")
    assert seen["spent"] == 6.5 and seen["records"] == [] and not seen["can_record"]
    # change and delete: author or manager
    r.patch(f"{p}/work/{rec['id']}", {"hours": 4}, expect=403)
    changed = c.patch(f"{p}/work/{rec['id']}", {"hours": 4, "comment": "Bring-up done"})
    assert changed["hours"] == 4 and changed["comment"] == "Bring-up done"
    m.delete(f"{p}/work/{rec['id']}")
    assert c.get(f"{p}/items/{t}/work")["spent"] == 3.5
    # recording time does not create item versions; finished items have nothing remaining
    assert c.get(f"{p}/items/{t}")["version_no"] == version
    c.post(f"{p}/items/{t}/transitions/start", {})
    c.post(f"{p}/items/{t}/transitions/finish", {})
    assert c.get(f"{p}/items/{t}/work")["remaining"] == 0
    assert any(e["action"] == "work.recorded" for e in m.get(f"{p}/audit?action=work.recorded"))


def test_weekly_timesheet(team, project):
    c, m = team["contributor"], team["manager"]
    cu = team["users"]["contributor"]
    p = f"/projects/{project}"
    today = _today()
    monday = today - timedelta(days=today.weekday())
    a = new_item(c, project, "system_requirement", "Measure pressure")["key"]
    open_task = new_item(c, project, "task", "Write test spec", owner_id=cu["id"],
                         fields={"start_date": monday.isoformat(), "due_date": (monday + timedelta(days=4)).isoformat(),
                                 "estimate": 8})["key"]
    c.put(f"{p}/timesheet", {"item": a, "day": today.isoformat(), "hours": 1.5})
    c.put(f"{p}/timesheet", {"item": a, "day": today.isoformat(), "hours": 2})  # replaces, does not add
    ts = c.get(f"{p}/timesheet?week={today.isoformat()}")
    rows = {x["key"]: x for x in ts["rows"]}
    assert ts["week"] == monday.isoformat() and len(ts["days"]) == 7 and ts["editable"]
    assert rows[a]["hours"] == {today.isoformat(): 2} and rows[a]["total"] == 2
    assert open_task in rows and rows[open_task]["total"] == 0 and rows[open_task]["remaining"] == 8
    assert ts["totals"][today.isoformat()] == 2 and ts["total"] == 2 and ts["capacity"] == 40
    c.put(f"{p}/timesheet", {"item": a, "day": today.isoformat(), "hours": 0})
    assert a not in {x["key"] for x in c.get(f"{p}/timesheet")["rows"]}
    c.put(f"{p}/timesheet", {"item": a, "day": (today + timedelta(days=1)).isoformat(), "hours": 1}, expect=422)
    # other people's weeks: managers only, read-only
    c.get(f"{p}/timesheet?user=mia", expect=403)
    theirs = m.get(f"{p}/timesheet?user=carla")
    assert theirs["user"]["username"] == "carla" and not theirs["editable"]
    m.get(f"{p}/timesheet?user=nobody", expect=404)


def test_resource_load_capacity_and_levelling(team, project):
    c, m, v = team["contributor"], team["manager"], team["viewer"]
    cu = team["users"]["contributor"]
    p = f"/projects/{project}"
    today = _today()
    mon = today - timedelta(days=today.weekday()) + timedelta(days=7)  # next week: everything lies ahead

    def d(n):
        return (mon + timedelta(days=n)).isoformat()

    def task(title, start, due, hours, owner=cu["id"]):
        return new_item(c, project, "task", title, owner_id=owner,
                        fields={"start_date": d(start), "due_date": d(due), "estimate": hours})["key"]

    a = task("Driver", 0, 4, 40)       # 8 h a day
    b = task("Docs", 0, 4, 20)         # 4 h a day on top: 150 %
    x = task("Test", 7, 11, 10)        # after the docs
    u = task("Unassigned", 0, 1, 6)
    c.patch(f"{p}/items/{u}", {"owner_id": None})
    c.post(f"{p}/links", {"type": "depends_on", "source": x, "target": b}, expect=201)
    res = c.get(f"{p}/resources?start={d(0)}&weeks=3")
    assert res["weeks"] == [d(0), d(7), d(14)]
    carla = next(pp for pp in res["people"] if pp["user"]["username"] == "carla")
    w0 = carla["weeks"][0]
    assert (w0["planned"], w0["capacity"], w0["load"], carla["overloaded"]) == (60, 40, 1.5, 1)
    assert {i["key"] for i in w0["items"]} == {a, b} and carla["weeks"][1]["planned"] == 10
    assert res["unassigned"][0]["planned"] == 6
    # capacity follows the member's hours per day
    m.put(f"{p}/members", {"user_id": cu["id"], "role": "contributor", "hours_per_day": 6})
    assert next(pp for pp in c.get(f"{p}/resources?start={d(0)}")["people"]
                if pp["user"]["username"] == "carla")["weeks"][0]["capacity"] == 30
    assert next(x for x in m.get(f"{p}/members") if x["username"] == "carla")["hours_per_day"] == 6
    m.put(f"{p}/members", {"user_id": cu["id"], "role": "contributor", "hours_per_day": 8})
    m.put(f"{p}/members", {"user_id": cu["id"], "role": "contributor", "hours_per_day": 30}, expect=422)
    # levelling: the docs feed the test (no float) and keep their dates; the driver work has float and moves to the
    # next week, the test follows it; nothing else moves
    v.post(f"{p}/resources/level", {}, expect=403)
    preview = c.post(f"{p}/resources/level", {})
    moves = {mv["key"]: mv for mv in preview["moves"]}
    assert set(moves) == {a, x} and preview["dry_run"]
    assert moves[a]["start_date"] == [d(0), d(7)] and moves[x]["start_date"] == [d(7), d(14)]
    assert preview["remaining_overloads"] == [] and preview["remaining_conflicts"] == []
    assert c.get(f"{p}/items/{a}")["fields"]["start_date"] == d(0)
    c.post(f"{p}/resources/level", {"dry_run": False})
    carla = next(pp for pp in c.get(f"{p}/resources?start={d(0)}&weeks=3")["people"]
                 if pp["user"]["username"] == "carla")
    assert [w["planned"] for w in carla["weeks"]] == [20, 40, 10] and carla["overloaded"] == 0
    assert c.get(f"{p}/timeline")["conflicts"] == []
    # recorded time reduces the remaining work that is planned
    c.post(f"{p}/items/{a}/work", {"day": today.isoformat(), "hours": 10}, expect=201)
    carla = next(pp for pp in c.get(f"{p}/resources?start={d(7)}&weeks=1")["people"]
                 if pp["user"]["username"] == "carla")
    assert carla["weeks"][0]["planned"] == 30
