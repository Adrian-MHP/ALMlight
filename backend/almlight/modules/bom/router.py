"""Product structure as a bill of materials: multi-level BOM with quantities, find numbers and effectivity,
exports, and where-used (also across projects that reuse an element)."""

from __future__ import annotations

import csv
import io
import uuid
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from almlight.core.db import get_db
from almlight.core.deps import current_user
from almlight.core.errors import ValidationFailed
from almlight.modules.identity.models import User
from almlight.modules.items import service as items_svc
from almlight.modules.items.models import Item
from almlight.modules.links.models import Link
from almlight.modules.projects.access import get_project, project_role
from almlight.modules.projects.models import Project

router = APIRouter(prefix="/projects/{project_key}", tags=["product structure"])
MAX_ROWS = 20_000


def _effective(attrs: dict[str, Any], on: date | None) -> bool:
    if on is None:
        return True
    start, end = attrs.get("effective_from"), attrs.get("effective_to")
    try:
        if start and date.fromisoformat(str(start)[:10]) > on:
            return False
        if end and date.fromisoformat(str(end)[:10]) < on:
            return False
    except ValueError:
        return True
    return True


def bom_rows(db: Session, project: Project, root: Item, effective: date | None = None) -> list[dict[str, Any]]:
    structural = project.model.structural_link_types()
    rows: list[dict[str, Any]] = []
    projects: dict[uuid.UUID, Project] = {project.id: project}

    def proj(pid: uuid.UUID) -> Project:
        if pid not in projects:
            projects[pid] = db.get(Project, pid)
        return projects[pid]

    def walk(parent: Item, level: int, path: list[str], qty: float, seen: frozenset) -> None:
        links = db.execute(
            select(Link, Item).join(Item, Item.id == Link.target_id)
            .where(Link.source_id == parent.id, Link.type_key.in_(structural), Link.deleted_at.is_(None),
                   Item.deleted_at.is_(None)).order_by(Link.position.nulls_last(), Item.key)
        ).all()
        for link, child in links:
            if child.id in seen or len(rows) >= MAX_ROWS:
                continue
            attrs = link.attributes or {}
            if not _effective(attrs, effective):
                continue
            q = attrs.get("quantity")
            q = float(q) if isinstance(q, (int, float)) and not isinstance(q, bool) else 1.0
            p = proj(child.project_id)
            wf = p.model.workflow_for(child.type_key)
            st = wf.state(child.state) if wf else None
            t = p.model.item_type(child.type_key)
            rows.append({
                "level": level, "path": "/".join([*path, child.key]), "key": child.key, "project": p.key,
                "type": child.type_key, "type_label": t.label if t else child.type_key, "title": child.title,
                "revision": child.revision, "version": child.version_label, "state": st.label if st else child.state,
                "state_category": st.category if st else None, "quantity": attrs.get("quantity"),
                "unit": attrs.get("unit"), "find_number": attrs.get("find_number"),
                "effective_from": attrs.get("effective_from"), "effective_to": attrs.get("effective_to"),
                "total_quantity": round(qty * q, 6), "link_id": str(link.id),
                "part_number": child.fields.get("part_number"), "supplier": child.fields.get("supplier"),
                "has_children": False,
            })
            idx = len(rows) - 1
            before = len(rows)
            walk(child, level + 1, [*path, child.key], qty * q, seen | {child.id})
            rows[idx]["has_children"] = len(rows) > before

    walk(root, 1, [root.key], 1.0, frozenset({root.id}))
    return rows


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        raise ValidationFailed("effective must be a date (YYYY-MM-DD)") from None


@router.get("/items/{item_key}/bom", summary="Multi-level bill of materials (quantities, find numbers, effectivity)")
def bom(project_key: str, item_key: str, effective: str | None = None, user: User = Depends(current_user),
        db: Session = Depends(get_db)) -> dict[str, Any]:
    project = get_project(db, project_key, user)
    root = items_svc.get_item(db, project, item_key)
    rows = bom_rows(db, project, root, _parse_date(effective))
    totals: dict[str, float] = {}
    for r in rows:
        if not r["has_children"]:
            totals[r["key"]] = totals.get(r["key"], 0) + r["total_quantity"]
    return {"root": {"key": root.key, "title": root.title, "version": root.version_label}, "effective": effective,
            "rows": rows, "leaf_totals": [{"key": k, "total_quantity": v} for k, v in sorted(totals.items())]}


@router.get("/items/{item_key}/bom.{fmt}", summary="BOM export (csv or xlsx)")
def bom_export(project_key: str, item_key: str, fmt: str, effective: str | None = None,
               user: User = Depends(current_user), db: Session = Depends(get_db)) -> Response:
    if fmt not in ("csv", "xlsx"):
        raise ValidationFailed("format must be csv or xlsx")
    project = get_project(db, project_key, user)
    root = items_svc.get_item(db, project, item_key)
    rows = bom_rows(db, project, root, _parse_date(effective))
    header = ["level", "find_number", "key", "title", "type_label", "version", "state", "quantity", "unit",
              "total_quantity", "part_number", "supplier", "effective_from", "effective_to", "project", "path"]
    data = [[r.get(h) if r.get(h) is not None else "" for h in header] for r in rows]
    name = f"{root.key}-BOM{'-' + effective if effective else ''}"
    if fmt == "csv":
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(header)
        w.writerows(data)
        return Response(("﻿" + buf.getvalue()).encode("utf-8"), media_type="text/csv",
                        headers={"Content-Disposition": f'attachment; filename="{name}.csv"'})
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "BOM"
    ws.append(header)
    for row in data:
        ws.append(row)
    ws.freeze_panes = "A2"
    out = io.BytesIO()
    wb.save(out)
    return Response(out.getvalue(), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{name}.xlsx"'})


@router.get("/items/{item_key}/where-used", summary="Every structure an item is used in (paths up to the roots)")
def where_used(project_key: str, item_key: str, user: User = Depends(current_user),
               db: Session = Depends(get_db)) -> dict[str, Any]:
    project = get_project(db, project_key, user)
    item = items_svc.get_item(db, project, item_key)
    cache: dict[uuid.UUID, Item] = {}
    projects: dict[uuid.UUID, Project] = {}

    def get(iid: uuid.UUID) -> Item | None:
        if iid not in cache:
            cache[iid] = db.get(Item, iid)
        return cache[iid]

    def structural_of(pid: uuid.UUID) -> list[str]:
        if pid not in projects:
            projects[pid] = db.get(Project, pid)
        return projects[pid].model.structural_link_types()

    paths: list[list[dict[str, Any]]] = []

    def up(child: Item, trail: list[dict[str, Any]], seen: frozenset, depth: int) -> None:
        parents = db.execute(
            select(Link).where(Link.target_id == child.id, Link.deleted_at.is_(None))
        ).scalars().all()
        found = False
        for link in parents:
            parent = get(link.source_id)
            if parent is None or parent.deleted_at is not None or parent.id in seen:
                continue
            if link.type_key not in structural_of(parent.project_id):
                continue
            if project_role(db, projects[parent.project_id], user) is None:
                continue  # structures in projects the user cannot see stay hidden
            found = True
            step = {"key": parent.key, "title": parent.title, "project": projects[parent.project_id].key,
                    "version": parent.version_label, "quantity": (link.attributes or {}).get("quantity"),
                    "find_number": (link.attributes or {}).get("find_number")}
            if depth < 15:
                up(parent, [step, *trail], seen | {parent.id}, depth + 1)
        if not found and trail:
            paths.append(trail)

    up(item, [], frozenset({item.id}), 0)
    direct = sorted({p[-1]["key"] for p in paths})
    return {"item": item.key, "used_in": len(direct), "direct_parents": direct, "paths": paths}
