from __future__ import annotations

import io
import uuid
import zipfile
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from almlight.core.db import utcnow
from almlight.core.errors import Conflict, NotFound, ValidationFailed
from almlight.modules.audit import service as audit
from almlight.modules.baselines import service as baselines
from almlight.modules.baselines.models import Baseline, BaselineItem
from almlight.modules.doc_collections.models import Collection, CollectionEntry
from almlight.modules.identity.models import User
from almlight.modules.io.document_export import render_docx, render_pdf
from almlight.modules.io.document_snapshot import build_snapshot
from almlight.modules.items.models import Item
from almlight.modules.projects.access import has_role
from almlight.modules.projects.models import Project


def get_collection(db: Session, project: Project, collection_id: uuid.UUID) -> Collection:
    c = db.get(Collection, collection_id)
    if c is None or c.project_id != project.id:
        raise NotFound("Collection not found")
    return c


def create(db: Session, project: Project, actor: User, name: str, description: str | None) -> Collection:
    if not (name or "").strip():
        raise ValidationFailed("Collection name is required")
    c = Collection(project_id=project.id, name=name.strip()[:200], description=description, created_by=actor.id)
    db.add(c)
    db.flush()
    audit.record(db, actor=actor, action="collection.created", entity_type="collection", entity_id=c.id,
                 project_id=project.id, summary=f"Created collection '{c.name}'")
    return c


def _ensure_open(c: Collection) -> None:
    if c.status != "open":
        raise Conflict(f"Collection '{c.name}' is closed — reopen it to change its content")


def add_document(db: Session, project: Project, actor: User, c: Collection, document: Item,
                 baseline: Baseline | None) -> CollectionEntry:
    _ensure_open(c)
    t = project.model.item_type(document.type_key)
    if t is None or not t.document:
        raise ValidationFailed(f"{document.key} is not a document")
    if baseline is None:
        baseline = baselines.create_baseline(db, project, actor, name=f"{c.name} — {document.key}",
                                             description=f"Baseline for collection '{c.name}'", scope_root=document)
    elif baseline.project_id != project.id or not db.execute(
            select(BaselineItem.item_id).where(BaselineItem.baseline_id == baseline.id,
                                               BaselineItem.item_id == document.id)).scalar():
        raise ValidationFailed(f"Baseline '{baseline.name}' does not contain {document.key}")
    entry = db.execute(select(CollectionEntry).where(CollectionEntry.collection_id == c.id,
                                                     CollectionEntry.document_id == document.id)).scalar_one_or_none()
    if entry is None:
        entry = CollectionEntry(collection_id=c.id, document_id=document.id, baseline_id=baseline.id,
                                added_by=actor.id)
        db.add(entry)
    else:
        entry.baseline_id = baseline.id
    db.flush()
    audit.record(db, actor=actor, action="collection.document_set", entity_type="collection", entity_id=c.id,
                 project_id=project.id, summary=f"Collection '{c.name}': {document.key} at baseline '{baseline.name}'",
                 related_ids=[document.id])
    return entry


def remove_document(db: Session, project: Project, actor: User, c: Collection, entry_id: uuid.UUID) -> None:
    _ensure_open(c)
    entry = db.get(CollectionEntry, entry_id)
    if entry is None or entry.collection_id != c.id:
        raise NotFound("Entry not found")
    db.delete(entry)
    audit.record(db, actor=actor, action="collection.document_removed", entity_type="collection", entity_id=c.id,
                 project_id=project.id, summary=f"Removed a document from collection '{c.name}'",
                 related_ids=[entry.document_id])


def set_status(db: Session, project: Project, actor: User, c: Collection, status: str) -> Collection:
    if status not in ("open", "closed"):
        raise ValidationFailed("status must be 'open' or 'closed'")
    if status == c.status:
        return c
    if status == "open" and not has_role(db, project, actor, "manager"):
        raise Conflict("Only a project manager can reopen a closed collection")
    if status == "closed" and not entries(db, c):
        raise ValidationFailed("A collection needs at least one document before it can be closed")
    c.status = status
    c.closed_at, c.closed_by = (utcnow(), actor.id) if status == "closed" else (None, None)
    audit.record(db, actor=actor, action=f"collection.{'closed' if status == 'closed' else 'reopened'}",
                 entity_type="collection", entity_id=c.id, project_id=project.id,
                 summary=f"{'Closed' if status == 'closed' else 'Reopened'} collection '{c.name}'")
    return c


def entries(db: Session, c: Collection) -> list[tuple[CollectionEntry, Item, Baseline]]:
    rows = db.execute(
        select(CollectionEntry, Item, Baseline).join(Item, Item.id == CollectionEntry.document_id)
        .join(Baseline, Baseline.id == CollectionEntry.baseline_id)
        .where(CollectionEntry.collection_id == c.id).order_by(Item.key)
    ).all()
    return [(e, i, b) for e, i, b in rows]


def export_zip(db: Session, project: Project, c: Collection, fmt: str) -> bytes:
    if fmt not in ("pdf", "docx"):
        raise ValidationFailed("format must be pdf or docx")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        manifest = [f"Collection: {c.name}", f"Status: {c.status}", ""]
        for _, doc, baseline in entries(db, c):
            snap = build_snapshot(db, project, doc, baseline_id=baseline.id)
            data = render_pdf(snap) if fmt == "pdf" else render_docx(snap)
            name = f"{doc.key}-{snap.root.version}.{fmt}"
            z.writestr(name, data)
            manifest.append(f"{name}\t{snap.root.title}\tbaseline '{baseline.name}' ({baseline.created_at:%Y-%m-%d})")
        z.writestr("MANIFEST.txt", "\n".join(manifest))
    return buf.getvalue()


def out(db: Session, c: Collection, users: Any) -> dict[str, Any]:
    return {
        "id": str(c.id), "name": c.name, "description": c.description, "status": c.status,
        "created_at": c.created_at.isoformat(), "created_by": users.ref(c.created_by),
        "closed_at": c.closed_at.isoformat() if c.closed_at else None, "closed_by": users.ref(c.closed_by),
        "entries": [{"id": str(e.id), "document": d.key, "title": d.title, "baseline_id": str(b.id),
                     "baseline": b.name, "baseline_created_at": b.created_at.isoformat()}
                    for e, d, b in entries(db, c)],
    }
