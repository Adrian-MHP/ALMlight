"""Link management, suspect propagation, traceability and impact analysis."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select, text, update
from sqlalchemy.orm import Session

from almlight.core.db import utcnow
from almlight.core.errors import Conflict, Forbidden, Locked, NotFound, ValidationFailed
from almlight.modules.audit import service as audit
from almlight.modules.identity.models import User
from almlight.modules.integrations.outbox import emit
from almlight.modules.items.fields import normalize_fields
from almlight.modules.items.lifecycle import is_frozen
from almlight.modules.items.models import Item
from almlight.modules.links.models import Link
from almlight.modules.projects.access import has_role
from almlight.modules.projects.metamodel import LinkTypeDef
from almlight.modules.projects.models import Project
from almlight.modules.variants.expressions import normalize as normalize_expr

_UNSET: Any = object()


def _link_type(project: Project, type_key: str) -> LinkTypeDef:
    lt = project.model.link_type(type_key)
    if lt is None:
        raise ValidationFailed(f"Unknown link type '{type_key}'")
    return lt


def get_link(db: Session, project: Project, link_id: uuid.UUID) -> Link:
    link = db.get(Link, link_id)
    if link is None or link.deleted_at is not None or link.project_id != project.id:
        raise NotFound("Link not found")
    return link


def _ensure_source_editable(project: Project, lt: LinkTypeDef, source: Item) -> None:
    if not lt.editable_on_frozen_source and is_frozen(project, source):
        raise Locked(
            f"{source.key} is frozen — links of type '{lt.label}' belong to it and cannot change now",
            {"item": source.key, "state": source.state},
        )


def _creates_cycle(db: Session, type_key: str, source_id: uuid.UUID, target_id: uuid.UUID) -> bool:
    # Adding source -> target closes a cycle if target already reaches source.
    sql = text(
        """
        WITH RECURSIVE reach(id) AS (
            SELECT CAST(:target AS uuid)
            UNION
            SELECT l.target_id FROM links l JOIN reach r ON l.source_id = r.id
            WHERE l.type_key = :type AND l.deleted_at IS NULL
        )
        SELECT EXISTS (SELECT 1 FROM reach WHERE id = CAST(:source AS uuid))
        """
    )
    return bool(db.execute(sql, {"target": str(target_id), "source": str(source_id), "type": type_key}).scalar())


def create_link(
    db: Session,
    project: Project,
    actor: User | None,
    *,
    type_key: str,
    source: Item,
    target: Item,
    position: float | None = None,
    attributes: dict[str, Any] | None = None,
    applicability: str | None = None,
) -> Link:
    lt = _link_type(project, type_key)
    if source.project_id != project.id:
        raise ValidationFailed("The source item must belong to this project")
    if source.deleted_at or target.deleted_at:
        raise ValidationFailed("Cannot link deleted items")
    if source.id == target.id:
        raise ValidationFailed("An item cannot link to itself")
    if target.project_id != project.id:
        target_project = db.get(Project, target.project_id)
        if target_project is None or not has_role(db, target_project, actor, "viewer"):
            raise Forbidden("No access to the target item's project")
        target_type = target_project.model.item_type(target.type_key)
        if target_type is None or not lt.allows(source.type_key, target.type_key):
            raise ValidationFailed(f"Link type '{lt.label}' does not allow {source.type_key} -> {target.type_key}")
    elif not lt.allows(source.type_key, target.type_key):
        raise ValidationFailed(
            f"Link type '{lt.label}' does not allow {source.type_key} -> {target.type_key}",
            {"allowed_sources": lt.sources, "allowed_targets": lt.targets},
        )
    _ensure_source_editable(project, lt, source)
    duplicate = db.execute(
        select(Link.id).where(
            Link.type_key == type_key,
            Link.source_id == source.id,
            Link.target_id == target.id,
            Link.deleted_at.is_(None),
        )
    ).scalar()
    if duplicate:
        raise Conflict(f"{source.key} already {lt.label} {target.key}")
    if lt.acyclic and _creates_cycle(db, type_key, source.id, target.id):
        raise ValidationFailed(f"Linking {source.key} {lt.label} {target.key} would create a cycle")
    attrs = normalize_fields(db, lt.attributes, attributes or {}, apply_defaults=True, what="link attribute")
    if lt.structural and position is None:
        current_max = db.execute(
            select(func.max(Link.position)).where(
                Link.source_id == source.id, Link.type_key == type_key, Link.deleted_at.is_(None)
            )
        ).scalar()
        position = (current_max or 0) + 1
    link = Link(
        project_id=project.id,
        type_key=type_key,
        source_id=source.id,
        target_id=target.id,
        position=position,
        attributes=attrs,
        applicability=normalize_expr(applicability),
        created_by=actor.id if actor else None,
    )
    db.add(link)
    db.flush()
    audit.record(
        db,
        actor=actor,
        action="link.created",
        entity_type="link",
        entity_id=link.id,
        project_id=project.id,
        summary=f"{source.key} {lt.label} {target.key}",
        details={"type": type_key, "source": source.key, "target": target.key, "attributes": attrs},
        related_ids=[source.id, target.id],
    )
    emit(db, "link.created", project.id, {"link_id": link.id, "type": type_key, "source": source.key,
                                          "target": target.key})
    return link


def update_link(
    db: Session,
    project: Project,
    actor: User | None,
    link: Link,
    *,
    position: float | None = _UNSET,
    attributes: dict[str, Any] | None = _UNSET,
    applicability: str | None = _UNSET,
) -> Link:
    lt = _link_type(project, link.type_key)
    source = db.get(Item, link.source_id)
    assert source is not None
    _ensure_source_editable(project, lt, source)
    changes: dict[str, Any] = {}
    if position is not _UNSET and position != link.position:
        changes["position"] = [link.position, position]
        link.position = position
    if attributes is not _UNSET:
        attrs = normalize_fields(db, lt.attributes, attributes or {}, base=link.attributes, what="link attribute")
        if attrs != link.attributes:
            changes["attributes"] = [link.attributes, attrs]
            link.attributes = attrs
    if applicability is not _UNSET:
        expr = normalize_expr(applicability)
        if expr != link.applicability:
            changes["applicability"] = [link.applicability, expr]
            link.applicability = expr
    if changes:
        target = db.get(Item, link.target_id)
        audit.record(
            db,
            actor=actor,
            action="link.updated",
            entity_type="link",
            entity_id=link.id,
            project_id=project.id,
            summary=f"Updated link {source.key} {lt.label} {target.key if target else ''}",
            details=changes,
            related_ids=[link.source_id, link.target_id],
        )
    return link


def delete_link(db: Session, project: Project, actor: User | None, link: Link) -> None:
    lt = _link_type(project, link.type_key)
    source = db.get(Item, link.source_id)
    target = db.get(Item, link.target_id)
    assert source is not None and target is not None
    _ensure_source_editable(project, lt, source)
    link.deleted_at = utcnow()
    link.deleted_by = actor.id if actor else None
    audit.record(
        db,
        actor=actor,
        action="link.deleted",
        entity_type="link",
        entity_id=link.id,
        project_id=project.id,
        summary=f"Removed: {source.key} {lt.label} {target.key}",
        details={"type": link.type_key, "source": source.key, "target": target.key},
        related_ids=[source.id, target.id],
    )
    emit(db, "link.deleted", project.id, {"link_id": link.id, "type": link.type_key, "source": source.key,
                                          "target": target.key})


def confirm_link(db: Session, project: Project, actor: User | None, link: Link, comment: str | None = None) -> Link:
    """Clear the suspect flag after reviewing the changed target."""
    if not link.suspect:
        return link
    source = db.get(Item, link.source_id)
    target = db.get(Item, link.target_id)
    link.suspect = False
    link.suspect_reason = None
    link.suspect_since = None
    link.confirmed_by = actor.id if actor else None
    link.confirmed_at = utcnow()
    audit.record(
        db,
        actor=actor,
        action="link.confirmed",
        entity_type="link",
        entity_id=link.id,
        project_id=project.id,
        summary=f"Confirmed suspect link {source.key if source else ''} -> {target.key if target else ''}",
        details={"comment": comment},
        related_ids=[link.source_id, link.target_id],
    )
    return link


def mark_suspects(db: Session, project: Project, item: Item, reason: str) -> int:
    """Flag links that depend on ``item`` (item is target) after a content change."""
    types = [lt.key for lt in project.model.link_types if lt.suspect_on_target_change]
    if not types:
        return 0
    result = db.execute(
        update(Link)
        .where(
            Link.target_id == item.id,
            Link.deleted_at.is_(None),
            Link.suspect.is_(False),
            Link.type_key.in_(types),
        )
        .values(suspect=True, suspect_since=utcnow(), suspect_reason=reason)
    )
    return result.rowcount or 0


def soft_delete_links_of(db: Session, item: Item, actor: User | None) -> int:
    result = db.execute(
        update(Link)
        .where(Link.deleted_at.is_(None), (Link.source_id == item.id) | (Link.target_id == item.id))
        .values(deleted_at=utcnow(), deleted_by=actor.id if actor else None)
    )
    return result.rowcount or 0


# --- queries -----------------------------------------------------------------------------


@dataclass
class LinkView:
    link: Link
    other: Item
    direction: str  # outgoing | incoming


def links_of(db: Session, item: Item) -> list[LinkView]:
    out: list[LinkView] = []
    rows = db.execute(
        select(Link, Item)
        .join(Item, Item.id == Link.target_id)
        .where(Link.source_id == item.id, Link.deleted_at.is_(None), Item.deleted_at.is_(None))
        .order_by(Link.type_key, Link.position.nulls_last(), Item.key)
    ).all()
    out += [LinkView(link, other, "outgoing") for link, other in rows]
    rows = db.execute(
        select(Link, Item)
        .join(Item, Item.id == Link.source_id)
        .where(Link.target_id == item.id, Link.deleted_at.is_(None), Item.deleted_at.is_(None))
        .order_by(Link.type_key, Item.key)
    ).all()
    out += [LinkView(link, other, "incoming") for link, other in rows]
    return out


def children(db: Session, parent: Item, structural_types: list[str]) -> list[tuple[Link, Item]]:
    rows = db.execute(
        select(Link, Item)
        .join(Item, Item.id == Link.target_id)
        .where(
            Link.source_id == parent.id,
            Link.type_key.in_(structural_types),
            Link.deleted_at.is_(None),
            Item.deleted_at.is_(None),
        )
        .order_by(Link.position.nulls_last(), Item.key)
    ).all()
    return [(link, item) for link, item in rows]


def descendant_ids(db: Session, root_id: uuid.UUID, structural_types: list[str]) -> list[uuid.UUID]:
    """All items below ``root_id`` along structural links (excluding the root)."""
    if not structural_types:
        return []
    sql = text(
        """
        WITH RECURSIVE tree(id) AS (
            SELECT l.target_id FROM links l
            WHERE l.source_id = CAST(:root AS uuid) AND l.deleted_at IS NULL AND l.type_key = ANY(:types)
            UNION
            SELECT l.target_id FROM links l JOIN tree t ON l.source_id = t.id
            WHERE l.deleted_at IS NULL AND l.type_key = ANY(:types)
        )
        SELECT t.id FROM tree t JOIN items i ON i.id = t.id WHERE i.deleted_at IS NULL
        """
    )
    return [r[0] for r in db.execute(sql, {"root": str(root_id), "types": structural_types})]


def impact_analysis(db: Session, project: Project, item: Item, max_depth: int = 8) -> list[dict[str, Any]]:
    """Items affected by a change of ``item``.

    Follows dependency links backwards (everything that depends on the item, transitively:
    derived requirements, satisfying elements, verifying tests, ...) and adds the
    *where-used* chain along structural links (documents and assemblies containing them).
    """
    dep_types = [lt.key for lt in project.model.link_types if lt.suspect_on_target_change]
    structural = project.model.structural_link_types()
    found: dict[uuid.UUID, dict[str, Any]] = {}
    if dep_types:
        sql = text(
            """
            WITH RECURSIVE impact(item_id, depth, via_type, via_item, path) AS (
                SELECT l.source_id, 1, l.type_key, l.target_id, ARRAY[l.target_id, l.source_id]
                FROM links l
                WHERE l.target_id = CAST(:root AS uuid) AND l.deleted_at IS NULL AND l.type_key = ANY(:types)
                UNION ALL
                SELECT l.source_id, i.depth + 1, l.type_key, l.target_id, i.path || l.source_id
                FROM links l JOIN impact i ON l.target_id = i.item_id
                WHERE l.deleted_at IS NULL AND l.type_key = ANY(:types)
                  AND NOT (l.source_id = ANY(i.path)) AND i.depth < :max
            )
            SELECT DISTINCT ON (item_id) item_id, depth, via_type, via_item
            FROM impact ORDER BY item_id, depth
            """
        )
        for row in db.execute(sql, {"root": str(item.id), "types": dep_types, "max": max_depth}):
            found[row.item_id] = {"depth": row.depth, "via": row.via_type, "via_item_id": row.via_item,
                                  "relation": "depends"}
    if structural:
        seeds = [item.id, *found.keys()]
        sql = text(
            """
            WITH RECURSIVE up(item_id, depth, via_item, path) AS (
                SELECT l.source_id, 1, l.target_id, ARRAY[l.target_id, l.source_id]
                FROM links l
                WHERE l.target_id = ANY(:seeds) AND l.deleted_at IS NULL AND l.type_key = ANY(:types)
                UNION ALL
                SELECT l.source_id, u.depth + 1, l.target_id, u.path || l.source_id
                FROM links l JOIN up u ON l.target_id = u.item_id
                WHERE l.deleted_at IS NULL AND l.type_key = ANY(:types)
                  AND NOT (l.source_id = ANY(u.path)) AND u.depth < :max
            )
            SELECT DISTINCT ON (item_id) item_id, depth, via_item FROM up ORDER BY item_id, depth
            """
        )
        for row in db.execute(sql, {"seeds": seeds, "types": structural, "max": max_depth}):
            if row.item_id not in found and row.item_id != item.id:
                found[row.item_id] = {"depth": row.depth, "via": "contains", "via_item_id": row.via_item,
                                      "relation": "where_used"}
    if not found:
        return []
    items = {
        i.id: i
        for i in db.execute(select(Item).where(Item.id.in_(found.keys()), Item.deleted_at.is_(None))).scalars()
    }
    via_keys = {
        i.id: i.key
        for i in db.execute(
            select(Item).where(Item.id.in_({f["via_item_id"] for f in found.values()}))
        ).scalars()
    }
    result = []
    for iid, info in found.items():
        it = items.get(iid)
        if it is None:
            continue
        result.append({"item": it, "via_item_key": via_keys.get(info["via_item_id"]), **info})
    result.sort(key=lambda r: (r["depth"], r["item"].type_key, r["item"].key))
    return result
