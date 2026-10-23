"""File check-out and check-in (document management in the PLM sense).

Files attached to an item are versioned with the item. For files edited outside the browser — CAD models, Office
documents, test reports — a user *checks out* the file: nobody else can replace or remove it until it is checked in
(a new file revision, which also creates a new item iteration) or the check-out is cancelled by its holder or a
project manager. Items with checked-out files cannot move to a frozen state (review, release) — like Teamcenter,
which refuses to release checked-out objects.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from almlight.core.errors import Conflict, Forbidden, NotFound
from almlight.modules.audit import service as audit
from almlight.modules.files.models import FileCheckout
from almlight.modules.identity.models import User
from almlight.modules.items.lifecycle import ensure_editable
from almlight.modules.items.models import Item
from almlight.modules.projects.access import has_role
from almlight.modules.projects.models import Project


def attachment(item: Item, attachment_id: str) -> dict[str, Any]:
    meta = next((a for a in item.attachments if a["id"] == attachment_id), None)
    if meta is None:
        raise NotFound("Attachment not found")
    return meta


def get(db: Session, item_id: uuid.UUID, attachment_id: str) -> FileCheckout | None:
    return db.execute(select(FileCheckout).where(FileCheckout.item_id == item_id,
                                                 FileCheckout.attachment_id == attachment_id)).scalar_one_or_none()


def for_items(db: Session, item_ids: list[uuid.UUID]) -> dict[tuple[uuid.UUID, str], FileCheckout]:
    if not item_ids:
        return {}
    rows = db.execute(select(FileCheckout).where(FileCheckout.item_id.in_(item_ids))).scalars().all()
    return {(r.item_id, r.attachment_id): r for r in rows}


def _holder(db: Session, co: FileCheckout) -> str:
    u = db.get(User, co.user_id)
    return u.display_name if u else "another user"


def ensure_not_locked_by_other(db: Session, item: Item, attachment_id: str, user: User | None) -> FileCheckout | None:
    """The caller's own check-out (or None); a check-out by someone else blocks changes to the file."""
    co = get(db, item.id, attachment_id)
    if co is not None and (user is None or co.user_id != user.id):
        filename = next((a["filename"] for a in item.attachments if a["id"] == attachment_id), "The file")
        raise Conflict(f"{filename} is checked out by {_holder(db, co)} since "
                       f"{co.checked_out_at:%Y-%m-%d %H:%M} UTC", {"checked_out_by": str(co.user_id)})
    return co


def checkout(db: Session, project: Project, actor: User, item: Item, attachment_id: str,
             note: str | None = None) -> FileCheckout:
    ensure_editable(project, item)
    meta = attachment(item, attachment_id)
    existing = ensure_not_locked_by_other(db, item, attachment_id, actor)
    if existing is not None:
        return existing
    co = FileCheckout(project_id=project.id, item_id=item.id, attachment_id=attachment_id, user_id=actor.id,
                      note=(note or "").strip()[:500] or None)
    db.add(co)
    db.flush()
    audit.record(db, actor=actor, action="file.checked_out", entity_type="item", entity_id=item.id,
                 project_id=project.id, summary=f"Checked out {meta['filename']} of {item.key}",
                 details={"attachment": attachment_id, "note": co.note}, related_ids=[item.id])
    return co


def cancel(db: Session, project: Project, actor: User, item: Item, attachment_id: str) -> None:
    co = get(db, item.id, attachment_id)
    if co is None:
        raise NotFound("The file is not checked out")
    if co.user_id != actor.id and not has_role(db, project, actor, "manager"):
        raise Forbidden("Only the holder or a project manager can cancel a check-out")
    meta = next((a for a in item.attachments if a["id"] == attachment_id), {"filename": "file"})
    db.delete(co)
    db.flush()
    forced = co.user_id != actor.id
    audit.record(db, actor=actor, action="file.checkout_cancelled", entity_type="item", entity_id=item.id,
                 project_id=project.id,
                 summary=f"Cancelled the check-out of {meta['filename']} of {item.key}"
                         + (f" (held by {_holder(db, co)})" if forced else ""),
                 details={"attachment": attachment_id, "forced": forced}, related_ids=[item.id])


def release_blockers(db: Session, items: list[Item]) -> list[str]:
    """Why these items cannot be frozen: their checked-out files."""
    by_id = {i.id: i for i in items}
    out = []
    for (item_id, att_id), co in sorted(for_items(db, list(by_id)).items(), key=lambda kv: kv[1].checked_out_at):
        it = by_id[item_id]
        filename = next((a["filename"] for a in it.attachments if a["id"] == att_id), "a file")
        out.append(f"{it.key}: {filename} is checked out by {_holder(db, co)}")
    return out


def mine(db: Session, user: User) -> list[dict[str, Any]]:
    rows = db.execute(
        select(FileCheckout, Item, Project).join(Item, Item.id == FileCheckout.item_id)
        .join(Project, Project.id == FileCheckout.project_id)
        .where(FileCheckout.user_id == user.id, Item.deleted_at.is_(None)).order_by(FileCheckout.checked_out_at)
    ).all()
    out = []
    for co, item, project in rows:
        meta = next((a for a in item.attachments if a["id"] == co.attachment_id), None)
        if meta is None:
            continue
        out.append({"project": project.key, "item_key": item.key, "item_title": item.title,
                    "attachment_id": co.attachment_id, "filename": meta["filename"],
                    "revision": meta.get("revision", 1), "note": co.note,
                    "checked_out_at": co.checked_out_at.isoformat()})
    return out
