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

from pydantic import BaseModel, ConfigDict, Field, model_validator
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


class Group(BaseModel):
    """Conditions combined with OR (``{"or": [...]}``) or AND (``{"and": [...]}``), optionally negated."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    any_of: list[Node] | None = Field(default=None, alias="or", max_length=MAX_CONDITIONS)
    all_of: list[Node] | None = Field(default=None, alias="and", max_length=MAX_CONDITIONS)
    negate: bool = Field(default=False, alias="not")

    @model_validator(mode="after")
    def _one_kind(self) -> Group:
        if (self.any_of is None) == (self.all_of is None):
            raise ValueError("a group has either 'or' or 'and'")
        if not (self.any_of or self.all_of):
            raise ValueError("a group needs conditions")
        return self

    @property
    def kind(self) -> str:
        return "or" if self.any_of is not None else "and"

    @property
    def children(self) -> list[Node]:
        return self.any_of if self.any_of is not None else (self.all_of or [])

    def dump(self) -> dict[str, Any]:
        out: dict[str, Any] = {self.kind: [c.dump() for c in self.children]}
        if self.negate:
            out["not"] = True
        return out


Node = Condition | Group
Group.model_rebuild()


def leaves(nodes: list[Node]) -> list[Condition]:
    """Every field condition in a (nested) query — for validation."""
    out: list[Condition] = []
    for n in nodes:
        out.extend(leaves(n.children) if isinstance(n, Group) else [n])
    return out


def node_sql(ctx: Context, n: Node, depth: int = 0) -> ColumnElement[bool]:
    if isinstance(n, Condition):
        return condition_sql(ctx, n)
    if depth > 8:
        raise ValidationFailed("Queries can be nested at most 8 levels deep")
    parts = [node_sql(ctx, c, depth + 1) for c in n.children]
    expr = or_(*parts) if n.kind == "or" else and_(*parts)
    return not_(expr) if n.negate else expr


def apply_conditions(stmt: Any, ctx: Context, conditions: list[Node]) -> Any:
    if len(leaves(conditions)) > MAX_CONDITIONS:
        raise ValidationFailed(f"At most {MAX_CONDITIONS} conditions")
    for c in conditions:
        stmt = stmt.where(node_sql(ctx, c))
    return stmt


def _node(raw: Any) -> Node:
    if isinstance(raw, dict) and ("or" in raw or "and" in raw):
        return Group.model_validate(raw)
    return Condition.model_validate(raw)


def parse_conditions(raw: Any) -> list[Node]:
    """Conditions from JSON (API parameter ``cond``, saved queries, boards): conditions and or/and groups."""
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
        return [_node(x) for x in raw]
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


_KEYWORDS = ("AND", "OR", "NOT", "TO")


class _Parser:
    """Recursive descent: or-expression := and-expression (OR and-expression)*;
    and-expression := unary ([AND] unary)*; unary := NOT unary | -clause | ( or-expression ) | clause | word."""

    def __init__(self, project: Project, text: str) -> None:
        self.project = project
        self.toks = _tokens(text or "")
        self.i = 0
        self.top_words: list[str] = []

    def peek(self, k: int = 0) -> tuple[str, str, int] | None:
        return self.toks[self.i + k] if self.i + k < len(self.toks) else None

    def where(self) -> str:
        t = self.peek()
        return f"position {t[2] + 1}" if t else "the end"

    def expect(self, val: str) -> None:
        t = self.peek()
        if t is None or t[1] != val:
            raise ValidationFailed(f"Expected '{val}' at {self.where()}")
        self.i += 1

    def is_word(self, val: str) -> bool:
        t = self.peek()
        return bool(t and t[0] == "w" and t[1] == val)

    def value(self) -> str:
        t = self.peek()
        if t is None or t[0] == "p" or (t[0] == "w" and t[1] in ("AND", "OR", "NOT")):
            raise ValidationFailed(f"Expected a value at {self.where()}")
        self.i += 1
        return t[1]

    def parse(self) -> tuple[str | None, list[Node]]:
        node = self.or_expr(top=True)
        if self.peek() is not None:
            raise ValidationFailed(f"Unexpected '{self.peek()[1]}' at {self.where()}")
        if node is None:
            nodes: list[Node] = []
        elif isinstance(node, Group) and node.kind == "and" and not node.negate:
            nodes = list(node.children)
        else:
            nodes = [node]
        return (" ".join(self.top_words) or None), nodes

    def or_expr(self, top: bool = False) -> Node | None:
        parts = [self.and_expr(top)]
        while self.is_word("OR"):
            self.i += 1
            parts.append(self.and_expr(False))
        if len(parts) > 1:
            # free words inside an OR branch are text conditions, not the global search
            if any(p is None for p in parts):
                raise ValidationFailed(f"OR needs a condition on both sides (near {self.where()})")
            return Group(any_of=parts)
        return parts[0]

    def and_expr(self, top: bool) -> Node | None:
        parts: list[Node] = []
        start_words = len(self.top_words)
        while True:
            t = self.peek()
            if t is None or (t[0] == "p" and t[1] == ")") or self.is_word("OR"):
                break
            if self.is_word("AND"):
                self.i += 1
                continue
            n = self.unary(top)
            if n is not None:
                parts.append(n)
        if self.is_word("OR") and top and len(self.top_words) > start_words:
            # "pressure OR drift": the words become text conditions of this branch
            words = self.top_words[start_words:]
            del self.top_words[start_words:]
            parts.append(Condition(field="text", op="contains", values=words))
        if not parts:
            return None
        return parts[0] if len(parts) == 1 else Group(all_of=parts)

    def unary(self, top: bool) -> Node | None:
        t = self.peek()
        kind, val, _pos = t
        if kind == "w" and val == "NOT":
            self.i += 1
            if self.peek() is None:
                raise ValidationFailed("NOT needs a clause after it")
            n = self.unary(False)
            if n is None:
                raise ValidationFailed("NOT applies to conditions, e.g. NOT priority:must")
            n.negate = not n.negate
            return n
        if kind == "p" and val == "(":
            self.i += 1
            n = self.or_expr(False)
            self.expect(")")
            if n is None:
                raise ValidationFailed("Empty parentheses")
            return n
        if kind == "p":
            raise ValidationFailed(f"Unexpected '{val}' at {self.where()}")
        if kind == "w" and val.startswith("-") and len(val) > 1 and self.peek(1) and self.peek(1)[1] == ":":
            self.toks[self.i] = ("w", val[1:], t[2])
            n = self.clause()
            n.negate = not n.negate
            return n
        nxt = self.peek(1)
        if kind == "w" and nxt and nxt[1] == ":":
            return self.clause()
        self.i += 1
        word = f'"{val}"' if kind == "q" else val
        if top:
            self.top_words.append(word)
            return None
        return Condition(field="text", op="contains", values=[val])

    def clause(self) -> Condition:
        _kind, val, _pos = self.peek()
        name = _field_name(self.project, val)
        info = field_info(self.project, name)
        self.i += 2
        t = self.peek()
        if t is None:
            raise ValidationFailed(f"'{val}:' needs a value")
        if t[1] == "(":
            self.i += 1
            vals = [self.value()]
            while self.is_word("OR"):
                self.i += 1
                vals.append(self.value())
            self.expect(")")
            return Condition(field=name, op="contains" if info.kind == "text" else "in", values=vals)
        if t[1] == "[":
            self.i += 1
            lo = self.value()
            if not self.is_word("TO"):
                raise ValidationFailed("A range is written [from TO to]")
            self.i += 1
            hi = self.value()
            self.expect("]")
            return Condition(field=name, op="between", values=[None if lo == "*" else lo, None if hi == "*" else hi])
        v = self.value()
        if v == "*":
            return Condition(field=name, op="exists", values=[True])
        if info.kind == "bool":
            return Condition(field=name, op="is", values=[v])
        if info.kind == "link" and v.lower() in ("true", "false"):
            return Condition(field=name, op="exists", values=[v.lower() == "true"])
        if info.kind in ("number", "date"):
            return Condition(field=name, op="between", values=[v, v])
        return Condition(field=name, op="contains" if info.kind == "text" else "in", values=[v])


def parse_query(project: Project, text: str) -> tuple[str | None, list[Node]]:
    """Query language → (free text, conditions incl. or/and groups)."""
    return _Parser(project, text).parse()


_PLAIN = re.compile(r"^[^\s()\[\]:\"]+$")


def _fmt_value(v: Any) -> str:
    if v is None:
        return "*"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    s = str(v)
    return s if _PLAIN.match(s) and s not in _KEYWORDS else '"' + s.replace('"', '\\"') + '"'


def _fmt_condition(c: Condition, custom: dict[str, FieldDef]) -> str | None:
    name = c.field
    if name.startswith("field.") and name[6:] in custom and name[6:] not in BUILTIN:
        name = name[6:]
    neg = "NOT " if c.negate else ""
    if c.field == "text" and c.op == "contains" and not c.negate and len(c.values) == 1:
        return _fmt_value(c.values[0])  # a plain word
    if c.op == "exists":
        truthy = _bool(c.values or [True])
        if not truthy:
            neg = "" if c.negate else "NOT "
        return f"{neg}{name}:*"
    if c.op == "between":
        lo = c.values[0] if c.values else None
        hi = c.values[1] if len(c.values) > 1 else None
        if lo is not None and lo == hi:
            return f"{neg}{name}:{_fmt_value(lo)}"
        return f"{neg}{name}:[{_fmt_value(lo)} TO {_fmt_value(hi)}]"
    if c.op == "is":
        return f"{neg}{name}:{_fmt_value(_bool(c.values))}"
    vals = [_fmt_value(v) for v in c.values]
    if not vals:
        return None
    return f"{neg}{name}:{vals[0]}" if len(vals) == 1 else f"{neg}{name}:({' OR '.join(vals)})"


def _fmt_node(n: Node, custom: dict[str, FieldDef], nested: bool) -> str | None:
    if isinstance(n, Condition):
        return _fmt_condition(n, custom)
    parts = [x for x in (_fmt_node(c, custom, True) for c in n.children) if x]
    if not parts:
        return None
    inner = (" OR " if n.kind == "or" else " ").join(parts)
    if n.negate:
        return f"NOT ({inner})"
    return f"({inner})" if (nested or n.kind == "or") and len(parts) > 1 else inner


def format_query(project: Project, q: str | None, conditions: list[Node]) -> str:
    """(free text, conditions) → query language."""
    custom = custom_fields(project)
    parts = [x for x in (_fmt_node(c, custom, False) for c in conditions) if x]
    if q:
        parts.append(q)
    return " ".join(parts)
