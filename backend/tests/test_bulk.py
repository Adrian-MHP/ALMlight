"""Bulk edit: dry run, per-item skipping (frozen, missing field, impossible transition), owner, transitions with
e-signature, planning and moving between releases, links, watching, deletion and permissions."""

from conftest import new_item


def _bulk(api, project, expect=200, **body):
    return api.post(f"/projects/{project}/items/bulk", body, expect=expect)


def test_bulk_update_dry_run_and_skips(team, project):
    c, v, m = team["contributor"], team["viewer"], team["manager"]
    p = f"/projects/{project}"
    reqs = [new_item(c, project, "system_requirement", f"Req {i}", fields={"priority": "could"})["key"] for i in range(4)]
    tc = new_item(c, project, "test_case", "A test")["key"]
    c.post(f"{p}/items/{reqs[3]}/transitions/submit", {})  # in review: frozen
    dry = _bulk(c, project, keys=reqs + [tc], action="update", fields={"priority": "must"})
    assert dry["dry_run"] and dry["summary"] == {"ok": 3, "skipped": 2}
    by_key = {r["key"]: r for r in dry["results"]}
    assert "frozen" in by_key[reqs[3]]["message"] and "has no field priority" in by_key[tc]["message"]
    assert c.get(f"{p}/items/{reqs[0]}")["fields"]["priority"] == "could"  # nothing changed
    done = _bulk(c, project, keys=reqs + [tc], action="update", fields={"priority": "must"}, dry_run=False)
    assert done["summary"] == {"ok": 3, "skipped": 2}
    item = c.get(f"{p}/items/{reqs[0]}")
    assert item["fields"]["priority"] == "must" and item["version"] == "A.2"
    again = _bulk(c, project, keys=reqs[:3], action="update", fields={"priority": "must"}, dry_run=False)
    assert again["summary"] == {"unchanged": 3}
    # owner (also on frozen items), selection by query language
    mia = team["users"]["manager"]["id"]
    res = _bulk(c, project, query={"ql": "type:system_requirement"}, action="update", owner_id=mia, set_owner=True,
                dry_run=False)
    assert res["total"] == 4 and res["summary"] == {"ok": 4}
    assert c.get(f"{p}/items/{reqs[3]}")["owner"]["username"] == "mia"
    _bulk(v, project, keys=reqs, action="update", fields={"priority": "should"}, dry_run=False, expect=403)
    _bulk(c, project, keys=reqs, action="update", expect=422)  # nothing to change
    _bulk(c, project, keys=["NOPE-1"], action="update", fields={"priority": "must"}, expect=404)
    _bulk(c, project, action="update", fields={"priority": "must"}, expect=422)  # no selection
    del m


def test_bulk_transitions_planning_links_watch_delete(team, project):
    c, v, m = team["contributor"], team["viewer"], team["manager"]
    p = f"/projects/{project}"
    reqs = [new_item(c, project, "system_requirement", f"Req {i}")["key"] for i in range(3)]
    c.post(f"{p}/items/{reqs[2]}/transitions/submit", {})
    res = _bulk(c, project, keys=reqs, action="transition", transition="submit", dry_run=False)
    assert res["summary"] == {"ok": 2, "skipped": 1} and "not possible" in res["results"][2]["message"]
    assert all(c.get(f"{p}/items/{k}")["lifecycle"]["state"] == "in_review" for k in reqs)
    # approval transitions request approvals per item
    res = _bulk(c, project, keys=reqs, action="transition", transition="approve", dry_run=False)
    assert res["summary"] == {"ok": 3} and res["results"][0]["message"] == "approval requested"
    # e-signature: checked once, wrong password refuses the whole run
    els = [new_item(c, project, "system_element", f"Part {i}")["key"] for i in range(2)]
    for k in els:
        c.post(f"{p}/items/{k}/transitions/freeze", {})
    release_t = next(t for t in c.get(f"{p}/items/{els[0]}/transitions") if t["key"] == "release")
    if release_t["signature"]:
        _bulk(m, project, keys=els, action="transition", transition="release", password="wrong", dry_run=False,
              expect=403)
    # planning, moving between releases, unplanning
    r1 = new_item(c, project, "release", "R1")["key"]
    r2 = new_item(c, project, "release", "R2")["key"]
    res = _bulk(c, project, keys=reqs, action="plan", release=r1, dry_run=False)
    assert res["summary"] == {"ok": 3}
    assert len(c.get(f"{p}/plans/{r1}")["items"]) == 3
    res = _bulk(c, project, keys=reqs[:2], action="plan", release=r2, from_release=r1, dry_run=False)
    assert res["summary"] == {"ok": 2} and res["results"][0]["message"] == f"moved to {r2}"
    assert len(c.get(f"{p}/plans/{r1}")["items"]) == 1 and len(c.get(f"{p}/plans/{r2}")["items"]) == 2
    assert _bulk(c, project, keys=reqs[:2], action="unplan", release=r2, dry_run=False)["summary"] == {"ok": 2}
    _bulk(c, project, keys=reqs, action="plan", release=reqs[0], expect=422)  # not a release
    # links: one test case verifies all selected requirements
    tc = new_item(c, project, "test_case", "Covers all")["key"]
    res = _bulk(c, project, keys=reqs, action="link", link_type="verifies", link_dir="in", target=tc, dry_run=False)
    assert res["summary"] == {"ok": 3}
    assert len([lk for lk in c.get(f"{p}/items/{tc}/links") if lk["type"] == "verifies"]) == 3
    # watching is allowed for viewers
    assert _bulk(v, project, keys=reqs, action="watch", dry_run=False)["summary"] == {"ok": 3}
    assert _bulk(v, project, keys=reqs, action="watch", dry_run=False)["summary"] == {"unchanged": 3}
    assert len(v.get("/subscriptions")) == 3
    # deletion needs a manager; nothing was released, so all go to the recycle bin
    drafts = [new_item(c, project, "system_requirement", f"Temp {i}")["key"] for i in range(2)]
    _bulk(c, project, keys=drafts, action="delete", dry_run=False, expect=403)
    assert _bulk(m, project, keys=drafts, action="delete", dry_run=False)["summary"] == {"ok": 2}
    c.get(f"{p}/items/{drafts[0]}", expect=404)


def test_bulk_change_notifies_owner_once(team, project):
    c, m = team["contributor"], team["manager"]
    p = f"/projects/{project}"
    reqs = [new_item(c, project, "system_requirement", f"Req {i}")["key"] for i in range(7)]
    _bulk(m, project, keys=reqs, action="update", fields={"priority": "must"}, dry_run=False)
    notes = c.get("/notifications")
    assert notes["unread"] == 1 and notes["items"][0]["kind"] == "digest"
    assert "7 changes" in notes["items"][0]["title"]
    del p


def test_live_events_wait_for_the_real_commit(team, project):
    """Savepoint commits inside a transaction must not publish live events (they may still be rolled back)."""
    from almlight.core import events

    c = team["contributor"]
    reqs = [new_item(c, project, "system_requirement", f"Req {i}")["key"] for i in range(3)]
    published = []
    original = events.bus.publish
    events.bus.publish = lambda evs: published.append([e.get("type") for e in evs])
    try:
        _bulk(c, project, keys=reqs, action="update", fields={"priority": "must"}, dry_run=True)
        assert published == []  # dry run: savepoints committed, outer transaction rolled back -> nothing
        _bulk(c, project, keys=reqs, action="update", fields={"priority": "must"}, dry_run=False)
        assert len(published) == 1  # one batch, after the real commit
    finally:
        events.bus.publish = original
