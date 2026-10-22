from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from almlight.core.db import get_db
from almlight.core.deps import current_user
from almlight.core.errors import ValidationFailed
from almlight.core.schemas import Ok, UserDirectory
from almlight.modules.identity.models import User
from almlight.modules.items import service as items_svc
from almlight.modules.items.models import Item
from almlight.modules.items.schemas import ItemOut, items_out
from almlight.modules.links import service
from almlight.modules.links.models import Link
from almlight.modules.projects.access import get_project

router = APIRouter(prefix="/projects/{project_key}", tags=["traceability"])


class LinkIn(BaseModel):
    type: str
    source: str = Field(description="Source item key (the dependent side)")
    target: str = Field(description="Target item key; 'PROJ:KEY' for another project")
    position: float | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)
    applicability: str | None = None


class LinkPatch(BaseModel):
    position: float | None = None
    attributes: dict[str, Any] | None = None
    applicability: str | None = None


class ConfirmIn(BaseModel):
    comment: str | None = None


class MoveIn(BaseModel):
    parent: str = Field(description="Key of the new parent")
    position: float | None = None


class LinkOut(BaseModel):
    id: uuid.UUID
    type: str
    label: str
    direction: str
    position: float | None
    attributes: dict[str, Any]
    applicability: str | None
    suspect: bool
    suspect_reason: str | None
    other: ItemOut


def _resolve_target(db: Session, project, ref: str, user: User) -> Item:
    if ":" in ref:
        other_key, item_key = ref.split(":", 1)
        other = get_project(db, other_key, user)
        return items_svc.get_item(db, other, item_key)
    return items_svc.get_item(db, project, ref)


def _link_out(db: Session, project, views: list[service.LinkView], users: UserDirectory) -> list[LinkOut]:
    from almlight.modules.projects.models import Project

    out = []
    projects: dict[uuid.UUID, Project] = {project.id: project}
    for v in views:
        lt = project.model.link_type(v.link.type_key)
        other_project = projects.get(v.other.project_id) or db.get(Project, v.other.project_id)
        projects[other_project.id] = other_project
        label = (lt.label if v.direction == "outgoing" else lt.reverse_label) if lt else v.link.type_key
        out.append(LinkOut(id=v.link.id, type=v.link.type_key, label=label, direction=v.direction,
                           position=v.link.position, attributes=v.link.attributes,
                           applicability=v.link.applicability, suspect=v.link.suspect,
                           suspect_reason=v.link.suspect_reason,
                           other=items_out(other_project, [v.other], users)[0]))
    return out


@router.get("/items/{item_key}/links", response_model=list[LinkOut])
def item_links(project_key: str, item_key: str, user: User = Depends(current_user),
               db: Session = Depends(get_db)) -> list[LinkOut]:
    project = get_project(db, project_key, user)
    item = items_svc.get_item(db, project, item_key)
    return _link_out(db, project, service.links_of(db, item), UserDirectory(db))


@router.post("/links", status_code=201)
def create_link(project_key: str, body: LinkIn, user: User = Depends(current_user),
                db: Session = Depends(get_db)) -> dict[str, Any]:
    project = get_project(db, project_key, user, "contributor")
    source = items_svc.get_item(db, project, body.source)
    target = _resolve_target(db, project, body.target, user)
    link = service.create_link(db, project, user, type_key=body.type, source=source, target=target,
                               position=body.position, attributes=body.attributes, applicability=body.applicability)
    db.commit()
    return {"id": str(link.id), "type": link.type_key, "source": source.key, "target": target.key}


@router.patch("/links/{link_id}", summary="Change a link; returns the id of the new link version")
def update_link(project_key: str, link_id: uuid.UUID, body: LinkPatch, user: User = Depends(current_user),
                db: Session = Depends(get_db)) -> dict[str, Any]:
    project = get_project(db, project_key, user, "contributor")
    link = service.get_link(db, project, link_id)
    sent = body.model_fields_set
    link = service.update_link(
        db, project, user, link,
        position=body.position if "position" in sent else service._UNSET,
        attributes=body.attributes if "attributes" in sent else service._UNSET,
        applicability=(body.applicability or None) if "applicability" in sent else service._UNSET,
    )
    db.commit()
    return {"id": str(link.id)}


@router.delete("/links/{link_id}", response_model=Ok)
def delete_link(project_key: str, link_id: uuid.UUID, user: User = Depends(current_user),
                db: Session = Depends(get_db)) -> Ok:
    project = get_project(db, project_key, user, "contributor")
    service.delete_link(db, project, user, service.get_link(db, project, link_id))
    db.commit()
    return Ok()


@router.post("/links/{link_id}/confirm", response_model=Ok)
def confirm_link(project_key: str, link_id: uuid.UUID, body: ConfirmIn | None = None,
                 user: User = Depends(current_user), db: Session = Depends(get_db)) -> Ok:
    project = get_project(db, project_key, user, "contributor")
    service.confirm_link(db, project, user, service.get_link(db, project, link_id), body.comment if body else None)
    db.commit()
    return Ok()


@router.post("/items/{item_key}/move", response_model=Ok, summary="Move an item to another parent/position")
def move_item(project_key: str, item_key: str, body: MoveIn, user: User = Depends(current_user),
              db: Session = Depends(get_db)) -> Ok:
    project = get_project(db, project_key, user, "contributor")
    item = items_svc.get_item(db, project, item_key)
    parent = items_svc.get_item(db, project, body.parent)
    structural = project.model.structural_link_types()
    current = db.execute(
        select(Link).where(Link.target_id == item.id, Link.type_key.in_(structural), Link.deleted_at.is_(None))
    ).scalars().all()
    same = next((lk for lk in current if lk.source_id == parent.id), None)
    if same is not None:
        service.update_link(db, project, user, same, position=body.position)
    else:
        if len(current) > 1:
            raise ValidationFailed(f"{item.key} has several parents; remove the extra links first")
        for lk in current:
            service.delete_link(db, project, user, lk)
        type_key = items_svc._structural_type_for(project, parent.type_key, item.type_key)
        service.create_link(db, project, user, type_key=type_key, source=parent, target=item, position=body.position)
    db.commit()
    return Ok()


@router.get("/items/{item_key}/impact")
def impact(project_key: str, item_key: str, depth: int = Query(default=8, ge=1, le=20),
           user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    """Impact analysis: what depends on this item (transitively) and where it is used."""
    project = get_project(db, project_key, user)
    item = items_svc.get_item(db, project, item_key)
    rows = service.impact_analysis(db, project, item, depth)
    users = UserDirectory(db)
    out = []
    for r in rows:
        out.append({"item": items_out(project, [r["item"]], users)[0].model_dump(mode="json"),
                    "depth": r["depth"], "via": r["via"], "via_item": r["via_item_key"],
                    "relation": r["relation"]})
    by_type: dict[str, int] = {}
    for r in rows:
        by_type[r["item"].type_key] = by_type.get(r["item"].type_key, 0) + 1
    return {"root": item.key, "count": len(out), "by_type": by_type, "impacted": out}


@router.get("/suspects")
def suspects(project_key: str, user: User = Depends(current_user), db: Session = Depends(get_db)
             ) -> list[dict[str, Any]]:
    project = get_project(db, project_key, user)
    src = Item.__table__.alias("src")
    tgt = Item.__table__.alias("tgt")
    rows = db.execute(
        select(Link, src.c.key, src.c.title, tgt.c.key, tgt.c.title)
        .join(src, src.c.id == Link.source_id).join(tgt, tgt.c.id == Link.target_id)
        .where(Link.project_id == project.id, Link.suspect.is_(True), Link.deleted_at.is_(None),
               src.c.deleted_at.is_(None))
        .order_by(Link.suspect_since.desc())
    ).all()
    return [{"link_id": str(link.id), "type": link.type_key, "source": sk, "source_title": st, "target": tk,
             "target_title": tt, "reason": link.suspect_reason,
             "since": link.suspect_since.isoformat() if link.suspect_since else None}
            for link, sk, st, tk, tt in rows]


@router.get("/trace-matrix")
def trace_matrix(project_key: str, rows: str, cols: str, link_type: str | None = None,
                 user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    """Traceability matrix between two item types (links in either direction)."""
    project = get_project(db, project_key, user)
    for t in (rows, cols):
        items_svc.item_type(project, t)
    row_items = db.execute(select(Item).where(Item.project_id == project.id, Item.type_key == rows,
                                              Item.deleted_at.is_(None)).order_by(Item.seq)).scalars().all()
    col_items = db.execute(select(Item).where(Item.project_id == project.id, Item.type_key == cols,
                                              Item.deleted_at.is_(None)).order_by(Item.seq)).scalars().all()
    rid = {i.id for i in row_items}
    cid = {i.id for i in col_items}
    stmt = select(Link).where(Link.deleted_at.is_(None),
                              ((Link.source_id.in_(rid)) & (Link.target_id.in_(cid)))
                              | ((Link.source_id.in_(cid)) & (Link.target_id.in_(rid))))
    if link_type:
        stmt = stmt.where(Link.type_key == link_type)
    cells = []
    for link in db.execute(stmt).scalars():
        r, c = (link.source_id, link.target_id) if link.source_id in rid else (link.target_id, link.source_id)
        cells.append({"row": str(r), "col": str(c), "type": link.type_key, "suspect": link.suspect})
    return {
        "rows": [{"id": str(i.id), "key": i.key, "title": i.title} for i in row_items],
        "cols": [{"id": str(i.id), "key": i.key, "title": i.title} for i in col_items],
        "cells": cells,
    }
