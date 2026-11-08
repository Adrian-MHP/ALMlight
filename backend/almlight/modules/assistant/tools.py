"""What the assistant may do in a project.

Every tool runs through the normal services with the role of the person who is chatting, so the assistant can
never read or change more than they can. Tools that change data (``writes=True``) are never executed by the
model: they are previewed in a savepoint that is rolled back, and only the person's confirmation applies them.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select

from almlight.core import richtext
from almlight.core.errors import Forbidden, ValidationFailed
from almlight.modules.audit.models import AuditEntry
from almlight.modules.identity.models import User
from almlight.modules.items import service as items_svc
from almlight.modules.items.models import Item
from almlight.modules.items.query import parse_query
from almlight.modules.links import service as links_svc
from almlight.modules.projects import service as projects_svc
from almlight.modules.projects.access import has_role
from almlight.modules.projects.models import Project
from almlight.modules.verification import service as verification_svc

MAX_ROWS = 50
MAX_TEXT = 4000


@dataclass
class Context:
    db: Any
    project: Project
    user: User

    def may_write(self) -> bool:
        return has_role(self.db, self.project, self.user, "contributor")


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    run: Callable[[Context, dict[str, Any]], dict[str, Any]]
    writes: bool = False
    # one line describing the proposed change, shown to the person before they confirm
    summary: Callable[[Context, dict[str, Any]], str] | None = None

    def schema(self) -> dict[str, Any]:
        return {"type": "function",
                "function": {"name": self.name, "description": self.description, "parameters": self.parameters}}


def _str(args: dict[str, Any], key: str, default: str = "") -> str:
    value = args.get(key)
    return value.strip() if isinstance(value, str) else default


def _int(args: dict[str, Any], key: str, default: int, lo: int, hi: int) -> int:
    try:
        return max(lo, min(hi, int(args.get(key, default))))
    except (TypeError, ValueError):
        return default


def _list(args: dict[str, Any], key: str) -> list[str]:
    value = args.get(key)
    if isinstance(value, str):
        value = [value]
    return [v for v in value if isinstance(v, str)] if isinstance(value, list) else []


def _fields(args: dict[str, Any], key: str = "fields") -> dict[str, Any]:
    value = args.get(key)
    return {str(k): v for k, v in value.items()} if isinstance(value, dict) else {}


def _item(ctx: Context, key: str) -> Item:
    if not key:
        raise ValidationFailed("Give the item key, e.g. SYS-12")
    return items_svc.get_item(ctx.db, ctx.project, key)


def _text(html: str | None, limit: int = MAX_TEXT) -> str:
    text = richtext.to_text(html or "").strip()
    return text[:limit] + " …" if len(text) > limit else text


def _item_row(ctx: Context, item: Item) -> dict[str, Any]:
    t = ctx.project.model.item_type(item.type_key)
    state = ctx.project.model.workflow(t.workflow).state(item.state) if t and t.workflow and item.state else None
    return {"key": item.key, "type": t.label if t else item.type_key, "title": item.title,
            "state": state.label if state else item.state, "version": item.version_label,
            "updated_at": item.updated_at.date().isoformat()}


# --- reading ----------------------------------------------------------------------------------------------


def _overview(ctx: Context, args: dict[str, Any]) -> dict[str, Any]:
    model = ctx.project.model
    types = []
    for t in model.item_types:
        fields = [{"key": f.key, "label": f.label, "type": f.type, "required": f.required,
                   "options": [o.key for o in f.options] or None,
                   "computed": f.computed or None} for f in t.fields]
        wf = model.workflow(t.workflow)
        types.append({"key": t.key, "label": t.label, "category": t.category, "prefix": t.prefix,
                      "change_controlled": t.change_controlled or None,
                      "states": [s.key for s in wf.states] if wf else None,
                      "fields": [{k: v for k, v in f.items() if v is not None} for f in fields]})
    links = [{"key": lt.key, "label": lt.label, "from": lt.sources, "to": lt.targets,
              "structural": lt.structural or None} for lt in model.link_types]
    from almlight.modules.items.query import BUILTIN, custom_fields

    fields = sorted(BUILTIN) + sorted(custom_fields(ctx.project))
    return {"project": {"key": ctx.project.key, "name": ctx.project.name, "description": ctx.project.description},
            "query_fields": fields,
            "your_role": "manager" if ctx.user.is_admin else (
                "contributor" if ctx.may_write() else "viewer"),
            "item_types": types, "link_types": [{k: v for k, v in lt.items() if v is not None} for lt in links],
            "statistics": projects_svc.stats(ctx.db, ctx.project)}


def _search(ctx: Context, args: dict[str, Any]) -> dict[str, Any]:
    ql = _str(args, "query_language")
    text, conditions = (None, [])
    if ql:
        try:
            text, conditions = parse_query(ctx.project, ql)
        except ValidationFailed as exc:
            return {"error": str(exc), "hint": "Use plain words in 'text' instead, or check the field names with "
                                               "project_overview."}
    link_type = _str(args, "link_type")
    has_link = args.get("has_link")
    if link_type and ctx.project.model.link_type(link_type) is None:
        return {"error": f"Unknown link type '{link_type}'", "hint": "project_overview lists the link types."}
    query = items_svc.ItemQuery(
        q=_str(args, "text") or text, types=_list(args, "types") or None, states=_list(args, "states") or None,
        conditions=conditions or None, sort=_str(args, "sort") or "-updated",
        limit=_int(args, "limit", 25, 1, MAX_ROWS), user_id=ctx.user.id,
        link_type=link_type or None,
        link_dir="in" if _str(args, "link_direction") == "incoming" else "out",
        link_exists=bool(has_link) if isinstance(has_link, bool) and link_type else None,
    )
    items, total = items_svc.query_items(ctx.db, ctx.project, query)
    # say what was counted: a total means nothing without the filter it belongs to
    applied = {"text": query.q, "types": query.types, "states": query.states, "query_language": ql or None,
               "link": f"{'has' if query.link_exists else 'lacks'} {query.link_dir}coming {query.link_type}"
                       if query.link_type and query.link_exists is not None else None}
    return {"total": total, "shown": len(items), "filter": {k: v for k, v in applied.items() if v},
            "items": [_item_row(ctx, i) for i in items]}


def _get_item(ctx: Context, args: dict[str, Any]) -> dict[str, Any]:
    item = _item(ctx, _str(args, "key"))
    t = ctx.project.model.item_type(item.type_key)
    labels = {f.key: f.label for f in (t.fields if t else [])}
    links = [{"type": ctx.project.model.link_type(v.link.type_key).label
              if ctx.project.model.link_type(v.link.type_key) else v.link.type_key,
              "direction": v.direction, "item": v.other.key, "title": v.other.title,
              "suspect": v.link.suspect or None}
             for v in links_svc.links_of(ctx.db, item)[:MAX_ROWS]]
    owner = ctx.db.get(User, item.owner_id) if item.owner_id else None
    return {**_item_row(ctx, item), "description": _text(item.description),
            "fields": {labels.get(k, k): v for k, v in item.fields.items() if v not in (None, "", [])},
            "owner": owner.display_name if owner else None,
            "links": [{k: v for k, v in link.items() if v is not None} for link in links],
            "attachments": [a.get("filename") for a in item.attachments][:20]}


def _coverage(ctx: Context, args: dict[str, Any]) -> dict[str, Any]:
    type_key = _str(args, "type")
    if ctx.project.model.item_type(type_key) is None:
        raise ValidationFailed(f"Unknown item type '{type_key}' — project_overview lists them")
    data = verification_svc.coverage(ctx.db, ctx.project, type_key)
    gaps = [{"key": r["key"], "title": r["title"], "refined_by": r["refined_by"], "satisfied_by": r["satisfied_by"],
             "test_cases": r["verified_by"], "verification": r["verification"]}
            for r in data.get("rows", [])
            if not (r["satisfied_by"] and r["verified_by"] and r["verification"] == "passed")][:MAX_ROWS]
    return {"total": data.get("total"), "refined_pct": data.get("refined_pct"),
            "allocated_pct": data.get("allocated_pct"), "with_tests_pct": data.get("with_tests_pct"),
            "verified_pct": data.get("verified_pct"),
            "legend": {"refined_by": "number of refining items", "satisfied_by": "allocated to elements",
                       "test_cases": "verifying test cases", "verification": "result of the last test run"},
            "items_with_gaps": gaps}


def _impact(ctx: Context, args: dict[str, Any]) -> dict[str, Any]:
    item = _item(ctx, _str(args, "key"))
    rows = links_svc.impact_analysis(ctx.db, ctx.project, item)[:MAX_ROWS]
    return {"item": item.key, "affected": [{"key": r.get("key"), "title": r.get("title"), "via": r.get("via"),
                                            "depth": r.get("depth")} for r in rows]}


def _history(ctx: Context, args: dict[str, Any]) -> dict[str, Any]:
    limit = _int(args, "limit", 20, 1, MAX_ROWS)
    stmt = select(AuditEntry).where(AuditEntry.project_id == ctx.project.id)
    key = _str(args, "key")
    if key:
        item = _item(ctx, key)
        stmt = stmt.where(AuditEntry.related_ids.contains([str(item.id)]))
    rows = ctx.db.execute(stmt.order_by(AuditEntry.id.desc()).limit(limit)).scalars().all()
    return {"changes": [{"at": r.ts.isoformat(timespec="minutes"), "who": r.actor_name, "what": r.summary}
                        for r in rows]}


# --- changing (previewed, applied only after the person confirms) -----------------------------------------


def _create_item(ctx: Context, args: dict[str, Any]) -> dict[str, Any]:
    type_key = _str(args, "type")
    item = items_svc.create_item(
        ctx.db, ctx.project, ctx.user, type_key=type_key, title=_str(args, "title"),
        description=richtext.plain_to_html(_str(args, "description")) if _str(args, "description") else "",
        fields=_fields(args) or None, change_note="Created by the assistant",
    )
    ctx.db.flush()
    return {"created": item.key, **_item_row(ctx, item)}


def _create_summary(ctx: Context, args: dict[str, Any]) -> str:
    t = ctx.project.model.item_type(_str(args, "type"))
    return f"Create {t.label if t else _str(args, 'type')}: “{_str(args, 'title')}”"


def _update_item(ctx: Context, args: dict[str, Any]) -> dict[str, Any]:
    item = _item(ctx, _str(args, "key"))
    before = {"title": item.title, "fields": dict(item.fields), "description": _text(item.description, 200)}
    description = args.get("description")
    change = items_svc.ContentChange(
        title=_str(args, "title") or None,
        description=richtext.plain_to_html(description.strip()) if isinstance(description, str) else None,
        fields=_fields(args) or None,
    )
    item = items_svc.update_item(ctx.db, ctx.project, ctx.user, item, change,
                                 change_note=_str(args, "reason") or "Changed by the assistant")
    ctx.db.flush()
    return {"updated": item.key, "version": item.version_label, "before": before,
            "after": {"title": item.title, "fields": item.fields, "description": _text(item.description, 200)}}


def _update_summary(ctx: Context, args: dict[str, Any]) -> str:
    changed = [name for name in ("title", "description") if _str(args, name)]
    changed += [f"{k}" for k in _fields(args)]
    return f"Change {_str(args, 'key')}: {', '.join(changed) or 'nothing'}"


def _create_link(ctx: Context, args: dict[str, Any]) -> dict[str, Any]:
    source, target = _item(ctx, _str(args, "from")), _item(ctx, _str(args, "to"))
    link = links_svc.create_link(ctx.db, ctx.project, ctx.user, type_key=_str(args, "type"),
                                 source=source, target=target)
    ctx.db.flush()
    lt = ctx.project.model.link_type(link.type_key)
    return {"linked": f"{source.key} {lt.label if lt else link.type_key} {target.key}"}


def _link_summary(ctx: Context, args: dict[str, Any]) -> str:
    lt = ctx.project.model.link_type(_str(args, "type"))
    return f"Link {_str(args, 'from')} {lt.label if lt else _str(args, 'type')} {_str(args, 'to')}"


def _add_comment(ctx: Context, args: dict[str, Any]) -> dict[str, Any]:
    item = _item(ctx, _str(args, "key"))
    items_svc.add_comment(ctx.db, ctx.project, ctx.user, item, _str(args, "body"))
    ctx.db.flush()
    return {"commented": item.key}


TOOLS: list[Tool] = [
    Tool("project_overview",
         "The project's information model (item types with their fields and states, link types) and its current "
         "numbers. Call this first when you need to know which types, fields or link types exist.",
         {"type": "object", "properties": {}}, _overview),
    Tool("search_items",
         "Find items of the project. Combine: plain words in 'text', a filter in 'query_language' (only the "
         "fields project_overview lists under query_fields, e.g. 'type:system_requirement state:approved', "
         "'priority:must', 'updated:-7d', 'owner:me'), and a traceability filter with link_type/has_link. "
         "Traceability gaps are asked for here, not in the query language: requirements nothing verifies are "
         "link_type='verifies', link_direction='incoming', has_link=false.",
         {"type": "object", "properties": {
             "text": {"type": "string", "description": "words to search in key, title and description"},
             "query_language": {"type": "string", "description": "filter in the project's query language"},
             "types": {"type": "array", "items": {"type": "string"}, "description": "item type keys"},
             "states": {"type": "array", "items": {"type": "string"}},
             "link_type": {"type": "string", "description": "link type key, e.g. verifies or satisfies"},
             "link_direction": {"type": "string", "enum": ["incoming", "outgoing"],
                                "description": "incoming: other items point at these (a test case verifies a "
                                               "requirement); outgoing: these point at others"},
             "has_link": {"type": "boolean", "description": "true: items that have such a link, false: items "
                                                            "that lack it (the gap)"},
             "sort": {"type": "string", "enum": ["key", "-updated", "title", "state"]},
             "limit": {"type": "integer", "minimum": 1, "maximum": MAX_ROWS}}}, _search),
    Tool("get_item",
         "Everything about one item: description, all fields, owner, state, version, its links and attachments.",
         {"type": "object", "properties": {"key": {"type": "string", "description": "item key, e.g. SYS-12"}},
          "required": ["key"]}, _get_item),
    Tool("coverage",
         "Traceability coverage of one item type: how many items are allocated and verified, and which have gaps.",
         {"type": "object", "properties": {"type": {"type": "string", "description": "item type key"}},
          "required": ["type"]}, _coverage),
    Tool("impact",
         "What a change of this item would affect: the items that depend on it and the documents containing it.",
         {"type": "object", "properties": {"key": {"type": "string"}}, "required": ["key"]}, _impact),
    Tool("history",
         "What happened recently in the project, or to one item (key): who changed what and when.",
         {"type": "object", "properties": {"key": {"type": "string"},
                                           "limit": {"type": "integer", "minimum": 1, "maximum": MAX_ROWS}}},
         _history),
    Tool("create_item",
         "Create a new item. Needs the person's confirmation, so describe what you are creating and why.",
         {"type": "object", "properties": {
             "type": {"type": "string", "description": "item type key from project_overview"},
             "title": {"type": "string"},
             "description": {"type": "string", "description": "plain text, line breaks allowed"},
             "fields": {"type": "object", "description": "field key -> value, as in the information model"}},
          "required": ["type", "title"]}, _create_item, writes=True, summary=_create_summary),
    Tool("update_item",
         "Change title, description or fields of an existing item. Only pass what should change. Needs the "
         "person's confirmation.",
         {"type": "object", "properties": {
             "key": {"type": "string"}, "title": {"type": "string"},
             "description": {"type": "string", "description": "plain text; replaces the current description"},
             "fields": {"type": "object", "description": "field key -> new value"},
             "reason": {"type": "string", "description": "short change note for the item's history"}},
          "required": ["key"]}, _update_item, writes=True, summary=_update_summary),
    Tool("create_link",
         "Link two items (traceability), e.g. a test case that verifies a requirement. Needs confirmation.",
         {"type": "object", "properties": {
             "type": {"type": "string", "description": "link type key from project_overview"},
             "from": {"type": "string", "description": "key of the source item"},
             "to": {"type": "string", "description": "key of the target item"}},
          "required": ["type", "from", "to"]}, _create_link, writes=True, summary=_link_summary),
    Tool("add_comment",
         "Write a comment on an item, e.g. a review remark. Needs confirmation.",
         {"type": "object", "properties": {"key": {"type": "string"}, "body": {"type": "string"}},
          "required": ["key", "body"]}, _add_comment, writes=True,
         summary=lambda ctx, a: f"Comment on {_str(a, 'key')}: “{_str(a, 'body')[:80]}”"),
]
BY_NAME = {t.name: t for t in TOOLS}


def schemas(ctx: Context) -> list[dict[str, Any]]:
    """The tools offered to the model: writing ones only for people who may write."""
    may_write = ctx.may_write()
    return [t.schema() for t in TOOLS if may_write or not t.writes]


def run(ctx: Context, name: str, args: dict[str, Any]) -> dict[str, Any]:
    tool = BY_NAME.get(name)
    if tool is None:
        raise ValidationFailed(f"Unknown tool '{name}'")
    if tool.writes and not ctx.may_write():
        raise Forbidden("This needs the contributor role in the project")
    return tool.run(ctx, args)


def preview(ctx: Context, name: str, args: dict[str, Any]) -> dict[str, Any]:
    """Run a changing tool inside a savepoint and roll it back: the result is exactly what applying would do."""
    savepoint = ctx.db.begin_nested()
    try:
        result = run(ctx, name, args)
    finally:
        savepoint.rollback()
    return result


def describe(ctx: Context, name: str, args: dict[str, Any]) -> str:
    tool = BY_NAME.get(name)
    if tool is None or tool.summary is None:
        return name
    try:
        return tool.summary(ctx, args)
    except Exception:  # noqa: BLE001 — a summary must never break the conversation
        return name


def new_id() -> str:
    return uuid.uuid4().hex[:12]
