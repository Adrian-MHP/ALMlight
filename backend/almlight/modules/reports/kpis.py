"""Platform and process KPIs computed from the engineering data.

* Reuse rate per module          — how many products use each module, share of reused/standard/purchased elements
* Change lead time               — creation to decision/release of change requests and orders (and end-to-end)
* Re-test effort per variant     — applicable test cases without a current passing result, estimated duration
* Module variants vs. variants   — modules needed per offered product variant
"""

from __future__ import annotations

import statistics
import uuid
from collections import defaultdict
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from almlight.core.db import utcnow
from almlight.modules.items.models import Item
from almlight.modules.links.models import Link
from almlight.modules.projects.models import Project
from almlight.modules.variants import expressions
from almlight.modules.variants import service as variants_svc
from almlight.modules.verification.models import TestRecord
from almlight.modules.workflow.models import WorkflowEvent

REUSED = ("reused", "standard", "purchased")
MODULE_LEVELS = ("module", "component")


def _days(a: datetime, b: datetime) -> float:
    return round((b - a).total_seconds() / 86400, 1)


def _stats(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"avg": None, "median": None, "p90": None, "min": None, "max": None}
    ordered = sorted(values)
    p90 = ordered[min(len(ordered) - 1, int(round(0.9 * (len(ordered) - 1))))]
    return {"avg": round(statistics.fmean(values), 1), "median": round(statistics.median(values), 1),
            "p90": p90, "min": ordered[0], "max": ordered[-1]}


# --- reuse -------------------------------------------------------------------------------------


def reuse(db: Session, project: Project) -> dict[str, Any]:
    sem = project.model.semantics
    element_types = [t for t in sem.element_types if project.model.item_type(t)]
    elements = db.execute(
        select(Item).where(Item.project_id == project.id, Item.type_key.in_(element_types), Item.deleted_at.is_(None))
        .order_by(Item.seq)
    ).scalars().all() if element_types else []
    ids = {e.id for e in elements}
    structural = project.model.structural_link_types()
    parents: dict[uuid.UUID, set[uuid.UUID]] = defaultdict(set)
    level_of: dict[uuid.UUID, str | None] = {e.id: e.fields.get("level") for e in elements}
    if ids and structural:
        # Structures of all projects count: platform modules are reused by products in other projects.
        for link, parent_level in db.execute(
            select(Link, Item.fields["level"].astext).join(Item, Item.id == Link.source_id)
            .where(Link.type_key.in_(structural), Link.deleted_at.is_(None), Item.deleted_at.is_(None))
        ).all():
            parents[link.target_id].add(link.source_id)
            level_of.setdefault(link.source_id, parent_level)

    def products_using(eid: uuid.UUID) -> set[uuid.UUID]:
        seen, stack, found = set(), [eid], set()
        while stack:
            cur = stack.pop()
            for p in parents.get(cur, ()):
                if p in seen:
                    continue
                seen.add(p)
                if level_of.get(p) == "product" or not parents.get(p):
                    found.add(p)
                stack.append(p)
        return found

    rows = []
    for e in elements:
        products = products_using(e.id)
        rows.append({"key": e.key, "title": e.title, "level": e.fields.get("level"),
                     "reuse_strategy": e.fields.get("reuse_strategy"), "parents": len(parents.get(e.id, ())),
                     "products": len(products)})
    modules = [r for r in rows if r["level"] in MODULE_LEVELS]
    strategies: dict[str, int] = defaultdict(int)
    for r in modules:
        strategies[r["reuse_strategy"] or "unspecified"] += 1
    n = len(modules) or 1
    rows.sort(key=lambda r: (-r["products"], r["key"]))
    return {
        "modules": len(modules),
        "reuse_rate_pct": round(100 * sum(1 for r in modules if r["reuse_strategy"] in REUSED) / n),
        "multi_use_pct": round(100 * sum(1 for r in modules if r["products"] >= 2) / n),
        "avg_products_per_module": round(sum(r["products"] for r in modules) / n, 2) if modules else 0,
        "by_strategy": dict(strategies),
        "rows": rows,
    }


# --- change lead time ------------------------------------------------------------------------------


def change_lead_time(db: Session, project: Project, change_types: list[str] | None = None,
                     interval: str = "month", periods: int = 12) -> dict[str, Any]:
    model = project.model
    types = change_types or [t.key for t in model.item_types if t.category == "change"]
    items = db.execute(
        select(Item).where(Item.project_id == project.id, Item.type_key.in_(types), Item.deleted_at.is_(None))
        .order_by(Item.created_at)
    ).scalars().all() if types else []
    if not items:
        return {"types": {}, "rows": [], "end_to_end": _stats([]), "trend": []}
    events: dict[uuid.UUID, list[WorkflowEvent]] = defaultdict(list)
    for ev in db.execute(select(WorkflowEvent).where(WorkflowEvent.item_id.in_([i.id for i in items]))
                         .order_by(WorkflowEvent.created_at)).scalars():
        events[ev.item_id].append(ev)
    now = utcnow()
    rows = []
    done_at: dict[uuid.UUID, datetime] = {}
    for it in items:
        wf = model.workflow_for(it.type_key)
        finished = None
        outcome = None
        for ev in events[it.id]:
            st = wf.state(ev.to_state) if wf else None
            if st and st.category in ("released", "closed"):
                finished, outcome = ev.created_at, st.label
                break
        current = wf.state(it.state) if wf else None
        is_open = not (current and current.category in ("released", "closed", "obsolete"))
        if finished:
            done_at[it.id] = finished
        rows.append({"key": it.key, "title": it.title, "type": it.type_key, "state": current.label if current else None,
                     "created": it.created_at.isoformat(), "done": finished.isoformat() if finished else None,
                     "outcome": outcome, "lead_days": _days(it.created_at, finished) if finished else None,
                     "open_age_days": _days(it.created_at, now) if is_open else None})
    per_type = {}
    for t in types:
        trows = [r for r in rows if r["type"] == t]
        if not trows:
            continue
        per_type[t] = {"label": model.item_type(t).label if model.item_type(t) else t, "count": len(trows),
                       "open": sum(1 for r in trows if r["open_age_days"] is not None),
                       "lead_days": _stats([r["lead_days"] for r in trows if r["lead_days"] is not None]),
                       "open_age_days": _stats([r["open_age_days"] for r in trows if r["open_age_days"] is not None])}
    # End-to-end: change request created -> implementing change order released.
    by_id = {i.id: i for i in items}
    e2e = []
    implements = model.semantics.implements_link
    if model.link_type(implements):
        for link in db.execute(select(Link).where(Link.type_key == implements, Link.deleted_at.is_(None),
                                                  Link.source_id.in_(by_id), Link.target_id.in_(by_id))).scalars():
            co, cr = by_id[link.source_id], by_id[link.target_id]
            if co.id in done_at:
                e2e.append(_days(cr.created_at, done_at[co.id]))
    # Trend: average lead time of changes finished per period.
    buckets: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        if r["done"] and r["lead_days"] is not None:
            d = datetime.fromisoformat(r["done"])
            label = d.strftime("%Y-%m") if interval == "month" else f"{d.isocalendar()[0]}-W{d.isocalendar()[1]:02d}"
            buckets[label].append(r["lead_days"])
    trend = [{"period": k, "finished": len(v), "avg_lead_days": round(statistics.fmean(v), 1)}
             for k, v in sorted(buckets.items())][-periods:]
    return {"types": per_type, "rows": rows, "end_to_end": _stats(e2e), "trend": trend}


# --- re-test effort ----------------------------------------------------------------------------------


def retest_effort(db: Session, project: Project, variant_key: str | None = None) -> dict[str, Any]:
    sem = project.model.semantics
    tcs = db.execute(
        select(Item).where(Item.project_id == project.id, Item.type_key.in_(sem.test_case_types),
                           Item.deleted_at.is_(None)).order_by(Item.seq)
    ).scalars().all()
    variant_types = variants_svc._types_with_field(project, "selection")
    stmt = select(Item).where(Item.project_id == project.id, Item.type_key.in_(variant_types),
                              Item.deleted_at.is_(None)).order_by(Item.seq)
    variants = db.execute(stmt).scalars().all() if variant_types else []
    if variant_key:
        variants = [v for v in variants if v.key == variant_key.upper()]
    suspect_tcs = set(db.execute(
        select(Link.source_id).where(Link.source_id.in_([t.id for t in tcs]), Link.suspect.is_(True),
                                     Link.type_key == sem.verifies_link, Link.deleted_at.is_(None))
    ).scalars()) if tcs else set()
    records = db.execute(
        select(TestRecord, Item.fields).join(Item, Item.id == TestRecord.run_id)
        .where(TestRecord.test_case_id.in_([t.id for t in tcs]), TestRecord.result != "not_run",
               Item.deleted_at.is_(None))
        .order_by(TestRecord.executed_at.desc().nulls_last())
    ).all() if tcs else []

    def latest(tc_id: uuid.UUID, vkey: str | None) -> TestRecord | None:
        for rec, run_fields in records:
            if rec.test_case_id != tc_id:
                continue
            run_variant = (run_fields or {}).get("variant")
            if vkey is None or run_variant in (None, "", vkey):
                return rec
        return None

    def evaluate(applicable: list[Item], vkey: str | None) -> dict[str, Any]:
        passed = failed = never = 0
        retest_ms = 0
        retest_keys = []
        for tc in applicable:
            rec = latest(tc.id, vkey)
            current = (rec is not None and rec.result == "passed" and rec.test_case_version_no >= tc.version_no
                       and tc.id not in suspect_tcs)
            if current:
                passed += 1
                continue
            if rec is None:
                never += 1
            elif rec.result in ("failed", "blocked"):
                failed += 1
            retest_keys.append(tc.key)
            retest_ms += (rec.duration_ms or 0) if rec else 0
        return {"applicable": len(applicable), "passed_current": passed, "needs_retest": len(retest_keys),
                "never_run": never, "failed": failed, "estimated_minutes": round(retest_ms / 60000, 1),
                "retest_pct": round(100 * len(retest_keys) / len(applicable)) if applicable else 0,
                "retest_keys": retest_keys[:200]}

    rows = []
    for v in variants:
        sel = variants_svc.selection_of(v)
        applicable = []
        for tc in tcs:
            try:
                if expressions.applies(tc.applicability, sel):
                    applicable.append(tc)
            except Exception:  # noqa: BLE001
                continue
        rows.append({"variant": v.key, "title": v.title, **evaluate(applicable, v.key)})
    return {"overall": evaluate(list(tcs), None), "variants": rows}


# --- module variants vs. offered variants --------------------------------------------------------------


def variant_ratio(db: Session, project: Project) -> dict[str, Any]:
    sem = project.model.semantics
    element_types = [t for t in sem.element_types if project.model.item_type(t)]
    modules = [
        e for e in db.execute(
            select(Item).where(Item.project_id == project.id, Item.type_key.in_(element_types),
                               Item.deleted_at.is_(None))
        ).scalars()
        if e.fields.get("level") in MODULE_LEVELS
    ] if element_types else []
    variant_types = variants_svc._types_with_field(project, "selection")
    variants = db.execute(
        select(Item).where(Item.project_id == project.id, Item.type_key.in_(variant_types), Item.deleted_at.is_(None))
        .order_by(Item.seq)
    ).scalars().all() if variant_types else []
    feature_model = variants_svc.load_feature_model(db, project)
    common = [m for m in modules if not m.applicability]
    specific = [m for m in modules if m.applicability]
    rows = []
    for v in variants:
        sel = variants_svc.selection_of(v)
        used = [m for m in modules if _applies(m.applicability, sel)]
        rows.append({"variant": v.key, "title": v.title, "modules": len(used),
                     "variant_specific_modules": sum(1 for m in used if m.applicability),
                     "valid": not variants_svc.validate_selection(feature_model, sel)})
    offered = len(variants)
    return {
        "offered_variants": offered, "features": len(feature_model.features), "modules_total": len(modules),
        "modules_common": len(common), "modules_variant_specific": len(specific),
        "modules_per_variant_ratio": round(len(modules) / offered, 2) if offered else None,
        "variant_specific_per_variant": round(len(specific) / offered, 2) if offered else None,
        "rows": rows,
    }


def _applies(expr: str | None, selection: set[str]) -> bool:
    try:
        return expressions.applies(expr, selection)
    except Exception:  # noqa: BLE001
        return False
