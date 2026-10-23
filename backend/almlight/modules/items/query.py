"""Item queries: structured filter conditions and a Polarion-like query language.

A query is free text plus a list of **conditions** ``{field, op, values, not}``. Fields are built-in properties
(``type``, ``state``, ``owner``, ``created`` …), traceability (``link.<type>.out|in``), planning (``release``) or a
custom field of the information model (``field.<key>``). The query language is a readable form of the same
conditions, close to what Polarion users type:

    type:system_requirement state:(draft OR in_review) priority:must NOT link.verifies.in:* updated:[-30d TO *]

Clauses are combined with AND (``AND`` may be written or left out); ``OR`` combines values inside parentheses;
``NOT`` (or a leading ``-``) negates a clause; ``field:*`` means "has a value"; ``[a TO b]`` is a range (``*`` =
open end); dates accept ``YYYY-MM-DD``, ``today`` and relative values like ``-7d``, ``+2w``, ``-3m``; user fields
accept user names, ``me`` and ``none``. Words without a field search key, title and text.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import ColumnElement, Numeric, String, and_, case, cast, false, func, not_, or_, select, true
from sqlalchemy.dialects.postgresql import ARRAY

from almlight.core.errors import ValidationFailed
from almlight.modules.items.models import Item
from almlight.modules.links.models import Link
from almlight.modules.projects.metamodel import FieldDef
from almlight.modules.projects.models import Project

OPS = ("in", "contains", "between", "exists", "is")
MAX_CONDITIONS = 40
MAX_VALUES = 500


class Condition(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    field: str = Field(max_length=120)
    op: str = "in"
    values: list[Any] = Field(default_factory=list, max_length=MAX_VALUES)
    negate: bool = Field(default=False, alias="not")

    def dump(self) -> dict[str, Any]:
        out: dict[str, Any] = {"field": self.field, "op": self.op, "values": self.values}
        if self.negate:
            out["not"] = True
        return out


@dataclass(frozen=True)
class FieldInfo:
    """What a query field is: its kind decides operators and value parsing."""

    name: str      # as written in the query language
    kind: str      # enum | user | text | number | date | bool | link | release | multi
    label: str
    custom: FieldDef | None = None


BUILTIN: dict[str, tuple[str, str]] = {
    "type": ("enum", "Type"),
    "state": ("enum", "Status"),
    "category": ("enum", "Status category"),
    "owner": ("user", "Owner"),
    "author": ("user", "Created by"),
    "created": ("date", "Created"),
    "updated": ("date", "Updated"),
    "key": ("enum", "Key"),
    "title": ("text", "Title"),
    "text": ("text", "Text"),
    "revision": ("enum", "Revision"),
    "applicability": ("text", "Applicability"),
    "released": ("bool", "Has a released version"),
    "frozen": ("bool", "Frozen"),
    "suspect": ("bool", "Has suspect links"),
    "watched": ("bool", "Watched by me"),
    "checkedout": ("bool", "Has checked-out files"),
    "attachments": ("bool", "Has files"),
    "release": ("release", "Planned in"),
}
_KIND_OF_FIELD = {"enum": "enum", "user": "user", "string": "text", "text": "text", "url": "text", "integer": "number",
                  "number": "number", "date": "date", "boolean": "bool", "multienum": "multi", "tags": "multi"}


def custom_fields(project: Project) -> dict[str, FieldDef]:
    """Custom fields across all item types (first definition of a key wins)."""
    out: dict[str, FieldDef] = {}
    for t in project.model.item_types:
        for f in t.fields:
            if f.type != "steps":
                out.setdefault(f.key, f)
    return out


def field_info(project: Project, name: str) -> FieldInfo:
    if name.startswith("field."):
        key = name[6:]
        f = custom_fields(project).get(key)
        if f is None:
            raise ValidationFailed(f"Unknown field '{key}'", {"field": name})
        return FieldInfo(name, _KIND_OF_FIELD.get(f.type, "text"), f.label, f)
    if name.startswith("link."):
        parts = name.split(".")
        if len(parts) != 3 or parts[2] not in ("in", "out") or project.model.link_type(parts[1]) is None:
            raise ValidationFailed(f"Unknown link filter '{name}' (use link.<type>.out or link.<type>.in)",
                                   {"field": name})
        lt = project.model.link_type(parts[1])
        return FieldInfo(name, "link", lt.label if parts[2] == "out" else lt.reverse_label)
    if name in BUILTIN:
        kind, label = BUILTIN[name]
        return FieldInfo(name, kind, label)
    raise ValidationFailed(f"Unknown query field '{name}'", {"field": name})


# --- values ---------------------------------------------------------------------------------------------------

_REL = re.compile(r"^([+-]\d{1,4})([dwmy])$")


def resolve_date(value: Any) -> date | None:
    if value in (None, "", "*"):
        return None
    s = str(value).strip().lower()
    today = datetime.now(UTC).date()
    if s == "today":
        return today
    m = _REL.match(s)
    if m:
        n, unit = int(m.group(1)), m.group(2)
        days = {"d": 1, "w": 7, "m": 30, "y": 365}[unit] * n
        return today + timedelta(days=days)
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        raise ValidationFailed(f"'{value}' is not a date (YYYY-MM-DD, today, -7d, +2w, -3m)") from None


def _number(value: Any) -> float | None:
    if value in (None, "", "*"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        raise ValidationFailed(f"'{value}' is not a number") from None


def _bool(values: list[Any]) -> bool:
    v = values[0] if values else True
    if isinstance(v, bool):
        return v
    s = str(v).lower()
    if s in ("true", "yes", "1"):
        return True
    if s in ("false", "no", "0"):
        return False
    raise ValidationFailed(f"'{v}' is not true or false")


# --- SQL ------------------------------------------------------------------------------------------------------


@dataclass
class Context:
    project: Project
    user_id: uuid.UUID | None
    db: Any


def _user_ids(ctx: Context, values: list[Any]) -> tuple[list[uuid.UUID], bool]:
    """User values: ids, user names, ``me``; ``none`` is returned as a flag."""
    from almlight.modules.identity.models import User

    ids: list[uuid.UUID] = []
    names: list[str] = []
    none = False
    for v in values:
        s = str(v).strip()
        if s.lower() == "none":
            none = True
        elif s.lower() == "me":
            if ctx.user_id:
                ids.append(ctx.user_id)
        else:
            try:
                ids.append(uuid.UUID(s))
            except ValueError:
                names.append(s.lower())
    if names:
        ids += list(ctx.db.execute(select(User.id).where(func.lower(User.username).in_(names))).scalars())
    return ids, none


def _contains(col: Any, values: list[Any]) -> ColumnElement[bool]:
    terms = [str(v) for v in values if str(v).strip()]
    if not terms:
        return true()
    escaped = [t.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") for t in terms]
    return or_(*[col.ilike(f"%{t}%") for t in escaped])


def _date_range(col: Any, values: list[Any]) -> ColumnElement[bool]:
    lo = resolve_date(values[0] if values else None)
    hi = resolve_date(values[1] if len(values) > 1 else None)
    parts = []
    if lo:
        parts.append(col >= datetime.combine(lo, datetime.min.time(), tzinfo=UTC))
    if hi:
        parts.append(col < datetime.combine(hi + timedelta(days=1), datetime.min.time(), tzinfo=UTC))
    return and_(*parts) if parts else true()


def _state_pairs(project: Project, pred) -> ColumnElement[bool]:
    """Items whose (type, state) satisfies ``pred(state_def)``."""
    clauses = []
    for t in project.model.item_types:
        wf = project.model.workflow_for(t.key)
        if wf is None:
            continue
        states = [s.key for s in wf.states if pred(s)]
        if states:
            clauses.append(and_(Item.type_key == t.key, Item.state.in_(states)))
    return or_(*clauses) if clauses else false()


def _custom(ctx: Context, info: FieldInfo, c: Condition) -> ColumnElement[bool]:
    key = info.custom.key  # type: ignore[union-attr]
    el = Item.fields[key]
    txt = el.astext
    if c.op == "exists":
        has = and_(Item.fields.has_key(key), func.jsonb_typeof(el) != "null")
        return has if _bool(c.values or [True]) else not_(has)
    kind = info.kind
    if kind == "number":
        num = case((func.jsonb_typeof(el) == "number", txt.cast(Numeric)), else_=None)
        if c.op == "between":
            lo = _number(c.values[0] if c.values else None)
            hi = _number(c.values[1] if len(c.values) > 1 else None)
            parts = [num.is_not(None)]
            if lo is not None:
                parts.append(num >= lo)
            if hi is not None:
                parts.append(num <= hi)
            return and_(*parts)
        nums = [_number(v) for v in c.values]
        return num.in_([n for n in nums if n is not None])
    if kind == "date":
        if c.op == "between":
            lo = resolve_date(c.values[0] if c.values else None)
            hi = resolve_date(c.values[1] if len(c.values) > 1 else None)
            parts = [txt.is_not(None)]
            if lo:
                parts.append(txt >= lo.isoformat())
            if hi:
                parts.append(txt <= hi.isoformat() + "T99")  # a date or a timestamp on that day
            return and_(*parts)
        return func.substr(txt, 1, 10).in_([resolve_date(v).isoformat() for v in c.values if resolve_date(v)])
    if kind == "bool":
        return Item.fields.contains({key: _bool(c.values)})
    if kind == "multi":
        vals = [str(v) for v in c.values]
        return el.op("?|")(cast(vals, ARRAY(String)))
    if kind == "user":
        ids, none = _user_ids(ctx, c.values)
        parts = [txt.in_([str(i) for i in ids])] if ids else []
        if none:
            parts.append(not_(Item.fields.has_key(key)))
        return or_(*parts) if parts else false()
    if c.op == "contains" or kind == "text":
        return _contains(txt, c.values)
    return txt.in_([str(v) for v in c.values])


def condition_sql(ctx: Context, c: Condition) -> ColumnElement[bool]:
    if c.op not in OPS:
        raise ValidationFailed(f"Unknown operator '{c.op}' (one of {', '.join(OPS)})")
    project = ctx.project
    info = field_info(project, c.field)
    name, vals = info.name, c.values
    if info.custom is not None:
        expr = _custom(ctx, info, c)
    elif info.kind == "link":
        _, lt, direction = name.split(".")
        own, other = (Link.source_id, Link.target_id) if direction == "out" else (Link.target_id, Link.source_id)
        linked = select(own).where(Link.type_key == lt, Link.deleted_at.is_(None))
        if c.op == "in" and vals:
            others = select(Item.id).where(Item.key.in_([str(v).upper() for v in vals]))
            linked = linked.where(other.in_(others))
            expr = Item.id.in_(linked)
        else:
            expr = Item.id.in_(linked) if _bool(vals or [True]) else Item.id.not_in(linked)
    elif name == "release":
        planned = select(Link.source_id).where(Link.type_key == project.model.semantics.planned_link,
                                               Link.deleted_at.is_(None))
        keys = [str(v).upper() for v in vals if str(v).lower() != "none"]
        if c.op == "exists":
            expr = Item.id.in_(planned) if _bool(vals or [True]) else Item.id.not_in(planned)
        else:
            parts = []
            if keys:
                rel = select(Item.id).where(Item.project_id == project.id, Item.key.in_(keys))
                parts.append(Item.id.in_(planned.where(Link.target_id.in_(rel))))
            if any(str(v).lower() == "none" for v in vals):
                parts.append(Item.id.not_in(planned))
            expr = or_(*parts) if parts else false()
    elif name == "type":
        expr = Item.type_key.in_([str(v) for v in vals])
    elif name == "state":
        expr = Item.state.in_([str(v) for v in vals])
    elif name == "category":
        cats = {str(v) for v in vals}
        expr = _state_pairs(project, lambda s: s.category in cats)
    elif name in ("owner", "author"):
        col = Item.owner_id if name == "owner" else Item.created_by
        if c.op == "exists":
            expr = col.is_not(None) if _bool(vals or [True]) else col.is_(None)
        else:
            ids, none = _user_ids(ctx, vals)
            parts = [col.in_(ids)] if ids else []
            if none:
                parts.append(col.is_(None))
            expr = or_(*parts) if parts else false()
    elif name in ("created", "updated"):
        expr = _date_range(Item.created_at if name == "created" else Item.updated_at, vals)
    elif name == "key":
        expr = Item.key.in_([str(v).upper() for v in vals])
    elif name == "title":
        expr = _contains(Item.title, vals)
    elif name == "text":
        terms = " ".join(str(v) for v in vals if str(v).strip())
        expr = or_(Item.search.op("@@")(func.websearch_to_tsquery("simple", terms)), _contains(Item.description, vals),
                   _contains(Item.title, vals)) if terms else true()
    elif name == "revision":
        expr = Item.revision.in_([str(v).upper() for v in vals])
    elif name == "applicability":
        if c.op == "exists":
            has = and_(Item.applicability.is_not(None), Item.applicability != "")
            expr = has if _bool(vals or [True]) else not_(has)
        else:
            expr = _contains(func.coalesce(Item.applicability, ""), vals)
    elif name == "released":
        expr = Item.released_version_id.is_not(None) if _bool(vals) else Item.released_version_id.is_(None)
    elif name == "frozen":
        frozen = _state_pairs(project, lambda s: s.frozen)
        expr = frozen if _bool(vals) else not_(frozen)
    elif name == "suspect":
        sus = Item.id.in_(select(Link.source_id).where(Link.suspect.is_(True), Link.deleted_at.is_(None)))
        expr = sus if _bool(vals) else not_(sus)
    elif name == "watched":
        from almlight.modules.notifications.models import Subscription

        w = Item.id.in_(select(Subscription.item_id).where(Subscription.user_id == ctx.user_id))
        expr = w if _bool(vals) else not_(w)
    elif name == "checkedout":
        from almlight.modules.files.models import FileCheckout

        co = Item.id.in_(select(FileCheckout.item_id))
        expr = co if _bool(vals) else not_(co)
    elif name == "attachments":
        has = func.jsonb_array_length(Item.attachments) > 0
        expr = has if _bool(vals) else not_(has)
    else:  # pragma: no cover — guarded by field_info
        raise ValidationFailed(f"Unknown query field '{name}'")
    expr = func.coalesce(expr, False)
    return not_(expr) if c.negate else expr


def apply_conditions(stmt: Any, ctx: Context, conditions: list[Condition]) -> Any:
    if len(conditions) > MAX_CONDITIONS:
        raise ValidationFailed(f"At most {MAX_CONDITIONS} conditions")
    for c in conditions:
        stmt = stmt.where(condition_sql(ctx, c))
    return stmt


def parse_conditions(raw: Any) -> list[Condition]:
    """Conditions from JSON (API parameter ``cond``, saved queries)."""
    import json

    if raw in (None, "", []):
        return []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            raise ValidationFailed("cond must be a JSON list of conditions") from None
    if not isinstance(raw, list):
        raise ValidationFailed("cond must be a JSON list of conditions")
    try:
        return [Condition.model_validate(x) for x in raw]
    except Exception as exc:  # noqa: BLE001 — pydantic message is precise enough
        raise ValidationFailed(f"Invalid condition: {exc}") from None


def sort_expressions(project: Project, sort: str) -> list[Any] | None:
    """Ordering by a custom field (``field.<key>`` / ``-field.<key>``), numbers numerically."""
    desc = sort.startswith("-")
    name = sort.lstrip("-")
    if not name.startswith("field."):
        return None
    f = custom_fields(project).get(name[6:])
    if f is None:
        raise ValidationFailed(f"Unknown sort field '{name}'")
    el = Item.fields[f.key]
    expr: Any = case((func.jsonb_typeof(el) == "number", el.astext.cast(Numeric)), else_=None) \
        if f.type in ("integer", "number") else el.astext
    expr = expr.desc().nulls_last() if desc else expr.asc().nulls_last()
    return [expr, Item.type_key, Item.seq]


# --- query language -------------------------------------------------------------------------------------------

_TOKEN = re.compile(r'\s*(?:(?P<q>"(?:[^"\\]|\\.)*")|(?P<p>[()\[\]:])|(?P<w>[^\s()\[\]:"]+))')


def _tokens(text: str) -> list[tuple[str, str, int]]:
    out, pos = [], 0
    while pos < len(text):
        if text[pos:].strip() == "":
            break
        m = _TOKEN.match(text, pos)
        if not m:
            raise ValidationFailed(f"Cannot read the query at position {pos + 1}", {"position": pos})
        kind = "q" if m.group("q") else "p" if m.group("p") else "w"
        val = m.group(kind)
        if kind == "q":
            val = re.sub(r"\\(.)", r"\1", val[1:-1])
        out.append((kind, val, m.start(kind)))
        pos = m.end()
    return out


def _field_name(project: Project, word: str) -> str:
    if word.startswith(("field.", "link.")) or word in BUILTIN:
        return word
    if word in custom_fields(project):
        return f"field.{word}"
    raise ValidationFailed(f"Unknown query field '{word}'", {"field": word})


def parse_query(project: Project, text: str) -> tuple[str | None, list[Condition]]:
    """Query language → (free text, conditions)."""
    toks = _tokens(text or "")
    i, words, conds = 0, [], []

    def peek(k: int = 0) -> tuple[str, str, int] | None:
        return toks[i + k] if i + k < len(toks) else None

    def expect(val: str) -> None:
        nonlocal i
        t = peek()
        if t is None or t[1] != val:
            where = f"position {t[2] + 1}" if t else "the end"
            raise ValidationFailed(f"Expected '{val}' at {where}")
        i += 1

    def value() -> str:
        nonlocal i
        t = peek()
        if t is None or (t[0] == "p"):
            raise ValidationFailed(f"Expected a value at {'position ' + str(t[2] + 1) if t else 'the end'}")
        i += 1
        return t[1]

    while i < len(toks):
        kind, val, pos = toks[i]
        if kind == "w" and val == "AND":
            i += 1
            continue
        if kind == "w" and val == "OR":
            raise ValidationFailed(f"OR combines values inside parentheses, e.g. state:(draft OR in_review) "
                                   f"(position {pos + 1})")
        negate = False
        if kind == "w" and val == "NOT":
            negate, i = True, i + 1
            if peek() is None:
                raise ValidationFailed("NOT needs a clause after it")
            kind, val, pos = toks[i]
        elif kind == "w" and val.startswith("-") and len(val) > 1 and peek(1) and peek(1)[1] == ":":
            negate, val = True, val[1:]
        nxt = peek(1)
        if kind == "w" and nxt and nxt[1] == ":":
            name = _field_name(project, val)
            info = field_info(project, name)
            i += 2
            t = peek()
            if t is None:
                raise ValidationFailed(f"'{val}:' needs a value")
            if t[1] == "(":
                i += 1
                vals = [value()]
                while peek() and peek()[1] == "OR":
                    i += 1
                    vals.append(value())
                expect(")")
                op = "contains" if info.kind == "text" else "in"
                conds.append(Condition(field=name, op=op, values=vals, negate=negate))
            elif t[1] == "[":
                i += 1
                lo = value()
                if not (peek() and peek()[1] == "TO"):
                    raise ValidationFailed("A range is written [from TO to]")
                i += 1
                hi = value()
                expect("]")
                conds.append(Condition(field=name, op="between", values=[None if lo == "*" else lo,
                                                                          None if hi == "*" else hi], negate=negate))
            else:
                v = value()
                if v == "*":
                    conds.append(Condition(field=name, op="exists", values=[True], negate=negate))
                elif info.kind in ("bool",):
                    conds.append(Condition(field=name, op="is", values=[v], negate=negate))
                elif info.kind == "link" and v.lower() in ("true", "false"):
                    conds.append(Condition(field=name, op="exists", values=[v.lower() == "true"], negate=negate))
                elif info.kind == "number" or info.kind == "date":
                    conds.append(Condition(field=name, op="between", values=[v, v], negate=negate))
                else:
                    conds.append(Condition(field=name, op="contains" if info.kind == "text" else "in",
                                           values=[v], negate=negate))
            continue
        if negate:
            raise ValidationFailed("NOT applies to field clauses, e.g. NOT priority:must")
        words.append(f'"{val}"' if kind == "q" else val)
        i += 1
    return (" ".join(words) or None), conds


_PLAIN = re.compile(r"^[^\s()\[\]:\"]+$")


def _fmt_value(v: Any) -> str:
    if v is None:
        return "*"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    s = str(v)
    return s if _PLAIN.match(s) and s not in ("AND", "OR", "NOT", "TO") else '"' + s.replace('"', '\\"') + '"'


def format_query(project: Project, q: str | None, conditions: list[Condition]) -> str:
    """(free text, conditions) → query language."""
    parts = []
    custom = custom_fields(project)
    for c in conditions:
        name = c.field
        if name.startswith("field.") and name[6:] in custom and name[6:] not in BUILTIN:
            name = name[6:]
        neg = "NOT " if c.negate else ""
        if c.op == "exists":
            truthy = _bool(c.values or [True])
            if not truthy:
                neg = "" if c.negate else "NOT "
            parts.append(f"{neg}{name}:*")
        elif c.op == "between":
            lo = c.values[0] if c.values else None
            hi = c.values[1] if len(c.values) > 1 else None
            if lo is not None and lo == hi:
                parts.append(f"{neg}{name}:{_fmt_value(lo)}")
            else:
                parts.append(f"{neg}{name}:[{_fmt_value(lo)} TO {_fmt_value(hi)}]")
        elif c.op == "is":
            parts.append(f"{neg}{name}:{_fmt_value(_bool(c.values))}")
        else:
            vals = [_fmt_value(v) for v in c.values]
            if not vals:
                continue
            parts.append(f"{neg}{name}:{vals[0]}" if len(vals) == 1 else f"{neg}{name}:({' OR '.join(vals)})")
    if q:
        parts.append(q)
    return " ".join(parts)
