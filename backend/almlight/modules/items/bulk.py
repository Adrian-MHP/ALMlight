"""Bulk edit: one action applied to many items (Polarion "bulk edit", Teamcenter "mass update").

The selection is a list of keys or a query (the item list's filter). Every item is processed in its own savepoint
through the normal services, so lifecycle rules, validation, permissions, versions, suspect links and the audit
trail apply exactly as for single edits; items that cannot be changed are skipped with the reason. A dry run
reports what would happen without changing anything. Notifications of one bulk run collapse into one summary per
person (see the notification service).
"""

from __future__ import annotations

import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from almlight.core.errors import DomainError, Forbidden, NotFound, ValidationFailed
from almlight.modules.identity.models import User
from almlight.modules.items import service as items_svc
from almlight.modules.items.models import Item
from almlight.modules.links import service as links_svc
from almlight.modules.links.models import Link
from almlight.modules.projects.access import has_role
from almlight.modules.projects.models import Project

MAX_BULK = 1000
Action = Literal["update", "transition", "plan", "unplan", "link", "watch", "unwatch", "delete"]


class Selection(BaseModel):
    q: str | None = None
    types: list[str] | None = None
    conditions: list[dict[str, Any]] | None = None
    ql: str | None = None


class BulkIn(BaseModel):
    keys: list[str] | None = Field(default=None, max_length=MAX_BULK)
    query: Selection | None = None
    action: Action
    dry_run: bool = True
    # update
    fields: dict[str, Any] | None = None
    owner_id: uuid.UUID | None = None
    set_owner: bool = False
    applicability: str | None = None
    set_applicability: bool = False
    change_note: str | None = Field(default=None, max_length=500)
    # transition
    transition: str | None = None
    comment: str | None = Field(default=None, max_length=2000)
    password: str | None = None
    # plan / unplan (release key; "from_release" moves between releases)
    release: str | None = None
    from_release: str | None = None
    # link
    link_type: str | None = None
    link_dir: Literal["out", "in"] = "out"
    target: str | None = None


def select_items(db: Session, project: Project, user: User, body: BulkIn) -> list[Item]:
    if body.keys:
        keys = list(dict.fromkeys(k.strip().upper() for k in body.keys if k.strip()))
        items = db.execute(select(Item).where(Item.project_id == project.id, Item.key.in_(keys),
                                              Item.deleted_at.is_(None))).scalars().all()
        found = {i.key for i in items}
        missing = [k for k in keys if k not in found]
        if missing:
            raise NotFound(f"Items not found: {', '.join(missing[:10])}", {"missing": missing})
        order = {k: n for n, k in enumerate(keys)}
        return sorted(items, key=lambda i: order[i.key])
    if body.query is None:
        raise ValidationFailed("Select items by keys or by a query")
    from almlight.modules.items import query as item_query

    conditions = item_query.parse_conditions(body.query.conditions or [])
    q = body.query.q
    if body.query.ql:
        text, more = item_query.parse_query(project, body.query.ql)
        q = " ".join(x for x in (q, text) if x) or None
        conditions += more
    items, total = items_svc.query_items(db, project, items_svc.ItemQuery(
        q=q, types=body.query.types, conditions=conditions or None, user_id=user.id, limit=MAX_BULK + 1),
        max_limit=MAX_BULK + 1)
    if total > MAX_BULK:
        raise ValidationFailed(f"The query selects {total} items; bulk edit handles at most {MAX_BULK}")
    return items


def _release(db: Session, project: Project, key: str | None) -> Item:
    if not key:
        raise ValidationFailed("Choose a release")
    rel = items_svc.get_item(db, project, key)
    if rel.type_key != project.model.semantics.release_type:
        raise ValidationFailed(f"{rel.key} is not a release")
    return rel


def _planned_link(db: Session, project: Project, item: Item, release: Item) -> Link | None:
    return db.execute(select(Link).where(Link.source_id == item.id, Link.target_id == release.id,
                                         Link.type_key == project.model.semantics.planned_link,
                                         Link.deleted_at.is_(None))).scalar_one_or_none()


def _apply_one(db: Session, project: Project, user: User, item: Item, body: BulkIn,
               ctx: dict[str, Any]) -> tuple[str, str | None]:
    """Returns (status, message): ok | unchanged | skipped."""
    a = body.action
    if a == "update":
        t = project.model.item_type(item.type_key)
        fields = None
        if body.fields:
            known = {f.key for f in t.fields}
            unknown = [k for k in body.fields if k not in known]
            if len(unknown) == len(body.fields) and not (body.set_owner or body.set_applicability):
                return "skipped", f"{t.label} has no field {', '.join(unknown)}"
            fields = {k: v for k, v in body.fields.items() if k in known} or None
        before = (item.version_no, item.owner_id)
        change = items_svc.ContentChange(fields=fields, applicability=(body.applicability or None)
                                         if body.set_applicability else items_svc._UNSET)
        items_svc.update_item(db, project, user, item, change, change_note=body.change_note or "Bulk edit",
                              owner_id=body.owner_id if body.set_owner else items_svc._UNSET)
        return ("ok", None) if (item.version_no, item.owner_id) != before else ("unchanged", None)
    if a == "transition":
        from almlight.modules.collab.router import flush_item
        from almlight.modules.workflow import engine

        wf = project.model.workflow_for(item.type_key)
        t = wf.transition(body.transition or "") if wf else None
        if t is None:
            return "skipped", f"{project.model.item_type(item.type_key).label} has no transition '{body.transition}'"
        if item.state not in t.from_:
            return "skipped", f"not possible from '{item.state}'"
        flush_item(db, item)
        res = engine.execute_transition(db, project, user, item, t.key, comment=body.comment,
                                        password=body.password, signature_verified=ctx.get("signature_ok", False))
        return "ok", "approval requested" if res.get("status") == "approval_requested" else None
    if a in ("plan", "unplan"):
        rel = ctx["release"]
        if a == "plan":
            if item.id == rel.id:
                return "skipped", "a release cannot be planned into itself"
            moved = False
            if ctx.get("from_release") is not None:
                old = _planned_link(db, project, item, ctx["from_release"])
                if old is not None:
                    links_svc.delete_link(db, project, user, old)
                    moved = True
            if _planned_link(db, project, item, rel) is not None:
                return ("ok", f"moved to {rel.key}") if moved else ("unchanged", f"already planned in {rel.key}")
            links_svc.create_link(db, project, user, type_key=project.model.semantics.planned_link, source=item,
                                  target=rel)
            return "ok", f"moved to {rel.key}" if moved else None
        link = _planned_link(db, project, item, rel)
        if link is None:
            return "unchanged", f"not planned in {rel.key}"
        links_svc.delete_link(db, project, user, link)
        return "ok", None
    if a == "link":
        target = ctx["target"]
        source, dest = (item, target) if body.link_dir == "out" else (target, item)
        exists = db.execute(select(Link.id).where(Link.source_id == source.id, Link.target_id == dest.id,
                                                  Link.type_key == body.link_type,
                                                  Link.deleted_at.is_(None))).scalar()
        if exists:
            return "unchanged", "link exists"
        links_svc.create_link(db, project, user, type_key=body.link_type, source=source, target=dest)
        return "ok", None
    if a in ("watch", "unwatch"):
        from almlight.modules.notifications.models import Subscription
        from almlight.modules.notifications.service import watch

        was = db.execute(select(Subscription.id).where(Subscription.user_id == user.id,
                                                       Subscription.item_id == item.id)).scalar() is not None
        if was == (a == "watch"):
            return "unchanged", None
        watch(db, user, project, item, a == "watch")
        db.flush()
        return "ok", None
    if a == "delete":
        items_svc.delete_item(db, project, user, item)
        return "ok", None
    raise ValidationFailed(f"Unknown action '{a}'")  # pragma: no cover — guarded by the schema


def run_bulk(db: Session, project: Project, user: User, body: BulkIn) -> dict[str, Any]:
    needed = ("viewer" if body.action in ("watch", "unwatch")
              else "manager" if body.action == "delete" else "contributor")
    if not has_role(db, project, user, needed):
        raise Forbidden(f"Bulk '{body.action}' needs the {needed} role")
    if body.action == "update" and not (body.fields or body.set_owner or body.set_applicability):
        raise ValidationFailed("Nothing to change: give fields, an owner or an applicability")
    items = select_items(db, project, user, body)
    ctx: dict[str, Any] = {}
    if body.action in ("plan", "unplan"):
        ctx["release"] = _release(db, project, body.release)
        if body.from_release:
            ctx["from_release"] = _release(db, project, body.from_release)
    if body.action == "link":
        if not body.link_type or project.model.link_type(body.link_type) is None:
            raise ValidationFailed("Choose a link type")
        ctx["target"] = items_svc.get_item(db, project, body.target or "")
    if body.action == "transition":
        if not body.transition:
            raise ValidationFailed("Choose a transition")
        signs = any((t := (project.model.workflow_for(i.type_key).transition(body.transition)
                           if project.model.workflow_for(i.type_key) else None)) is not None and t.signature
                    for i in items)
        if signs and not body.dry_run:
            from almlight.modules.workflow.engine import _check_signature

            _check_signature(user, body.password)  # once for the whole run
        ctx["signature_ok"] = True  # checked above; a dry run changes nothing
    results = []
    summary: dict[str, int] = {}
    for item in items:
        sp = db.begin_nested()
        try:
            status, message = _apply_one(db, project, user, item, body, ctx)
            sp.commit()
        except DomainError as exc:
            sp.rollback()
            status, message = "skipped", exc.message
        results.append({"key": item.key, "title": item.title, "status": status, "message": message})
        summary[status] = summary.get(status, 0) + 1
    if body.dry_run:
        db.rollback()
    else:
        db.commit()
    return {"dry_run": body.dry_run, "action": body.action, "total": len(items), "summary": summary,
            "results": results}
