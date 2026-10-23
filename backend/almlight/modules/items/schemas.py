from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from almlight.core.schemas import UserDirectory, UserRef
from almlight.modules.items.models import Item, ItemVersion
from almlight.modules.projects.models import Project


class Lifecycle(BaseModel):
    state: str | None
    label: str | None
    category: str | None
    color: str | None
    frozen: bool
    released: bool


class ItemOut(BaseModel):
    id: uuid.UUID
    key: str
    project_key: str
    type_key: str
    title: str
    lifecycle: Lifecycle
    revision: str
    iteration: int
    version: str
    version_no: int
    fields: dict[str, Any]
    applicability: str | None
    owner: UserRef | None
    updated_at: datetime
    created_at: datetime | None = None
    author: UserRef | None = None


class Attachment(BaseModel):
    id: str
    filename: str
    content_type: str
    size: int
    sha256: str
    uploaded_by: str | None = None
    uploaded_at: str | None = None
    revision: int = Field(default=1, description="File revision: increases with every check-in of new content")
    comment: str | None = None
    checked_out_by: UserRef | None = None
    checked_out_at: datetime | None = None
    checkout_note: str | None = None


class ItemDetailOut(ItemOut):
    description: str
    content_hash: str = Field(description="Identifies the current title/text (start state of a live editing session)")
    attachments: list[Attachment]
    released_version: str | None
    created_by: UserRef | None
    created_at: datetime
    updated_by: UserRef | None
    change_order: str | None = Field(description="Change order the current revision is implemented under")


class VersionOut(BaseModel):
    version_no: int
    version: str
    revision: str
    iteration: int
    kind: str
    title: str
    description: str
    fields: dict[str, Any]
    applicability: str | None
    attachments: list[Attachment]
    state: str | None
    change_note: str | None
    change_order: str | None
    created_by: UserRef | None
    created_at: datetime
    released: bool = False


class ItemIn(BaseModel):
    type: str
    title: str
    description: str = ""
    fields: dict[str, Any] = Field(default_factory=dict)
    applicability: str | None = None
    owner_id: uuid.UUID | None = None
    parent: str | None = Field(default=None, description="Key of a parent item (adds a structural link)")
    position: float | None = None


class ItemPatch(BaseModel):
    title: str | None = None
    description: str | None = None
    fields: dict[str, Any] | None = Field(default=None, description="Partial update; null removes a value")
    applicability: str | None = Field(default=None, description="Empty string removes the expression")
    owner_id: uuid.UUID | None = None
    expected_version: int | None = Field(default=None, description="Optimistic locking: current version_no")
    change_note: str | None = None


class ReviseIn(BaseModel):
    change_order: str | None = Field(default=None, description="Key of the change order (required if controlled)")
    change_note: str | None = None


class RestoreIn(BaseModel):
    version_no: int
    expected_version: int | None = None


class CommentIn(BaseModel):
    body: str
    parent_id: uuid.UUID | None = None
    document: str | None = Field(default=None, description="Key of the document the comment is made in")


class CommentOut(BaseModel):
    id: uuid.UUID
    item_key: str | None = None
    author: UserRef | None
    external_author: str | None = None
    source: str = "ui"
    body: str
    created_at: datetime
    resolved: bool = False
    resolved_at: datetime | None = None
    resolved_by: UserRef | None = None
    document_key: str | None = None
    replies: list[CommentOut] = Field(default_factory=list)


def lifecycle(project: Project, item: Item) -> Lifecycle:
    wf = project.model.workflow_for(item.type_key)
    s = wf.state(item.state) if wf else None
    return Lifecycle(state=item.state, label=s.label if s else None, category=s.category if s else None,
                     color=s.color if s else None, frozen=bool(s and s.frozen), released=bool(s and s.released))


def item_out(project: Project, item: Item, users: UserDirectory) -> ItemOut:
    return ItemOut(id=item.id, key=item.key, project_key=project.key, type_key=item.type_key, title=item.title,
                   lifecycle=lifecycle(project, item), revision=item.revision, iteration=item.iteration,
                   version=item.version_label, version_no=item.version_no, fields=item.fields,
                   applicability=item.applicability, owner=users.ref(item.owner_id), updated_at=item.updated_at,
                   created_at=item.created_at, author=users.ref(item.created_by))


def items_out(project: Project, items: list[Item], users: UserDirectory) -> list[ItemOut]:
    users.preload({i.owner_id for i in items} | {i.created_by for i in items})
    return [item_out(project, i, users) for i in items]


def item_detail(db: Session, project: Project, item: Item, users: UserDirectory) -> ItemDetailOut:
    base = item_out(project, item, users)
    released = None
    if item.released_version_id:
        v = db.get(ItemVersion, item.released_version_id)
        released = v.version_label if v else None
    head = db.get(ItemVersion, item.head_version_id) if item.head_version_id else None
    co_key = None
    if head and head.change_order_id:
        co_key = db.execute(select(Item.key).where(Item.id == head.change_order_id)).scalar()
    from almlight.core.richtext import content_hash
    from almlight.modules.files.service import for_items

    checkouts = for_items(db, [item.id]) if item.attachments else {}
    attachments = []
    for a in item.attachments:
        co = checkouts.get((item.id, a["id"]))
        attachments.append(Attachment(**a, checked_out_by=users.ref(co.user_id) if co else None,
                                      checked_out_at=co.checked_out_at if co else None,
                                      checkout_note=co.note if co else None))
    return ItemDetailOut(**base.model_dump(exclude={"created_at"}), description=item.description,
                         content_hash=content_hash(item.title, item.description),
                         attachments=attachments, released_version=released,
                         created_by=users.ref(item.created_by), created_at=item.created_at,
                         updated_by=users.ref(item.updated_by), change_order=co_key)


def version_out(db: Session, item: Item, v: ItemVersion, users: UserDirectory,
                co_keys: dict[uuid.UUID, str] | None = None) -> VersionOut:
    co = None
    if v.change_order_id:
        co = (co_keys or {}).get(v.change_order_id) or db.execute(
            select(Item.key).where(Item.id == v.change_order_id)).scalar()
    return VersionOut(version_no=v.version_no, version=v.version_label, revision=v.revision, iteration=v.iteration,
                      kind=v.kind, title=v.title, description=v.description, fields=v.fields,
                      applicability=v.applicability, attachments=[Attachment(**a) for a in v.attachments],
                      state=v.state, change_note=v.change_note, change_order=co, created_by=users.ref(v.created_by),
                      created_at=v.created_at, released=v.id == item.released_version_id)


CommentOut.model_rebuild()
