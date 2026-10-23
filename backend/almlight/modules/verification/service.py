"""Verification: test runs and records, CI result import, verification status, coverage and maturity.

Verification status of a requirement or element (from its incoming ``verifies`` links):
  * ``passed``  — every verifying test case passed in its latest execution, on its current version,
                  and no verifies-link is suspect
  * ``retest``  — results exist but are outdated (test case changed, or the verified item changed)
  * ``failed``  — at least one latest result failed or is blocked
  * ``not_run`` — test cases exist but have never been executed
  * ``none``    — no test case verifies the item
"""

from __future__ import annotations

import re
import uuid
from collections import defaultdict, deque
from typing import Any

from defusedxml import ElementTree as SafeET
from sqlalchemy import select
from sqlalchemy.orm import Session

from almlight.core.db import utcnow
from almlight.core.errors import Conflict, NotFound, ValidationFailed
from almlight.modules.audit import service as audit
from almlight.modules.identity.models import User
from almlight.modules.items import service as items_svc
from almlight.modules.items.lifecycle import ensure_editable, state_def
from almlight.modules.items.models import Item
from almlight.modules.links.models import Link
from almlight.modules.projects.models import Project
from almlight.modules.verification.models import RESULTS, TestRecord
from almlight.modules.workflow.models import WorkflowEvent


def _verification_link_types(project: Project) -> list[str]:
    key = project.model.semantics.verifies_link
    return [key] if project.model.link_type(key) else []


def records_of(db: Session, run: Item) -> list[tuple[TestRecord, Item]]:
    rows = db.execute(
        select(TestRecord, Item).join(Item, Item.id == TestRecord.test_case_id)
        .where(TestRecord.run_id == run.id).order_by(Item.seq)
    ).all()
    return [(r, tc) for r, tc in rows]


def add_test_cases(db: Session, project: Project, actor: User, run: Item, test_cases: list[Item]) -> int:
    ensure_editable(project, run)
    existing = {r.test_case_id for r, _ in records_of(db, run)}
    added = 0
    for tc in test_cases:
        if tc.id in existing:
            continue
        if tc.type_key not in project.model.semantics.test_case_types:
            raise ValidationFailed(f"{tc.key} is not a test case")
        db.add(TestRecord(run_id=run.id, test_case_id=tc.id, test_case_version_no=tc.version_no,
                          test_case_revision=tc.revision, result="not_run"))
        added += 1
    if added:
        audit.record(db, actor=actor, action="testrun.cases_added", entity_type="item", entity_id=run.id,
                     project_id=project.id, summary=f"Added {added} test case(s) to {run.key}",
                     related_ids=[run.id, *[tc.id for tc in test_cases]])
    return added


def steps_of(db: Session, project: Project, record: TestRecord, tc: Item) -> list[dict[str, str]]:
    """Steps of the executed test case version (or of the current version before the first execution)."""
    key = project.model.semantics.test_steps_field
    if record.executed_at is None:
        return list(tc.fields.get(key) or [])
    from almlight.modules.items.models import ItemVersion

    fields = db.execute(select(ItemVersion.fields).where(
        ItemVersion.item_id == tc.id, ItemVersion.version_no == record.test_case_version_no)).scalar()
    return list((fields or {}).get(key) or [])


def derive_result(step_results: list[dict[str, Any]]) -> str:
    results = [s.get("result", "not_run") for s in step_results]
    if any(r == "failed" for r in results):
        return "failed"
    if any(r == "blocked" for r in results):
        return "blocked"
    if results and all(r in ("passed", "skipped") for r in results) and "passed" in results:
        return "passed"
    if results and all(r == "skipped" for r in results):
        return "skipped"
    return "not_run"


def _clean_steps(step_results: list[dict[str, Any]], count: int) -> list[dict[str, Any]]:
    out = []
    for i in range(count):
        s = step_results[i] if i < len(step_results) and isinstance(step_results[i], dict) else {}
        r = s.get("result") or "not_run"
        if r not in RESULTS:
            raise ValidationFailed(f"step {i + 1}: result must be one of {RESULTS}")
        out.append({"result": r, "actual": str(s.get("actual") or "")[:5000],
                    "comment": str(s.get("comment") or "")[:2000]})
    return out


def set_result(
    db: Session, project: Project, actor: User | None, run: Item, record_id: uuid.UUID, *, result: str | None,
    comment: str | None = None, duration_ms: int | None = None, defect: Item | None = None,
    step_results: list[dict[str, Any]] | None = None,
) -> TestRecord:
    ensure_editable(project, run)
    record = db.get(TestRecord, record_id)
    if record is None or record.run_id != run.id:
        raise NotFound("Test record not found")
    tc = db.get(Item, record.test_case_id)
    assert tc is not None
    if step_results is not None:
        current_steps = list(tc.fields.get(project.model.semantics.test_steps_field) or [])
        record.step_results = _clean_steps(step_results, len(current_steps))
        if not result or result == "auto":
            result = derive_result(record.step_results)
    if result not in RESULTS:
        raise ValidationFailed(f"result must be one of {RESULTS}")
    record.result = result
    record.comment = comment
    record.duration_ms = duration_ms
    record.defect_id = defect.id if defect else None
    record.test_case_version_no = tc.version_no
    record.test_case_revision = tc.revision
    record.executed_by = actor.id if actor else None
    record.executed_at = utcnow() if result != "not_run" else None
    audit.record(db, actor=actor, action="testrun.result", entity_type="item", entity_id=run.id,
                 project_id=project.id, summary=f"{run.key}: {tc.key} {tc.version_label} -> {result}",
                 details={"comment": comment, "steps": record.step_results}, related_ids=[run.id, tc.id])
    return record


def raise_defect(db: Session, project: Project, actor: User, run: Item, record_id: uuid.UUID, *,
                 title: str | None = None, description: str | None = None, step: int | None = None) -> Item:
    """Create a problem report for a failed test record and link it (Polarion/Teamcenter "create defect")."""
    record = db.get(TestRecord, record_id)
    if record is None or record.run_id != run.id:
        raise NotFound("Test record not found")
    tc = db.get(Item, record.test_case_id)
    if record.defect_id is not None:
        existing = db.get(Item, record.defect_id)
        if existing is not None and existing.deleted_at is None:
            raise Conflict(f"{tc.key} in {run.key} already has defect {existing.key}", {"defect": existing.key})
    defect_type = project.model.semantics.defect_type
    if not defect_type or project.model.item_type(defect_type) is None:
        raise ValidationFailed("The information model has no defect (problem report) type")
    steps = steps_of(db, project, record, tc)
    lines = [f"Found in test run {run.key} executing {tc.key} {tc.version_label}: {tc.title}."]
    if step is not None and 0 < step <= len(steps):
        st = steps[step - 1]
        actual = ((record.step_results or [{}] * step)[step - 1] or {}).get("actual", "")
        lines += [f"Step {step}: {st.get('step', '')}", f"Expected: {st.get('expected', '')}",
                  f"Actual: {actual or '—'}"]
    if description:
        lines.append(description)
    t = project.model.item_type(defect_type)
    fields = {}
    if t.field("found_in"):
        fields["found_in"] = run.key
    defect = items_svc.create_item(db, project, actor, type_key=defect_type,
                                   title=title or f"{tc.key} failed in {run.key}" + (f" (step {step})" if step else ""),
                                   description="\n\n".join(lines), fields=fields)
    from almlight.modules.links import service as links_svc

    for lt in ("relates_to",):
        if project.model.link_type(lt) and project.model.link_type(lt).allows(defect.type_key, tc.type_key):
            links_svc.create_link(db, project, actor, type_key=lt, source=defect, target=tc)
    record.defect_id = defect.id
    return defect


# --- CI import ------------------------------------------------------------------------------

_KEY_IN_NAME = re.compile(r"(?<![A-Za-z0-9])([A-Z][A-Z0-9]{0,7}-\d+)(?![0-9])")


def import_junit(
    db: Session, project: Project, actor: User | None, xml: bytes, *, title: str | None = None,
    environment: str | None = None, build: str | None = None, variant: str | None = None,
) -> dict[str, Any]:
    """Create a test run from JUnit XML (the de-facto CI result format).

    Test cases are matched by their ``automation_id`` field (``classname.name`` or ``name``) or by
    an item key contained in the test name, e.g. ``test_TC-12_pressure_range``.
    """
    try:
        root = SafeET.fromstring(xml)
    except Exception as exc:  # noqa: BLE001
        raise ValidationFailed(f"Not a valid JUnit XML file: {exc}") from None
    cases = list(root.iter("testcase"))
    if not cases:
        raise ValidationFailed("The JUnit file contains no <testcase> elements")
    sem = project.model.semantics
    if not sem.test_run_type or project.model.item_type(sem.test_run_type) is None:
        raise ValidationFailed("This project has no test run item type")
    tcs = db.execute(
        select(Item).where(Item.project_id == project.id, Item.type_key.in_(sem.test_case_types),
                           Item.deleted_at.is_(None))
    ).scalars().all()
    by_auto = {str(tc.fields.get("automation_id")): tc for tc in tcs if tc.fields.get("automation_id")}
    by_key = {tc.key: tc for tc in tcs}

    run = items_svc.create_item(
        db, project, actor, type_key=sem.test_run_type,
        title=title or f"CI run {build or utcnow().strftime('%Y-%m-%d %H:%M')}",
        fields={k: v for k, v in {"environment": environment, "build": build, "variant": variant}.items() if v},
        change_note="Imported from JUnit XML",
    )
    matched: dict[uuid.UUID, tuple[Item, str, int | None, str | None]] = {}
    unmatched: list[str] = []
    for case in cases:
        name = case.get("name", "")
        classname = case.get("classname", "")
        tc = by_auto.get(f"{classname}.{name}") or by_auto.get(name)
        if tc is None:
            m = _KEY_IN_NAME.search(name) or _KEY_IN_NAME.search(classname)
            tc = by_key.get(m.group(1)) if m else None
        if tc is None:
            unmatched.append(f"{classname}.{name}" if classname else name)
            continue
        if case.find("failure") is not None or case.find("error") is not None:
            result = "failed"
            node = case.find("failure") if case.find("failure") is not None else case.find("error")
            message = (node.get("message") or (node.text or "")).strip()[:2000] or None
        elif case.find("skipped") is not None:
            result, message = "skipped", None
        else:
            result, message = "passed", None
        try:
            duration = int(float(case.get("time", "0")) * 1000)
        except ValueError:
            duration = None
        prev = matched.get(tc.id)
        # Several JUnit cases may map to one test case: any failure wins.
        if prev is None or (prev[1] == "passed" and result != "passed"):
            matched[tc.id] = (tc, result, duration, message)
    now = utcnow()
    for tc, result, duration, message in matched.values():
        db.add(TestRecord(run_id=run.id, test_case_id=tc.id, test_case_version_no=tc.version_no,
                          test_case_revision=tc.revision, result=result, comment=message, duration_ms=duration,
                          executed_by=actor.id if actor else None, executed_at=now))
    db.flush()
    _auto_close(db, project, actor, run)
    summary = defaultdict(int)
    for _, result, _, _ in matched.values():
        summary[result] += 1
    audit.record(db, actor=actor, action="testrun.imported", entity_type="item", entity_id=run.id,
                 project_id=project.id, summary=f"Imported {len(matched)} result(s) into {run.key}",
                 details={"summary": dict(summary), "unmatched": unmatched[:200]}, related_ids=[run.id])
    return {"run": run, "matched": len(matched), "unmatched": unmatched, "summary": dict(summary)}


def _auto_close(db: Session, project: Project, actor: User | None, run: Item) -> None:
    """Walk plain transitions (no approval, signature or comment) to the first closed state, if reachable."""
    wf = project.model.workflow_for(run.type_key)
    if wf is None:
        return
    from almlight.modules.workflow.engine import _guard_failures  # local: avoid import cycle

    goal = {s.key for s in wf.states if s.category == "closed" and s.frozen}
    queue: deque[tuple[str, list]] = deque([(run.state, [])])
    seen = {run.state}
    path = None
    while queue:
        state, steps = queue.popleft()
        if state in goal and steps:
            path = steps
            break
        for t in wf.transitions:
            if state in t.from_ and t.to not in seen and not (t.approval or t.signature or t.comment_required):
                seen.add(t.to)
                queue.append((t.to, [*steps, t]))
    if not path:
        return
    for t in path:
        if any(_guard_failures(db, project, run, g) for g in t.guards):
            return
        old = run.state
        run.state = t.to
        db.add(WorkflowEvent(item_id=run.id, transition_key=t.key, from_state=old, to_state=t.to, via="transition",
                             actor_id=actor.id if actor else None, comment="Automatic (CI import)",
                             version_no=run.version_no))
        db.flush()


# --- status ---------------------------------------------------------------------------------


def latest_results(db: Session, test_case_ids: list[uuid.UUID], variant: str | None = None
                   ) -> dict[uuid.UUID, TestRecord]:
    if not test_case_ids:
        return {}
    stmt = (
        select(TestRecord, Item)
        .join(Item, Item.id == TestRecord.run_id)
        .where(TestRecord.test_case_id.in_(test_case_ids), TestRecord.result != "not_run",
               Item.deleted_at.is_(None))
        .order_by(TestRecord.executed_at.desc().nulls_last())
    )
    out: dict[uuid.UUID, TestRecord] = {}
    for rec, run in db.execute(stmt).all():
        if variant and run.fields.get("variant") not in (None, "", variant):
            continue
        out.setdefault(rec.test_case_id, rec)
    return out


def verification_status(db: Session, project: Project, targets: list[Item], variant: str | None = None
                        ) -> dict[uuid.UUID, dict[str, Any]]:
    types = _verification_link_types(project)
    status: dict[uuid.UUID, dict[str, Any]] = {t.id: {"status": "none", "tests": []} for t in targets}
    if not targets or not types:
        return status
    rows = db.execute(
        select(Link, Item).join(Item, Item.id == Link.source_id)
        .where(Link.target_id.in_(status.keys()), Link.type_key.in_(types), Link.deleted_at.is_(None),
               Item.deleted_at.is_(None))
    ).all()
    tc_ids = list({tc.id for _, tc in rows})
    latest = latest_results(db, tc_ids, variant)
    for link, tc in rows:
        rec = latest.get(tc.id)
        if rec is None:
            st = "not_run"
        elif rec.result in ("failed", "blocked"):
            st = "failed"
        elif rec.test_case_version_no < tc.version_no or link.suspect:
            st = "retest"
        elif rec.result == "passed":
            st = "passed"
        else:
            st = "not_run"
        status[link.target_id]["tests"].append({
            "key": tc.key, "title": tc.title, "status": st, "suspect": link.suspect,
            "result": rec.result if rec else None,
            "executed_at": rec.executed_at.isoformat() if rec and rec.executed_at else None,
            "tested_version": f"{rec.test_case_revision}" if rec else None,
        })
    order = ["failed", "retest", "not_run", "passed"]
    for entry in status.values():
        tests = entry["tests"]
        if tests:
            entry["status"] = next(s for s in order if any(t["status"] == s for t in tests))
    return status


def coverage(db: Session, project: Project, type_key: str, variant: str | None = None) -> dict[str, Any]:
    """Coverage of one item type: refinement, allocation and verification per item."""
    reqs = db.execute(
        select(Item).where(Item.project_id == project.id, Item.type_key == type_key, Item.deleted_at.is_(None))
        .order_by(Item.seq)
    ).scalars().all()
    ids = [r.id for r in reqs]
    counts: dict[uuid.UUID, dict[str, int]] = {i: defaultdict(int) for i in ids}
    suspects: dict[uuid.UUID, int] = defaultdict(int)
    if ids:
        for link in db.execute(
            select(Link).join(Item, Item.id == Link.source_id)
            .where(Link.target_id.in_(ids), Link.deleted_at.is_(None), Item.deleted_at.is_(None))
        ).scalars():
            counts[link.target_id][link.type_key] += 1
            if link.suspect:
                suspects[link.target_id] += 1
    ver = verification_status(db, project, list(reqs), variant)
    sem = project.model.semantics
    rows = []
    for r in reqs:
        s = state_def(project, r)
        rows.append({
            "id": str(r.id), "key": r.key, "title": r.title, "state": r.state,
            "state_label": s.label if s else None, "version": r.version_label,
            "refined_by": counts[r.id].get(sem.derives_link, 0),
            "satisfied_by": counts[r.id].get(sem.satisfies_link, 0),
            "verified_by": counts[r.id].get(sem.verifies_link, 0),
            "suspect_links": suspects.get(r.id, 0),
            "verification": ver[r.id]["status"],
        })
    total = len(rows) or 1
    return {
        "type": type_key,
        "total": len(rows),
        "allocated_pct": round(100 * sum(1 for r in rows if r["satisfied_by"]) / total),
        "refined_pct": round(100 * sum(1 for r in rows if r["refined_by"]) / total),
        "verified_pct": round(100 * sum(1 for r in rows if r["verification"] == "passed") / total),
        "with_tests_pct": round(100 * sum(1 for r in rows if r["verified_by"]) / total),
        "rows": rows,
    }


def maturity(db: Session, project: Project, element_type: str | None = None,
             variant: str | None = None) -> list[dict[str, Any]]:
    """Maturity per element: specified / realised / verified / validated.

    * specified — requirements are allocated to the element and all of them are released
    * realised  — the element itself is released
    * verified  — every allocated requirement (and the element itself, if tested) passed verification
    * validated — every stakeholder requirement upstream of the allocated requirements passed
    """
    sem = project.model.semantics
    types = [element_type] if element_type else sem.element_types
    elements = db.execute(
        select(Item).where(Item.project_id == project.id, Item.type_key.in_(types), Item.deleted_at.is_(None))
        .order_by(Item.seq)
    ).scalars().all()
    out = []
    for el in elements:
        reqs = db.execute(
            select(Item).join(Link, Link.target_id == Item.id)
            .where(Link.source_id == el.id, Link.type_key == sem.satisfies_link, Link.deleted_at.is_(None),
                   Item.deleted_at.is_(None))
        ).scalars().all()
        released = [r for r in reqs if (s := state_def(project, r)) and s.released]
        specified = "done" if reqs and len(released) == len(reqs) else ("partial" if reqs else "none")
        el_state = state_def(project, el)
        realised = "done" if el_state and el_state.released else (
            "partial" if el_state and el_state.category == "review" else "none")
        ver = verification_status(db, project, [*reqs, el], variant)
        req_status = [ver[r.id]["status"] for r in reqs]
        if ver[el.id]["status"] != "none":
            req_status.append(ver[el.id]["status"])
        verified = ("done" if req_status and all(s == "passed" for s in req_status)
                    else "partial" if any(s == "passed" for s in req_status) else "none")
        upstream = _upstream_stakeholder(db, project, [r.id for r in reqs])
        up_status = verification_status(db, project, upstream, variant)
        vals = [v["status"] for v in up_status.values()]
        validated = ("done" if vals and all(s == "passed" for s in vals)
                     else "partial" if any(s == "passed" for s in vals) else "none")
        out.append({"id": str(el.id), "key": el.key, "title": el.title, "level": el.fields.get("level"),
                    "state": el.state, "version": el.version_label, "requirements": len(reqs),
                    "specified": specified, "realised": realised, "verified": verified, "validated": validated})
    return out


def _upstream_stakeholder(db: Session, project: Project, req_ids: list[uuid.UUID]) -> list[Item]:
    sem = project.model.semantics
    stakeholder_types = [t for t in sem.stakeholder_types if project.model.item_type(t)]
    if not req_ids or not stakeholder_types:
        return []
    seen = set(req_ids)
    frontier = list(req_ids)
    found: dict[uuid.UUID, Item] = {}
    while frontier:
        rows = db.execute(
            select(Item).join(Link, Link.target_id == Item.id)
            .where(Link.source_id.in_(frontier), Link.type_key == sem.derives_link, Link.deleted_at.is_(None),
                   Item.deleted_at.is_(None))
        ).scalars().all()
        frontier = []
        for it in rows:
            if it.id in seen:
                continue
            seen.add(it.id)
            frontier.append(it.id)
            if it.type_key in stakeholder_types:
                found[it.id] = it
    return list(found.values())
