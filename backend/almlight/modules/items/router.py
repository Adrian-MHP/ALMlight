from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from almlight.core.db import get_db
from almlight.core.deps import current_user, ui_locale
from almlight.core.errors import NotFound
from almlight.core.i18n import tr
from almlight.core.schemas import Ok, Page, UserDirectory
from almlight.modules.audit.models import AuditEntry
from almlight.modules.collab.router import flush_item
from almlight.modules.identity.models import User
from almlight.modules.items import bulk, service, storage
from almlight.modules.items import query as item_query
from almlight.modules.items.models import Comment, Item, ItemVersion
from almlight.modules.items.schemas import (
    CommentIn,
    CommentOut,
    ItemDetailOut,
    ItemIn,
    ItemOut,
    ItemPatch,
    RestoreIn,
    ReviseIn,
    VersionOut,
    item_detail,
    items_out,
    version_out,
)
from almlight.modules.links import service as links_svc
from almlight.modules.projects.access import get_project
from almlight.modules.projects.models import Project
from almlight.modules.workflow.models import WorkflowEvent

router = APIRouter(prefix="/projects/{project_key}", tags=["items"])


@router.get("/items", response_model=Page[ItemOut])
def list_items(
    project_key: str,
    request: Request,
    q: str | None = None,
    type: list[str] | None = Query(default=None),
    state: list[str] | None = Query(default=None),
    owner: uuid.UUID | None = None,
    suspect: bool | None = None,
    key: list[str] | None = Query(default=None),
    sort: str = "key",
    limit: int = Query(default=50, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    link_type: str | None = Query(default=None, description="Traceability filter: link type"),
    link_dir: str = Query(default="out", pattern="^(out|in)$"),
    link_exists: bool | None = Query(default=None, description="true: has such a link; false: lacks it"),
    updated_since: str | None = Query(default=None, description="ISO date or timestamp"),
    planned_in: str | None = Query(default=None, description="Key of a release"),
    cond: str | None = Query(default=None, description="JSON list of conditions {field, op, values, not}"),
    ql: str | None = Query(default=None, description="Query language, e.g. type:risk NOT link.mitigated_by.out:*"),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> Page[ItemOut]:
    """List and search items. Filter custom fields with ``field.<key>=<value>`` query parameters; find gaps with
    ``link_type=verifies&link_dir=in&link_exists=false`` (e.g. requirements without a verifying test)."""
    project = get_project(db, project_key, user)
    field_filters = {k[6:]: v for k, v in request.query_params.items() if k.startswith("field.")}
    conditions = item_query.parse_conditions(cond)
    if ql:
        text, more = item_query.parse_query(project, ql)
        q = " ".join(x for x in (q, text) if x) or None
        conditions += more
    items, total = service.query_items(db, project, service.ItemQuery(
        q=q, types=type, states=state, owner_id=owner, suspect=suspect, field_filters=field_filters, keys=key,
        sort=sort, limit=limit, offset=offset, link_type=link_type, link_dir=link_dir, link_exists=link_exists,
        updated_since=_since(updated_since), planned_in=planned_in, conditions=conditions or None, user_id=user.id))
    return Page[ItemOut](items=items_out(project, items, UserDirectory(db)), total=total, limit=limit, offset=offset)


@router.post("/items/bulk", summary="Bulk edit: fields/owner, transition, plan, link, watch or delete many items")
def bulk_edit(project_key: str, body: bulk.BulkIn, user: User = Depends(current_user),
              db: Session = Depends(get_db)) -> dict[str, Any]:
    """Select items by ``keys`` or ``query`` (``q``, ``types``, ``conditions``, ``ql``); ``dry_run`` (default) only
    reports. Each item is changed through the normal services; items that cannot be changed are skipped with the
    reason."""
    project = get_project(db, project_key, user)
    return bulk.run_bulk(db, project, user, body)


class QueryText(BaseModel):
    text: str = Field(default="", max_length=4000)


class QueryParts(BaseModel):
    q: str | None = None
    conditions: list[item_query.Node] = Field(default_factory=list)


@router.post("/query/parse", summary="Query language → free text and conditions")
def parse_query(project_key: str, body: QueryText, user: User = Depends(current_user),
                db: Session = Depends(get_db)) -> dict[str, Any]:
    project = get_project(db, project_key, user)
    q, conditions = item_query.parse_query(project, body.text)
    return {"q": q, "conditions": [c.dump() for c in conditions]}


@router.post("/query/format", summary="Free text and conditions → query language")
def format_query(project_key: str, body: QueryParts, user: User = Depends(current_user),
                 db: Session = Depends(get_db)) -> dict[str, Any]:
    project = get_project(db, project_key, user)
    for c in item_query.leaves(body.conditions):
        item_query.field_info(project, c.field)
    return {"text": item_query.format_query(project, body.q, body.conditions)}


def _since(value: str | None):
    if not value:
        return None
    from almlight.modules.documents.service import parse_at

    return parse_at(value if "T" in value else f"{value}T00:00:00")


@router.post("/items", response_model=ItemDetailOut, status_code=201)
def create_item(project_key: str, body: ItemIn, user: User = Depends(current_user),
                db: Session = Depends(get_db)) -> ItemDetailOut:
    project = get_project(db, project_key, user, "contributor")
    parent = service.get_item(db, project, body.parent) if body.parent else None
    item = service.create_item(db, project, user, type_key=body.type, title=body.title, description=body.description,
                               fields=body.fields, applicability=body.applicability, owner_id=body.owner_id,
                               parent=parent, position=body.position)
    db.commit()
    return item_detail(db, project, item, UserDirectory(db))


@router.get("/items/{item_key}", response_model=ItemDetailOut)
def get_item(project_key: str, item_key: str, user: User = Depends(current_user),
             db: Session = Depends(get_db)) -> ItemDetailOut:
    project = get_project(db, project_key, user)
    return item_detail(db, project, service.get_item(db, project, item_key), UserDirectory(db))


@router.patch("/items/{item_key}", response_model=ItemDetailOut)
def update_item(project_key: str, item_key: str, body: ItemPatch, user: User = Depends(current_user),
                db: Session = Depends(get_db)) -> ItemDetailOut:
    project = get_project(db, project_key, user, "contributor")
    item = service.get_item(db, project, item_key)
    if body.title is not None or body.description is not None:
        flush_item(db, item)  # unsaved live edits become a version first (expected_version then detects it)
    sent = body.model_fields_set
    change = service.ContentChange(
        title=body.title, description=body.description, fields=body.fields,
        applicability=(body.applicability or None) if "applicability" in sent else service._UNSET,
    )
    item = service.update_item(db, project, user, item, change, expected_version=body.expected_version,
                               change_note=body.change_note,
                               owner_id=body.owner_id if "owner_id" in sent else service._UNSET)
    db.commit()
    return item_detail(db, project, item, UserDirectory(db))


@router.delete("/items/{item_key}", response_model=Ok)
def delete_item(project_key: str, item_key: str, user: User = Depends(current_user),
                db: Session = Depends(get_db)) -> Ok:
    project = get_project(db, project_key, user, "manager")
    item = service.get_item(db, project, item_key)
    flush_item(db, item)
    service.delete_item(db, project, user, item)
    db.commit()
    return Ok()


@router.post("/items/{item_key}/revise", response_model=ItemDetailOut)
def revise_item(project_key: str, item_key: str, body: ReviseIn, user: User = Depends(current_user),
                db: Session = Depends(get_db)) -> ItemDetailOut:
    project = get_project(db, project_key, user, "contributor")
    item = service.get_item(db, project, item_key)
    flush_item(db, item)
    co = service.get_item(db, project, body.change_order) if body.change_order else None
    item = service.revise_item(db, project, user, item, change_order=co, change_note=body.change_note)
    db.commit()
    return item_detail(db, project, item, UserDirectory(db))


@router.get("/items/{item_key}/versions", response_model=list[VersionOut])
def list_versions(project_key: str, item_key: str, user: User = Depends(current_user),
                  db: Session = Depends(get_db)) -> list[VersionOut]:
    project = get_project(db, project_key, user)
    item = service.get_item(db, project, item_key)
    versions = db.execute(
        select(ItemVersion).where(ItemVersion.item_id == item.id).order_by(ItemVersion.version_no.desc())
    ).scalars().all()
    users = UserDirectory(db)
    users.preload({v.created_by for v in versions})
    return [version_out(db, item, v, users) for v in versions]


@router.get("/items/{item_key}/versions/{version_no}", response_model=VersionOut)
def get_version(project_key: str, item_key: str, version_no: int, user: User = Depends(current_user),
                db: Session = Depends(get_db)) -> VersionOut:
    project = get_project(db, project_key, user)
    item = service.get_item(db, project, item_key)
    return version_out(db, item, service.get_version(db, item, version_no), UserDirectory(db))


@router.get("/items/{item_key}/diff")
def diff(project_key: str, item_key: str, from_version: int = Query(alias="from"),
         to_version: int | None = Query(default=None, alias="to"), user: User = Depends(current_user),
         db: Session = Depends(get_db)) -> dict[str, Any]:
    project = get_project(db, project_key, user)
    item = service.get_item(db, project, item_key)
    a = service.get_version(db, item, from_version)
    b = service.get_version(db, item, to_version or item.version_no)
    return {"from": a.version_label, "to": b.version_label, "changes": service.diff_versions(a, b)}


@router.post("/items/{item_key}/restore", response_model=ItemDetailOut)
def restore(project_key: str, item_key: str, body: RestoreIn, user: User = Depends(current_user),
            db: Session = Depends(get_db)) -> ItemDetailOut:
    project = get_project(db, project_key, user, "contributor")
    item = service.get_item(db, project, item_key)
    flush_item(db, item)
    item = service.restore_version(db, project, user, item, body.version_no, expected_version=body.expected_version)
    db.commit()
    return item_detail(db, project, item, UserDirectory(db))


@router.get("/items/{item_key}/history")
def history(project_key: str, item_key: str, user: User = Depends(current_user),
            db: Session = Depends(get_db), locale: str = Depends(ui_locale)) -> list[dict[str, Any]]:
    """Complete timeline of the item: content versions, links, lifecycle, approvals and comments."""
    project = get_project(db, project_key, user)
    item = service.get_item(db, project, item_key)
    entries = db.execute(
        select(AuditEntry)
        .where(or_(AuditEntry.entity_id == str(item.id), AuditEntry.related_ids.contains([item.id])))
        .order_by(AuditEntry.id.desc()).limit(500)
    ).scalars().all()
    return [{"id": e.id, "ts": e.ts.isoformat(), "actor": e.actor_name, "action": e.action,
             "summary": tr(e.summary, locale), "details": e.details} for e in entries]


@router.get("/items/{item_key}/workflow-events")
def workflow_events(project_key: str, item_key: str, user: User = Depends(current_user),
                    db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    project = get_project(db, project_key, user)
    item = service.get_item(db, project, item_key)
    events = db.execute(
        select(WorkflowEvent).where(WorkflowEvent.item_id == item.id).order_by(WorkflowEvent.created_at.desc())
    ).scalars().all()
    users = UserDirectory(db)
    return [{"from": e.from_state, "to": e.to_state, "transition": e.transition_key, "via": e.via,
             "actor": users.ref(e.actor_id), "comment": e.comment, "version_no": e.version_no, "signed": e.signed,
             "at": e.created_at.isoformat()} for e in events]


# --- attachments ----------------------------------------------------------------------------


@router.post("/items/{item_key}/attachments", response_model=ItemDetailOut, status_code=201)
def upload(project_key: str, item_key: str, file: UploadFile = File(...), user: User = Depends(current_user),
           db: Session = Depends(get_db)) -> ItemDetailOut:
    project = get_project(db, project_key, user, "contributor")
    item = service.get_item(db, project, item_key)
    service.add_attachment(db, project, user, item, filename=file.filename or "file",
                           content_type=file.content_type or "application/octet-stream", stream=file.file)
    db.commit()
    return item_detail(db, project, item, UserDirectory(db))


INLINE_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp", "application/pdf"}


@router.get("/items/{item_key}/attachments/{attachment_id}")
def download(project_key: str, item_key: str, attachment_id: str, version: int | None = None, inline: bool = False,
             user: User = Depends(current_user), db: Session = Depends(get_db)) -> FileResponse:
    """Download a file; ``inline=true`` shows images and PDFs in the browser (other types always download)."""
    project = get_project(db, project_key, user)
    item = service.get_item(db, project, item_key)
    meta = service.find_attachment(db, item, attachment_id, version)
    path = storage.blob_path(meta["sha256"])
    if not path.exists():
        raise NotFound("File content missing in the file store")
    ctype = meta["content_type"].split(";")[0].strip().lower()
    if inline and ctype in INLINE_TYPES:
        headers = {} if ctype == "application/pdf" else {"Content-Security-Policy": "default-src 'none'; sandbox"}
        return FileResponse(path, media_type=ctype, filename=meta["filename"], content_disposition_type="inline",
                            headers=headers)
    return FileResponse(path, media_type=meta["content_type"], filename=meta["filename"])


@router.delete("/items/{item_key}/attachments/{attachment_id}", response_model=ItemDetailOut)
def remove_attachment(project_key: str, item_key: str, attachment_id: str, user: User = Depends(current_user),
                      db: Session = Depends(get_db)) -> ItemDetailOut:
    project = get_project(db, project_key, user, "contributor")
    item = service.get_item(db, project, item_key)
    service.remove_attachment(db, project, user, item, attachment_id)
    db.commit()
    return item_detail(db, project, item, UserDirectory(db))


# --- comments -------------------------------------------------------------------------------


def comment_threads(db: Session, comments: list[Comment], users: UserDirectory,
                    keys: dict[uuid.UUID, str] | None = None) -> list[CommentOut]:
    """Group comments into threads (root comments with their replies, oldest first)."""
    users.preload({c.author_id for c in comments} | {c.resolved_by for c in comments if c.resolved_by})
    doc_ids = {c.document_id for c in comments if c.document_id}
    doc_keys = dict(db.execute(select(Item.id, Item.key).where(Item.id.in_(doc_ids))).all()) if doc_ids else {}

    def out(c: Comment) -> CommentOut:
        return CommentOut(id=c.id, item_key=(keys or {}).get(c.item_id), author=users.ref(c.author_id),
                          external_author=c.external_author, source=c.source, body=c.body, created_at=c.created_at,
                          resolved=c.resolved_at is not None, resolved_at=c.resolved_at,
                          resolved_by=users.ref(c.resolved_by), document_key=doc_keys.get(c.document_id))

    roots = [c for c in comments if c.parent_id is None]
    replies: dict[uuid.UUID, list[Comment]] = {}
    for c in comments:
        if c.parent_id:
            replies.setdefault(c.parent_id, []).append(c)
    result = []
    for r in sorted(roots, key=lambda c: c.created_at):
        o = out(r)
        o.replies = [out(x) for x in sorted(replies.get(r.id, []), key=lambda c: c.created_at)]
        result.append(o)
    return result


@router.get("/items/{item_key}/comments", response_model=list[CommentOut])
def list_comments(project_key: str, item_key: str, resolved: bool = True, user: User = Depends(current_user),
                  db: Session = Depends(get_db)) -> list[CommentOut]:
    project = get_project(db, project_key, user)
    item = service.get_item(db, project, item_key)
    comments = db.execute(
        select(Comment).where(Comment.item_id == item.id, Comment.deleted_at.is_(None)).order_by(Comment.created_at)
    ).scalars().all()
    threads = comment_threads(db, list(comments), UserDirectory(db), {item.id: item.key})
    return threads if resolved else [t for t in threads if not t.resolved]


@router.post("/items/{item_key}/comments", response_model=CommentOut, status_code=201)
def add_comment(project_key: str, item_key: str, body: CommentIn, user: User = Depends(current_user),
                db: Session = Depends(get_db)) -> CommentOut:
    project = get_project(db, project_key, user, "contributor")
    document = service.get_item(db, project, body.document) if body.document else None
    comment = service.add_comment(db, project, user, service.get_item(db, project, item_key), body.body,
                                  parent_id=body.parent_id, document=document)
    db.commit()
    return CommentOut(id=comment.id, author=UserDirectory(db).ref(user.id), body=comment.body,
                      created_at=comment.created_at)


@router.post("/items/{item_key}/comments/{comment_id}/resolve", response_model=Ok)
def resolve_comment(project_key: str, item_key: str, comment_id: uuid.UUID, resolved: bool = True,
                    user: User = Depends(current_user), db: Session = Depends(get_db)) -> Ok:
    project = get_project(db, project_key, user, "contributor")
    service.resolve_comment(db, project, user, service.get_item(db, project, item_key), comment_id, resolved)
    db.commit()
    return Ok()


@router.delete("/items/{item_key}/comments/{comment_id}", response_model=Ok)
def delete_comment(project_key: str, item_key: str, comment_id: uuid.UUID, user: User = Depends(current_user),
                   db: Session = Depends(get_db)) -> Ok:
    project = get_project(db, project_key, user, "contributor")
    service.delete_comment(db, project, user, service.get_item(db, project, item_key), comment_id)
    db.commit()
    return Ok()


# --- recycle bin ----------------------------------------------------------------------------


@router.get("/recycle-bin", summary="Deleted items that can be restored")
def recycle_bin(project_key: str, user: User = Depends(current_user), db: Session = Depends(get_db)) -> list[dict]:
    project = get_project(db, project_key, user)
    items = db.execute(select(Item).where(Item.project_id == project.id, Item.deleted_at.is_not(None))
                       .order_by(Item.deleted_at.desc()).limit(500)).scalars().all()
    deleters = {}
    if items:
        for e in db.execute(select(AuditEntry).where(AuditEntry.action == "item.deleted",
                                                     AuditEntry.entity_id.in_([str(i.id) for i in items]))).scalars():
            deleters[e.entity_id] = e.actor_name
    return [{"key": i.key, "type_key": i.type_key, "title": i.title, "version": i.version_label,
             "deleted_at": i.deleted_at.isoformat(), "deleted_by": deleters.get(str(i.id))} for i in items]


@router.post("/items/{item_key}/undelete", response_model=ItemDetailOut, summary="Restore an item from the recycle bin")
def undelete(project_key: str, item_key: str, user: User = Depends(current_user),
             db: Session = Depends(get_db)) -> ItemDetailOut:
    project = get_project(db, project_key, user, "manager")
    item = service.get_item(db, project, item_key, include_deleted=True)
    service.undelete_item(db, project, user, item)
    db.commit()
    return item_detail(db, project, item, UserDirectory(db))


# --- structure / documents ---------------------------------------------------------------------


@router.get("/items/{item_key}/tree")
def tree(project_key: str, item_key: str, depth: int = Query(default=10, ge=1, le=30),
         content: bool = False, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    """The structural sub-tree below an item — a live document outline or a product structure."""
    project = get_project(db, project_key, user)
    root = service.get_item(db, project, item_key)
    structural = project.model.structural_link_types()
    users = UserDirectory(db)
    projects: dict[uuid.UUID, Project] = {project.id: project}

    def owner(item) -> Project:
        # Structures may reuse elements from other projects (platform modules).
        if item.project_id not in projects:
            projects[item.project_id] = db.get(Project, item.project_id)
        return projects[item.project_id]

    def node(item, link, level: int, seen: frozenset) -> dict[str, Any]:
        out = items_out(owner(item), [item], users)[0].model_dump(mode="json")
        if content:
            out["description"] = item.description
        if link is not None:
            out["link"] = {"id": str(link.id), "type": link.type_key, "position": link.position,
                           "attributes": link.attributes, "applicability": link.applicability,
                           "suspect": link.suspect}
        kids = []
        if level < depth:
            for child_link, child in links_svc.children(db, item, structural):
                if child.id not in seen:
                    kids.append(node(child, child_link, level + 1, seen | {child.id}))
        out["children"] = kids
        return out

    return node(root, None, 0, frozenset({root.id}))
