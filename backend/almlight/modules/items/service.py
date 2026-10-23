"""Item lifecycle: create, edit (new iteration), revise (new revision), restore, delete, attachments."""

from __future__ import annotations

import difflib
import re
import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, BinaryIO

from sqlalchemy import Select, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from almlight.core import richtext
from almlight.core.db import utcnow
from almlight.core.errors import Conflict, Forbidden, NotFound, ValidationFailed
from almlight.modules.audit import service as audit
from almlight.modules.identity.models import User
from almlight.modules.images.service import ProjectImages
from almlight.modules.integrations.outbox import emit
from almlight.modules.items import storage
from almlight.modules.items.fields import normalize_fields
from almlight.modules.items.lifecycle import ensure_editable, state_def
from almlight.modules.items.models import Blob, Comment, Item, ItemVersion
from almlight.modules.items.revisions import first_revision, next_revision
from almlight.modules.links import service as links
from almlight.modules.links.models import Link
from almlight.modules.projects.access import has_role
from almlight.modules.projects.metamodel import ItemTypeDef
from almlight.modules.projects.models import Project, ProjectCounter
from almlight.modules.variants.expressions import normalize as normalize_expr
from almlight.modules.workflow.models import WorkflowEvent

_UNSET: Any = object()
MAX_TITLE = 500
KEY_PATTERN = re.compile(r"^([A-Z][A-Z0-9]{0,7})-(\d+)$")


def item_type(project: Project, type_key: str) -> ItemTypeDef:
    t = project.model.item_type(type_key)
    if t is None:
        raise ValidationFailed(f"Unknown item type '{type_key}' in project {project.key}")
    return t


def get_item(db: Session, project: Project, key_or_id: str, *, include_deleted: bool = False) -> Item:
    stmt = select(Item).where(Item.project_id == project.id)
    try:
        stmt = stmt.where(Item.id == uuid.UUID(key_or_id))
    except ValueError:
        stmt = stmt.where(Item.key == key_or_id.upper())
    item = db.execute(stmt).scalar_one_or_none()
    if item is None or (item.deleted_at is not None and not include_deleted):
        raise NotFound(f"Item '{key_or_id}' not found in project {project.key}")
    return item


def get_version(db: Session, item: Item, version_no: int) -> ItemVersion:
    v = db.execute(
        select(ItemVersion).where(ItemVersion.item_id == item.id, ItemVersion.version_no == version_no)
    ).scalar_one_or_none()
    if v is None:
        raise NotFound(f"{item.key} has no version {version_no}")
    return v


def _next_key(db: Session, project: Project, prefix: str) -> tuple[str, int]:
    db.execute(
        pg_insert(ProjectCounter)
        .values(project_id=project.id, prefix=prefix, next_value=1)
        .on_conflict_do_nothing(index_elements=["project_id", "prefix"])
    )
    counter = db.execute(
        select(ProjectCounter)
        .where(ProjectCounter.project_id == project.id, ProjectCounter.prefix == prefix)
        .with_for_update()
    ).scalar_one()
    seq = counter.next_value
    counter.next_value = seq + 1
    return f"{prefix}-{seq}", seq


def _clean_title(title: str | None) -> str:
    title = (title or "").strip()
    if not title:
        raise ValidationFailed("Title is required", {"fields": {"title": "Title is required"}})
    if len(title) > MAX_TITLE:
        raise ValidationFailed(f"Title must be at most {MAX_TITLE} characters")
    return title


def _snapshot(item: Item, *, kind: str, actor: User | None, change_note: str | None,
              change_order_id: uuid.UUID | None = None) -> ItemVersion:
    return ItemVersion(
        item_id=item.id,
        version_no=item.version_no,
        revision=item.revision,
        iteration=item.iteration,
        kind=kind,
        title=item.title,
        description=item.description,
        fields=item.fields,
        applicability=item.applicability,
        attachments=item.attachments,
        state=item.state,
        change_note=change_note,
        change_order_id=change_order_id,
        created_by=actor.id if actor else None,
        created_at=utcnow(),
    )


def _payload(project: Project, item: Item) -> dict[str, Any]:
    return {"project": project.key, "item": item.key, "type": item.type_key, "title": item.title,
            "state": item.state, "version": item.version_label}


def create_item(
    db: Session,
    project: Project,
    actor: User | None,
    *,
    type_key: str,
    title: str,
    description: str = "",
    fields: dict[str, Any] | None = None,
    owner_id: uuid.UUID | None = None,
    applicability: str | None = None,
    parent: Item | None = None,
    parent_link_type: str | None = None,
    position: float | None = None,
    kind: str = "create",
    change_note: str | None = None,
) -> Item:
    t = item_type(project, type_key)
    wf = project.model.workflow(t.workflow)
    key, seq = _next_key(db, project, t.prefix)
    now = utcnow()
    item = Item(
        id=uuid.uuid4(),
        project_id=project.id,
        type_key=type_key,
        key=key,
        seq=seq,
        title=_clean_title(title),
        description=richtext.normalize_input(description, ProjectImages(db, project, actor)),
        fields=normalize_fields(db, t.fields, fields or {}, apply_defaults=True),
        applicability=normalize_expr(applicability),
        attachments=[],
        state=wf.initial_state.key if wf else None,
        revision=first_revision(project.model.revision_scheme),
        iteration=1,
        version_no=1,
        owner_id=owner_id or (actor.id if actor else None),
        created_by=actor.id if actor else None,
        created_at=now,
        updated_by=actor.id if actor else None,
        updated_at=now,
    )
    db.add(item)
    db.flush()
    version = _snapshot(item, kind=kind, actor=actor, change_note=change_note)
    db.add(version)
    db.flush()
    item.head_version_id = version.id
    audit.record(
        db,
        actor=actor,
        action="item.created",
        entity_type="item",
        entity_id=item.id,
        project_id=project.id,
        summary=f"Created {key} ({t.label}): {item.title}",
        details={"key": key, "type": type_key, "fields": item.fields},
        related_ids=[item.id],
    )
    emit(db, "item.created", project.id, _payload(project, item))
    if parent is not None:
        link_type = parent_link_type or _structural_type_for(project, parent.type_key, type_key)
        links.create_link(db, project, actor, type_key=link_type, source=parent, target=item, position=position)
    return item


def _structural_type_for(project: Project, parent_type: str, child_type: str) -> str:
    for lt in project.model.link_types:
        if lt.structural and lt.allows(parent_type, child_type):
            return lt.key
    raise ValidationFailed(f"No structural link type allows {parent_type} to contain {child_type}")


@dataclass
class ContentChange:
    title: str | None = None
    description: str | None = None
    fields: dict[str, Any] | None = None  # partial: keys present are set, None values unset
    applicability: Any = _UNSET


def update_item(
    db: Session,
    project: Project,
    actor: User | None,
    item: Item,
    change: ContentChange,
    *,
    expected_version: int | None = None,
    change_note: str | None = None,
    owner_id: Any = _UNSET,
) -> Item:
    if expected_version is not None and expected_version != item.version_no:
        raise Conflict(
            f"{item.key} was changed by someone else (now version {item.version_label})",
            {"current_version_no": item.version_no},
        )
    t = item_type(project, item.type_key)
    if owner_id is not _UNSET and owner_id != item.owner_id:
        old = item.owner_id
        item.owner_id = owner_id
        audit.record(db, actor=actor, action="item.owner_changed", entity_type="item", entity_id=item.id,
                     project_id=project.id, summary=f"Changed owner of {item.key}",
                     details={"from": old, "to": owner_id}, related_ids=[item.id])

    new_title = _clean_title(change.title) if change.title is not None else item.title
    new_desc = (richtext.normalize_input(change.description, ProjectImages(db, project, actor))
                if change.description is not None else item.description)
    new_fields = (
        normalize_fields(db, t.fields, change.fields, base=item.fields) if change.fields is not None else item.fields
    )
    new_appl = normalize_expr(change.applicability) if change.applicability is not _UNSET else item.applicability
    diff = {
        name: [old, new]
        for name, old, new in (
            ("title", item.title, new_title),
            ("description", item.description, new_desc),
            ("applicability", item.applicability, new_appl),
        )
        if old != new
    }
    changed_fields = sorted(k for k in set(item.fields) | set(new_fields) if item.fields.get(k) != new_fields.get(k))
    if changed_fields:
        diff["fields"] = {k: [item.fields.get(k), new_fields.get(k)] for k in changed_fields}
    if not diff:
        return item
    ensure_editable(project, item)

    item.title, item.description, item.fields, item.applicability = new_title, new_desc, new_fields, new_appl
    _new_iteration(db, project, actor, item, kind="edit", change_note=change_note)
    if "title" in diff or "description" in diff:
        text_changed(db, item)
    suspects = links.mark_suspects(db, project, item, f"{item.key} changed to {item.version_label}")
    summary_fields = [k for k in diff if k != "fields"] + [f"fields.{k}" for k in changed_fields]
    audit.record(
        db,
        actor=actor,
        action="item.updated",
        entity_type="item",
        entity_id=item.id,
        project_id=project.id,
        summary=f"Edited {item.key} -> {item.version_label} ({', '.join(summary_fields)})",
        details={"version": item.version_label, "changed": summary_fields, "suspect_links": suspects,
                 "change_note": change_note},
        related_ids=[item.id],
    )
    emit(db, "item.updated", project.id, {**_payload(project, item), "changed": summary_fields})
    return item


def _new_iteration(db: Session, project: Project, actor: User | None, item: Item, *, kind: str,
                   change_note: str | None, change_order_id: uuid.UUID | None = None) -> ItemVersion:
    if change_order_id is None and kind != "revise" and item.head_version_id is not None:
        # Iterations of a revision started under a change order stay attributed to it.
        change_order_id = db.execute(
            select(ItemVersion.change_order_id).where(ItemVersion.id == item.head_version_id)
        ).scalar()
    item.iteration += 1
    item.version_no += 1
    item.updated_by = actor.id if actor else None
    item.updated_at = utcnow()
    version = _snapshot(item, kind=kind, actor=actor, change_note=change_note, change_order_id=change_order_id)
    db.add(version)
    db.flush()
    item.head_version_id = version.id
    return version


def revise_item(
    db: Session,
    project: Project,
    actor: User | None,
    item: Item,
    *,
    change_order: Item | None = None,
    change_note: str | None = None,
) -> Item:
    """Start a new revision (A -> B) of a released item. Change-controlled types need a change order."""
    t = item_type(project, item.type_key)
    wf = project.model.workflow(t.workflow)
    current = state_def(project, item)
    if wf is None or current is None:
        raise Conflict(f"{t.label} items have no lifecycle and cannot be revised")
    if not current.released:
        raise Conflict(f"Only released items can be revised; {item.key} is '{current.label}'")
    if t.change_controlled:
        if change_order is None:
            raise ValidationFailed(
                f"{t.label} items are change-controlled: revise them under a change order that lists "
                f"{item.key} as affected item",
                {"change_order_required": True},
            )
        _check_change_order(db, project, change_order, item)
    elif change_order is not None:
        _check_change_order(db, project, change_order, item)

    old_label = item.version_label
    old_state = item.state
    item.revision = next_revision(item.revision, project.model.revision_scheme)
    item.iteration = 0  # _new_iteration increments to 1
    item.state = wf.initial_state.key
    _new_iteration(db, project, actor, item, kind="revise", change_note=change_note,
                   change_order_id=change_order.id if change_order else None)
    db.info.setdefault("access_changed", set()).add(item.id)
    db.add(WorkflowEvent(item_id=item.id, transition_key=None, from_state=old_state, to_state=item.state,
                         via="revise", actor_id=actor.id if actor else None, comment=change_note,
                         version_no=item.version_no, change_order_id=change_order.id if change_order else None))
    audit.record(
        db,
        actor=actor,
        action="item.revised",
        entity_type="item",
        entity_id=item.id,
        project_id=project.id,
        summary=f"Revised {item.key}: {old_label} -> {item.version_label}"
        + (f" under {change_order.key}" if change_order else ""),
        details={"from": old_label, "to": item.version_label,
                 "change_order": change_order.key if change_order else None, "change_note": change_note},
        related_ids=[item.id] + ([change_order.id] if change_order else []),
    )
    emit(db, "item.revised", project.id, {**_payload(project, item),
                                          "change_order": change_order.key if change_order else None})
    return item


def _check_change_order(db: Session, project: Project, change_order: Item, item: Item) -> None:
    if change_order.project_id != project.id or change_order.deleted_at:
        raise ValidationFailed("Change order not found in this project")
    s = state_def(project, change_order)
    if s is None or not s.implementation_open:
        raise Conflict(f"{change_order.key} is not open for implementation (state '{change_order.state}')")
    affects = db.execute(
        select(Link.id).where(
            Link.source_id == change_order.id,
            Link.target_id == item.id,
            Link.type_key == project.model.semantics.affects_link,
            Link.deleted_at.is_(None),
        )
    ).scalar()
    if not affects:
        raise ValidationFailed(f"{item.key} is not listed as affected item of {change_order.key}")


def restore_version(
    db: Session, project: Project, actor: User | None, item: Item, version_no: int, *,
    expected_version: int | None = None,
) -> Item:
    old = get_version(db, item, version_no)
    change = ContentChange(
        title=old.title,
        description=old.description,
        fields={k: old.fields.get(k) for k in set(old.fields) | set(item.fields)},
        applicability=old.applicability,
    )
    before = item.version_no
    item = update_item(db, project, actor, item, change, expected_version=expected_version,
                       change_note=f"Restored content of version {old.version_label}")
    if item.version_no != before:
        db.execute(
            ItemVersion.__table__.update()
            .where(ItemVersion.id == item.head_version_id)
            .values(kind="restore")
        )
    return item


def delete_item(db: Session, project: Project, actor: User | None, item: Item) -> None:
    if item.released_version_id is not None:
        raise Conflict(f"{item.key} has been released and cannot be deleted — make it obsolete instead")
    item.deleted_at = utcnow()
    removed = links.soft_delete_links_of(db, item, actor, at=item.deleted_at)
    audit.record(db, actor=actor, action="item.deleted", entity_type="item", entity_id=item.id,
                 project_id=project.id, summary=f"Deleted {item.key}: {item.title}",
                 details={"links_removed": removed}, related_ids=[item.id])
    emit(db, "item.deleted", project.id, _payload(project, item))


def undelete_item(db: Session, project: Project, actor: User | None, item: Item) -> int:
    """Restore an item from the recycle bin together with the links removed with it."""
    if item.deleted_at is None:
        raise Conflict(f"{item.key} is not deleted")
    deleted_at = item.deleted_at
    item.deleted_at = None
    restored = 0
    window = (deleted_at - timedelta(seconds=2), deleted_at + timedelta(seconds=2))
    for link in db.execute(
        select(Link).where((Link.source_id == item.id) | (Link.target_id == item.id),
                           Link.deleted_at.between(*window))
    ).scalars():
        other_id = link.target_id if link.source_id == item.id else link.source_id
        other = db.get(Item, other_id)
        duplicate = db.execute(select(Link.id).where(
            Link.type_key == link.type_key, Link.source_id == link.source_id, Link.target_id == link.target_id,
            Link.deleted_at.is_(None))).scalar()
        if other is None or other.deleted_at is not None or duplicate:
            continue
        link.deleted_at = None
        link.deleted_by = None
        restored += 1
    audit.record(db, actor=actor, action="item.restored", entity_type="item", entity_id=item.id,
                 project_id=project.id, summary=f"Restored {item.key} from the recycle bin ({restored} links)",
                 related_ids=[item.id])
    emit(db, "item.created", project.id, _payload(project, item))
    return restored


# --- attachments --------------------------------------------------------------------------


def add_attachment(
    db: Session, project: Project, actor: User | None, item: Item, *, filename: str, content_type: str,
    stream: BinaryIO,
) -> dict[str, Any]:
    ensure_editable(project, item)
    filename = (filename or "file").replace("/", "_").replace("\\", "_")[:255]
    sha, size = storage.store(stream)
    db.execute(
        pg_insert(Blob)
        .values(sha256=sha, size=size, content_type=content_type or "application/octet-stream")
        .on_conflict_do_nothing(index_elements=["sha256"])
    )
    meta = {
        "id": str(uuid.uuid4()),
        "filename": filename,
        "content_type": content_type or "application/octet-stream",
        "size": size,
        "sha256": sha,
        "uploaded_by": str(actor.id) if actor else None,
        "uploaded_at": utcnow().isoformat(),
    }
    item.attachments = [*item.attachments, meta]
    _new_iteration(db, project, actor, item, kind="edit", change_note=f"Attached {filename}")
    suspects = links.mark_suspects(db, project, item, f"{item.key} changed to {item.version_label}")
    audit.record(db, actor=actor, action="item.attachment_added", entity_type="item", entity_id=item.id,
                 project_id=project.id, summary=f"Attached {filename} to {item.key} ({item.version_label})",
                 details={"attachment": meta, "suspect_links": suspects}, related_ids=[item.id])
    emit(db, "item.updated", project.id, {**_payload(project, item), "changed": ["attachments"]})
    return meta


def revise_attachment(
    db: Session, project: Project, actor: User | None, item: Item, attachment_id: str, *, filename: str | None,
    content_type: str | None, stream: BinaryIO, comment: str | None = None,
) -> dict[str, Any]:
    """Check in a new revision of an attached file (same file, new content): a new item iteration; the holder's
    check-out is released. A file checked out by someone else cannot be replaced."""
    from almlight.modules.files import service as files

    ensure_editable(project, item)
    old = files.attachment(item, attachment_id)
    own = files.ensure_not_locked_by_other(db, item, attachment_id, actor)
    sha, size = storage.store(stream)
    if sha == old["sha256"]:
        if own is None:
            raise ValidationFailed("The uploaded file is identical to the current revision")
        db.delete(own)  # checking in an unchanged file just ends the check-out
        db.flush()
        return old
    db.execute(
        pg_insert(Blob)
        .values(sha256=sha, size=size, content_type=content_type or old["content_type"])
        .on_conflict_do_nothing(index_elements=["sha256"])
    )
    name = (filename or old["filename"]).replace("/", "_").replace("\\", "_")[:255]
    meta = {**old, "filename": name, "content_type": content_type or old["content_type"], "size": size,
            "sha256": sha, "revision": int(old.get("revision") or 1) + 1,
            "uploaded_by": str(actor.id) if actor else None, "uploaded_at": utcnow().isoformat(),
            "comment": (comment or "").strip()[:500] or None}
    item.attachments = [meta if a["id"] == attachment_id else a for a in item.attachments]
    _new_iteration(db, project, actor, item, kind="edit",
                   change_note=f"Checked in {name} (file revision {meta['revision']})")
    if own is not None:
        db.delete(own)
    suspects = links.mark_suspects(db, project, item, f"{item.key} changed to {item.version_label}")
    audit.record(db, actor=actor, action="item.attachment_revised", entity_type="item", entity_id=item.id,
                 project_id=project.id,
                 summary=f"Checked in {name} revision {meta['revision']} on {item.key} ({item.version_label})",
                 details={"attachment": meta, "previous_sha256": old["sha256"], "suspect_links": suspects},
                 related_ids=[item.id])
    emit(db, "item.updated", project.id, {**_payload(project, item), "changed": ["attachments"]})
    return meta


def attachment_history(db: Session, item: Item, attachment_id: str) -> list[dict[str, Any]]:
    """Every revision of one attached file, newest first, with the item version that introduced it."""
    versions = db.execute(select(ItemVersion).where(ItemVersion.item_id == item.id)
                          .order_by(ItemVersion.version_no)).scalars().all()
    out: list[dict[str, Any]] = []
    last = None
    for v in versions:
        a = next((x for x in v.attachments if x["id"] == attachment_id), None)
        if a is not None and a["sha256"] != last:
            out.append({**a, "revision": a.get("revision") or 1, "version_no": v.version_no,
                        "item_version": v.version_label})
            last = a["sha256"]
        elif a is None:
            last = None
    if not out:
        raise NotFound("Attachment not found")
    return list(reversed(out))


def remove_attachment(db: Session, project: Project, actor: User | None, item: Item, attachment_id: str) -> None:
    from almlight.modules.files import service as files

    ensure_editable(project, item)
    remaining = [a for a in item.attachments if a["id"] != attachment_id]
    if len(remaining) == len(item.attachments):
        raise NotFound("Attachment not found")
    own = files.ensure_not_locked_by_other(db, item, attachment_id, actor)
    if own is not None:
        db.delete(own)
    removed = next(a for a in item.attachments if a["id"] == attachment_id)
    item.attachments = remaining
    _new_iteration(db, project, actor, item, kind="edit", change_note=f"Removed {removed['filename']}")
    links.mark_suspects(db, project, item, f"{item.key} changed to {item.version_label}")
    audit.record(db, actor=actor, action="item.attachment_removed", entity_type="item", entity_id=item.id,
                 project_id=project.id, summary=f"Removed {removed['filename']} from {item.key}",
                 details={"attachment": removed}, related_ids=[item.id])


def find_attachment(db: Session, item: Item, attachment_id: str, version_no: int | None = None) -> dict[str, Any]:
    pool = get_version(db, item, version_no).attachments if version_no else item.attachments
    meta = next((a for a in pool if a["id"] == attachment_id), None)
    if meta is None:
        raise NotFound("Attachment not found")
    return meta


# --- comments -----------------------------------------------------------------------------


def add_comment(db: Session, project: Project, actor: User, item: Item, body: str, *,
                parent_id: uuid.UUID | None = None, document: Item | None = None) -> Comment:
    body = (body or "").strip()
    if not body:
        raise ValidationFailed("Comment must not be empty")
    parent = None
    if parent_id:
        parent = db.get(Comment, parent_id)
        if parent is None or parent.item_id != item.id or parent.deleted_at:
            raise NotFound("Comment to reply to not found")
        while parent.parent_id:  # replies attach to the thread root
            parent = db.get(Comment, parent.parent_id)
    comment = Comment(item_id=item.id, author_id=actor.id, body=body[:20_000], parent_id=parent.id if parent else None,
                      document_id=(document.id if document else (parent.document_id if parent else None)))
    db.add(comment)
    db.flush()
    if parent and parent.resolved_at:  # replying reopens a resolved thread
        parent.resolved_at, parent.resolved_by = None, None
    from almlight.modules.notifications.service import mentions

    audit.record(db, actor=actor, action="comment.added", entity_type="comment", entity_id=comment.id,
                 project_id=project.id, summary=f"{'Replied to a comment' if parent else 'Commented'} on {item.key}",
                 details={"mentions": mentions(body), "excerpt": body[:300]},
                 related_ids=[item.id] + ([document.id] if document else []))
    emit(db, "comment.added", project.id, {"project": project.key, "item": item.key, "comment_id": comment.id})
    return comment


def _comment(db: Session, item: Item, comment_id: uuid.UUID) -> Comment:
    comment = db.get(Comment, comment_id)
    if comment is None or comment.item_id != item.id or comment.deleted_at:
        raise NotFound("Comment not found")
    return comment


def resolve_comment(db: Session, project: Project, actor: User, item: Item, comment_id: uuid.UUID,
                    resolved: bool = True) -> Comment:
    comment = _comment(db, item, comment_id)
    if comment.parent_id:
        raise ValidationFailed("Resolve the thread, not a reply")
    comment.resolved_at = utcnow() if resolved else None
    comment.resolved_by = actor.id if resolved else None
    audit.record(db, actor=actor, action="comment.resolved" if resolved else "comment.reopened",
                 entity_type="comment", entity_id=comment.id, project_id=project.id,
                 summary=f"{'Resolved' if resolved else 'Reopened'} a comment thread on {item.key}",
                 related_ids=[item.id])
    return comment


def delete_comment(db: Session, project: Project, actor: User, item: Item, comment_id: uuid.UUID) -> None:
    comment = _comment(db, item, comment_id)
    if comment.author_id != actor.id and not has_role(db, project, actor, "manager"):
        raise Forbidden("Only the author or a project manager can delete a comment")
    now = utcnow()
    comment.deleted_at = now
    replies = 0
    for reply in db.execute(select(Comment).where(Comment.parent_id == comment.id,
                                                  Comment.deleted_at.is_(None))).scalars():
        reply.deleted_at = now
        replies += 1
    audit.record(db, actor=actor, action="comment.deleted", entity_type="comment", entity_id=comment.id,
                 project_id=project.id, summary=f"Deleted a comment on {item.key}"
                 + (f" with {replies} replies" if replies else ""), related_ids=[item.id])


# --- queries ------------------------------------------------------------------------------


@dataclass
class ItemQuery:
    q: str | None = None
    types: list[str] | None = None
    states: list[str] | None = None
    owner_id: uuid.UUID | None = None
    suspect: bool | None = None
    field_filters: dict[str, str] | None = None
    keys: list[str] | None = None
    sort: str = "key"
    limit: int = 50
    offset: int = 0
    # traceability filter: items that have (or lack) a link of this type in this direction
    link_type: str | None = None
    link_dir: str = "out"  # out | in
    link_exists: bool | None = None
    updated_since: Any = None
    planned_in: str | None = None


SORTS = {
    "key": (Item.type_key, Item.seq),
    "-key": (Item.type_key.desc(), Item.seq.desc()),
    "title": (Item.title,),
    "updated": (Item.updated_at,),
    "-updated": (Item.updated_at.desc(),),
    "state": (Item.state, Item.seq),
}


def _filtered(project: Project, query: ItemQuery) -> Select:
    stmt = select(Item).where(Item.project_id == project.id, Item.deleted_at.is_(None))
    if query.q:
        text_q = query.q.strip()
        if KEY_PATTERN.match(text_q.upper()):
            stmt = stmt.where(Item.key == text_q.upper())
        else:
            stmt = stmt.where(
                or_(
                    Item.search.op("@@")(func.websearch_to_tsquery("simple", text_q)),
                    Item.title.ilike(f"%{text_q}%"),
                )
            )
    if query.types:
        stmt = stmt.where(Item.type_key.in_(query.types))
    if query.states:
        stmt = stmt.where(Item.state.in_(query.states))
    if query.owner_id:
        stmt = stmt.where(Item.owner_id == query.owner_id)
    if query.keys:
        stmt = stmt.where(Item.key.in_([k.upper() for k in query.keys]))
    for fkey, fval in (query.field_filters or {}).items():
        if fval in ("true", "false"):
            stmt = stmt.where(Item.fields.contains({fkey: fval == "true"}))
        else:
            stmt = stmt.where(or_(Item.fields[fkey].astext == fval, Item.fields.contains({fkey: [fval]})))
    if query.suspect:
        stmt = stmt.where(
            Item.id.in_(select(Link.source_id).where(Link.suspect.is_(True), Link.deleted_at.is_(None)))
        )
    if query.link_type and query.link_exists is not None:
        own = Link.source_id if query.link_dir != "in" else Link.target_id
        linked = select(own).where(Link.type_key == query.link_type, Link.deleted_at.is_(None))
        stmt = stmt.where(Item.id.in_(linked) if query.link_exists else Item.id.not_in(linked))
    if query.updated_since is not None:
        stmt = stmt.where(Item.updated_at >= query.updated_since)
    if query.planned_in:
        release = select(Item.id).where(Item.project_id == project.id, Item.key == query.planned_in.upper())
        stmt = stmt.where(Item.id.in_(select(Link.source_id).where(
            Link.type_key == project.model.semantics.planned_link, Link.target_id.in_(release),
            Link.deleted_at.is_(None))))
    return stmt


def query_items(db: Session, project: Project, query: ItemQuery, *, max_limit: int = 1000) -> tuple[list[Item], int]:
    stmt = _filtered(project, query)
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    order = SORTS.get(query.sort, SORTS["key"])
    rows = db.execute(stmt.order_by(*order).limit(min(query.limit, max_limit)).offset(query.offset)).scalars().all()
    return list(rows), total


def text_changed(db: Session, item: Item) -> None:
    """Title/text changed outside a live editing session: open sessions must restart from the new text.

    Collected per transaction and acted on after commit (see ``collab.hooks``); a session saving its own
    content marks the transaction with ``db.info["collab_source"]`` so it is not reset.
    """
    if db.info.get("collab_source") != item.id:
        db.info.setdefault("text_changed", set()).add(item.id)


def text_diff(old: str, new: str) -> list[str]:
    return list(difflib.unified_diff(old.splitlines(), new.splitlines(), "before", "after", lineterm="", n=2))


def diff_versions(a: ItemVersion, b: ItemVersion) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    for name in ("title", "description", "applicability", "state"):
        old, new = getattr(a, name), getattr(b, name)
        if old != new:
            entry: dict[str, Any] = {"field": name, "old": old, "new": new}
            if name == "description":
                entry["diff"] = text_diff(richtext.to_text(old or ""), richtext.to_text(new or ""))
                entry["html_diff"] = richtext.html_diff(old or "", new or "")
            changes.append(entry)
    for key in sorted(set(a.fields) | set(b.fields)):
        if a.fields.get(key) != b.fields.get(key):
            changes.append({"field": f"fields.{key}", "old": a.fields.get(key), "new": b.fields.get(key)})
    old_files = {f["sha256"] + f["filename"] for f in a.attachments}
    new_files = {f["sha256"] + f["filename"] for f in b.attachments}
    if old_files != new_files:
        changes.append({
            "field": "attachments",
            "old": [f["filename"] for f in a.attachments],
            "new": [f["filename"] for f in b.attachments],
        })
    return changes
