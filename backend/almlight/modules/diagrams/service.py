"""Architecture diagrams: views of the project's model.

A diagram is an ordinary item (type ``diagram``) whose ``content`` field holds the canvas: **nodes** that show
items of the project and **edges** that show links between them. The distinction that makes this modelling and
not drawing: an element can appear on several diagrams, removing it from a diagram leaves the item untouched,
and an edge *is* a typed link of the project — drawing one creates real traceability, deleting one can leave the
link in place. Because a diagram is an item, it is versioned, baselined, released and exported like everything
else.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from almlight.core.errors import NotFound, ValidationFailed
from almlight.modules.identity.models import User
from almlight.modules.items import service as items_svc
from almlight.modules.items.lifecycle import is_frozen
from almlight.modules.items.models import Item
from almlight.modules.links import service as links_svc
from almlight.modules.links.models import Link
from almlight.modules.projects.models import Project

TYPE_KEY = "diagram"
NODE_W, NODE_H = 180.0, 72.0
GAP_X, GAP_Y = 60.0, 50.0
NOTE_W, NOTE_H = 180.0, 90.0

# which element and relationship types a viewpoint suggests; "*" means everything the model has
VIEWPOINTS: dict[str, dict[str, list[str]]] = {
    "context": {"types": ["system_element", "function", "stakeholder_requirement"],
                "links": ["connects", "relates_to", "satisfies"]},
    "decomposition": {"types": ["system_element", "function"], "links": ["contains", "realizes"]},
    "internal": {"types": ["system_element", "interface", "function"],
                 "links": ["contains", "connects", "realizes", "relates_to"]},
    "allocation": {"types": ["system_requirement", "element_requirement", "system_element", "function",
                             "interface", "test_case"],
                   "links": ["satisfies", "derives_from", "verifies", "realizes"]},
    "deployment": {"types": ["system_element", "interface"], "links": ["contains", "connects"]},
    "free": {"types": ["*"], "links": ["*"]},
}


def get_diagram(db: Session, project: Project, key: str) -> Item:
    item = items_svc.get_item(db, project, key)
    if item.type_key != TYPE_KEY:
        raise ValidationFailed(f"{item.key} is not an architecture diagram")
    return item


def content_of(item: Item) -> dict[str, Any]:
    content = item.fields.get("content") or {}
    return {"nodes": list(content.get("nodes") or []), "edges": list(content.get("edges") or [])}


def _items_by_key(db: Session, project: Project, keys: list[str]) -> dict[str, Item]:
    if not keys:
        return {}
    rows = db.execute(select(Item).where(Item.project_id == project.id, Item.key.in_(keys),
                                         Item.deleted_at.is_(None))).scalars().all()
    return {i.key: i for i in rows}


def _links_by_id(db: Session, project: Project, ids: list[str]) -> dict[str, Link]:
    """Links of *this* project by id — a canvas comes from the browser, so a foreign id must not resolve."""
    valid = []
    for raw in ids:
        try:
            valid.append(uuid.UUID(raw))
        except ValueError:
            continue
    if not valid:
        return {}
    rows = db.execute(select(Link).where(Link.id.in_(valid), Link.project_id == project.id,
                                         Link.deleted_at.is_(None))).scalars().all()
    return {str(link.id): link for link in rows}


def edge_links(db: Session, project: Project, content: dict[str, Any],
               items: dict[str, Item]) -> dict[str, Link]:
    """The live link edge stands for.

    By its id, and when that is gone by *the same relationship between the same two items*: editing a link's
    attributes (a BOM quantity, an effectivity) closes the row and writes a new one with a new id, and a
    diagram must not lose its connection because of that.
    """
    by_id = _links_by_id(db, project, [e["link"] for e in content["edges"] if e.get("link")])
    nodes = {n["id"]: n for n in content["nodes"]}
    live: dict[tuple[Any, Any, str], Link] = {}
    ids = [i.id for i in items.values()]
    if ids:
        db.flush()
        for link in db.execute(select(Link).where(Link.source_id.in_(ids), Link.target_id.in_(ids),
                                                  Link.project_id == project.id,
                                                  Link.deleted_at.is_(None))).scalars():
            live.setdefault((link.source_id, link.target_id, link.type_key), link)
    out: dict[str, Link] = {}
    for e in content["edges"]:
        link = by_id.get(e.get("link") or "")
        if link is None and e.get("type"):
            source = items.get((nodes.get(e["from"]) or {}).get("item") or "")
            target = items.get((nodes.get(e["to"]) or {}).get("item") or "")
            if source is not None and target is not None:
                link = live.get((source.id, target.id, e["type"]))
        if link is not None:
            out[e["id"]] = link
    return out


def view(db: Session, project: Project, item: Item) -> dict[str, Any]:
    """The diagram with everything the canvas needs, and what no longer matches the model."""
    content = content_of(item)
    model = project.model
    items = _items_by_key(db, project, [n["item"] for n in content["nodes"] if n.get("item")])
    links = edge_links(db, project, content, items)
    nodes, missing = [], []
    for n in content["nodes"]:
        node = {k: n[k] for k in ("id", "x", "y", "w", "h")}
        if n.get("kind") == "note":
            nodes.append({**node, "kind": "note", "text": n.get("text", "")})
            continue
        shown = items.get(n["item"])
        if shown is None:  # the item was deleted after it was put on the canvas
            missing.append(n["item"])
            nodes.append({**node, "kind": "item", "item": n["item"], "missing": True})
            continue
        t = model.item_type(shown.type_key)
        state = model.workflow(t.workflow).state(shown.state) if t and t.workflow and shown.state else None
        nodes.append({**node, "kind": "item", "item": shown.key, "title": shown.title,
                      "type": shown.type_key, "type_label": t.label if t else shown.type_key,
                      "category": t.category if t else "other", "state": state.label if state else None,
                      "state_category": state.category if state else None, "version": shown.version_label})
    edges, dropped = [], []
    for e in content["edges"]:
        link = links.get(e["id"])
        if (e.get("link") or e.get("type")) and link is None:  # the relationship is gone from the model
            dropped.append(e["id"])
            continue
        lt = model.link_type(link.type_key) if link else None
        edges.append({"id": e["id"], "from": e["from"], "to": e["to"],
                      "link": str(link.id) if link else None,
                      "type": link.type_key if link else None, "label": lt.label if lt else None,
                      "suspect": bool(link.suspect) if link else False})
    return {"key": item.key, "title": item.title, "version": item.version_label, "version_no": item.version_no,
            "viewpoint": item.fields.get("viewpoint") or "free",
            "frozen": is_frozen(project, item),
            "nodes": nodes, "edges": edges,
            "stale": {"missing_items": sorted(set(missing)), "removed_links": dropped}}


def palette(project: Project, viewpoint: str | None) -> dict[str, Any]:
    """The element and relationship types this viewpoint suggests — a hint, never a restriction."""
    wanted = VIEWPOINTS.get(viewpoint or "free", VIEWPOINTS["free"])
    model = project.model
    types = [{"key": t.key, "label": t.label, "category": t.category} for t in model.item_types
             if t.key != TYPE_KEY and (wanted["types"] == ["*"] or t.key in wanted["types"])]
    links = [{"key": lt.key, "label": lt.label, "sources": lt.sources, "targets": lt.targets}
             for lt in model.link_types if wanted["links"] == ["*"] or lt.key in wanted["links"]]
    return {"viewpoint": viewpoint or "free", "suggested_types": types, "suggested_links": links,
            "all_types": [{"key": t.key, "label": t.label, "category": t.category} for t in model.item_types
                          if t.key != TYPE_KEY]}


def _save(db: Session, project: Project, actor: User, item: Item, content: dict[str, Any],
          note: str, expected_version: int | None = None) -> Item:
    change = items_svc.ContentChange(fields={"content": content})
    return items_svc.update_item(db, project, actor, item, change, change_note=note,
                                 expected_version=expected_version)


def _free_place(nodes: list[dict[str, Any]], index: int = 0) -> tuple[float, float]:
    """A spot below everything that is already there, in rows of four."""
    bottom = max((n["y"] + n["h"] for n in nodes), default=-GAP_Y)
    return GAP_X + (index % 4) * (NODE_W + GAP_X), bottom + GAP_Y + (index // 4) * (NODE_H + GAP_Y)


def add_items(db: Session, project: Project, actor: User, item: Item, keys: list[str],
              content: dict[str, Any] | None = None, at: tuple[float, float] | None = None) -> Item:
    """Put existing items on the canvas; items already shown are skipped."""
    content = content if content is not None else content_of(item)
    shown = {n.get("item") for n in content["nodes"]}
    found = _items_by_key(db, project, [k.strip().upper() for k in keys])
    missing = [k for k in keys if k.strip().upper() not in found]
    if missing:
        raise NotFound(f"Not in this project: {', '.join(sorted(missing))}")
    added = 0
    before = list(content["nodes"])  # the places are measured against what was there, so a row stays a row
    for key in [k.strip().upper() for k in keys]:
        if key in shown:
            continue
        x, y = at if at and added == 0 else _free_place(before, added)
        content["nodes"].append({"id": f"n{uuid.uuid4().hex[:8]}", "item": key, "x": x, "y": y,
                                 "w": NODE_W, "h": NODE_H})
        added += 1
    if not added:
        raise ValidationFailed("Already on the diagram")
    return _save(db, project, actor, item, with_known_links(db, project, content),
                 f"Added {added} element(s) to the diagram")


def add_note(db: Session, project: Project, actor: User, item: Item, text: str,
             content: dict[str, Any] | None = None) -> Item:
    content = content if content is not None else content_of(item)
    x, y = _free_place(content["nodes"])
    content["nodes"].append({"id": f"n{uuid.uuid4().hex[:8]}", "kind": "note", "text": text, "x": x, "y": y,
                            "w": NOTE_W, "h": NOTE_H})
    return _save(db, project, actor, item, content, "Added a note to the diagram")


def with_known_links(db: Session, project: Project, content: dict[str, Any]) -> dict[str, Any]:
    """Draw the links that already exist between the items on the canvas (nothing is created here)."""
    by_key = {n["item"]: n["id"] for n in content["nodes"] if n.get("item")}
    if len(by_key) < 2:
        return content
    db.flush()  # the session does not flush by itself: links written in this transaction must be visible here
    items = _items_by_key(db, project, list(by_key))
    ids = {i.id: key for key, i in items.items()}
    have = {e.get("link") for e in content["edges"]}
    # also by what the edge shows: editing a link closes its row and writes a new id, and the relationship
    # that is already on the canvas must not be drawn a second time under the successor's id
    drawn = {(e["from"], e["to"], e.get("type")) for e in content["edges"]}
    rows = db.execute(select(Link).where(Link.source_id.in_(ids), Link.target_id.in_(ids),
                                         Link.project_id == project.id,
                                         Link.deleted_at.is_(None))).scalars().all()
    for link in rows:
        if str(link.id) in have:
            continue
        source, target = ids.get(link.source_id), ids.get(link.target_id)
        if not source or not target or source == target:
            continue
        if (by_key[source], by_key[target], link.type_key) in drawn:
            continue
        content["edges"].append({"id": f"e{uuid.uuid4().hex[:8]}", "from": by_key[source],
                                 "to": by_key[target], "link": str(link.id), "type": link.type_key})
    return content


def related(db: Session, project: Project, item: Item, keys: list[str], limit: int = 25) -> list[dict[str, Any]]:
    """Items linked to the ones already shown — the offer for "add what belongs to this"."""
    db.flush()  # see with_known_links: pending changes of this transaction must be visible
    shown = _items_by_key(db, project, keys)
    if not shown:
        return []
    ids = [i.id for i in shown.values()]
    out: dict[str, dict[str, Any]] = {}
    for link in db.execute(select(Link).where(Link.deleted_at.is_(None), Link.project_id == project.id,
                                              (Link.source_id.in_(ids)) | (Link.target_id.in_(ids)))).scalars():
        other_id = link.target_id if link.source_id in ids else link.source_id
        other = db.get(Item, other_id)
        if other is None or other.deleted_at or other.key in shown or other.project_id != project.id:
            continue
        lt = project.model.link_type(link.type_key)
        t = project.model.item_type(other.type_key)
        out.setdefault(other.key, {"key": other.key, "title": other.title,
                                   "type_label": t.label if t else other.type_key,
                                   "via": lt.label if lt else link.type_key})
    return sorted(out.values(), key=lambda r: r["key"])[:limit]


def connect(db: Session, project: Project, actor: User, item: Item, *, source_node: str, target_node: str,
            type_key: str, content: dict[str, Any] | None = None) -> Item:
    """Draw a relationship: this creates a real link in the project, with all its rules."""
    content = content if content is not None else content_of(item)
    by_id = {n["id"]: n for n in content["nodes"]}
    source, target = by_id.get(source_node), by_id.get(target_node)
    if source is None or target is None:
        raise NotFound("The diagram has no such node")
    if not source.get("item") or not target.get("item"):
        raise ValidationFailed("A note cannot be connected")
    source_item = items_svc.get_item(db, project, source["item"])
    target_item = items_svc.get_item(db, project, target["item"])
    link = links_svc.create_link(db, project, actor, type_key=type_key, source=source_item, target=target_item)
    db.flush()
    content["edges"].append({"id": f"e{uuid.uuid4().hex[:8]}", "from": source_node, "to": target_node,
                             "link": str(link.id), "type": type_key})
    lt = project.model.link_type(type_key)
    return _save(db, project, actor, item, content,
                 f"{source_item.key} {lt.label if lt else type_key} {target_item.key}")


def remove_node(db: Session, project: Project, actor: User, item: Item, node_id: str,
                content: dict[str, Any] | None = None) -> Item:
    """Take an element off the canvas. The item itself and its links stay — this is a view, not the model."""
    content = content if content is not None else content_of(item)
    node = next((n for n in content["nodes"] if n["id"] == node_id), None)
    if node is None:
        raise NotFound("The diagram has no such node")
    content["nodes"] = [n for n in content["nodes"] if n["id"] != node_id]
    content["edges"] = [e for e in content["edges"] if node_id not in (e["from"], e["to"])]
    what = node.get("item") or "the note"
    return _save(db, project, actor, item, content, f"Removed {what} from the diagram")


def remove_edge(db: Session, project: Project, actor: User, item: Item, edge_id: str, *, delete_link: bool,
                content: dict[str, Any] | None = None) -> Item:
    """Take a relationship off the canvas, and only on request delete the link it shows."""
    content = content if content is not None else content_of(item)
    edge = next((e for e in content["edges"] if e["id"] == edge_id), None)
    if edge is None:
        raise NotFound("The diagram has no such relationship")
    content["edges"] = [e for e in content["edges"] if e["id"] != edge_id]
    note = "Removed a relationship from the diagram"
    if delete_link and (edge.get("link") or edge.get("type")):
        stored = content_of(item)
        items = _items_by_key(db, project, [n["item"] for n in stored["nodes"] if n.get("item")])
        link = edge_links(db, project, stored, items).get(edge_id)
        if link is None:
            raise NotFound("This relationship no longer exists in the project")
        links_svc.delete_link(db, project, actor, link)
        note = "Deleted a link and removed it from the diagram"
    return _save(db, project, actor, item, content, note)


def layout(db: Session, project: Project, actor: User, item: Item,
           content: dict[str, Any] | None = None) -> Item:
    """Arrange the canvas in layers: what contains or derives from something else stands above it."""
    content = content if content is not None else content_of(item)
    content["nodes"] = arrange(content["nodes"], content["edges"])
    return _save(db, project, actor, item, content, "Arranged the diagram")


def arrange(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Longest-path layering: every node sits below everything that points at it, cycles are broken by order."""
    order = {n["id"]: i for i, n in enumerate(nodes)}
    incoming: dict[str, list[str]] = {n["id"]: [] for n in nodes}
    for e in edges:
        if e["from"] in incoming and e["to"] in incoming and e["from"] != e["to"]:
            incoming[e["to"]].append(e["from"])
    depth: dict[str, int] = {}

    def rank(node_id: str, seen: frozenset[str]) -> int:
        if node_id in depth:
            return depth[node_id]
        if node_id in seen:
            return 0
        parents = [p for p in incoming[node_id] if order[p] != order[node_id]]
        value = max((rank(p, seen | {node_id}) + 1 for p in parents), default=0)
        depth[node_id] = min(value, 20)
        return depth[node_id]

    for n in nodes:
        rank(n["id"], frozenset())
    rows: dict[int, list[dict[str, Any]]] = {}
    for n in sorted(nodes, key=lambda n: order[n["id"]]):
        rows.setdefault(depth.get(n["id"], 0), []).append(n)
    placed = []
    y = GAP_Y
    for level in sorted(rows):
        row = rows[level]
        x = GAP_X
        for n in row:
            placed.append({**n, "x": x, "y": y})
            x += n["w"] + GAP_X
        y += max(n["h"] for n in row) + GAP_Y
    return placed
