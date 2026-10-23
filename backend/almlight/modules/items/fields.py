"""Validation and normalisation of custom field values against the configured field definitions."""

from __future__ import annotations

import re
import uuid
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from almlight.core.errors import ValidationFailed
from almlight.modules.identity.models import User
from almlight.modules.projects.metamodel import FieldDef, eval_formula

MAX_STRING = 2000
MAX_TEXT = 200_000
MAX_STEPS = 300


def _coerce(db: Session, f: FieldDef, value: Any) -> Any:
    t = f.type
    if t in ("string", "url"):
        if not isinstance(value, str):
            raise ValueError("must be a string")
        value = value.strip()
        if len(value) > MAX_STRING:
            raise ValueError(f"must be at most {MAX_STRING} characters")
        if t == "url" and value and not re.match(r"^https?://", value):
            raise ValueError("must start with http:// or https://")
        if f.pattern and value and not re.fullmatch(f.pattern, value):
            raise ValueError(f"must match {f.pattern}")
        return value
    if t == "text":
        if not isinstance(value, str):
            raise ValueError("must be a string")
        if len(value) > MAX_TEXT:
            raise ValueError("is too long")
        return value
    if t == "integer":
        if isinstance(value, bool):
            raise ValueError("must be an integer")
        if isinstance(value, str) and re.fullmatch(r"-?\d+", value.strip()):
            return _bounded(f, int(value))
        if isinstance(value, int) or (isinstance(value, float) and value.is_integer()):
            return _bounded(f, int(value))
        raise ValueError("must be an integer")
    if t == "number":
        if isinstance(value, bool):
            raise ValueError("must be a number")
        try:
            return _bounded(f, float(value))
        except (TypeError, ValueError):
            raise ValueError("must be a number") from None
    if t == "steps":
        if not isinstance(value, list):
            raise ValueError("must be a list of steps")
        if len(value) > MAX_STEPS:
            raise ValueError(f"may have at most {MAX_STEPS} steps")
        steps = []
        for s in value:
            if isinstance(s, str):
                s = {"step": s, "expected": ""}
            if not isinstance(s, dict):
                raise ValueError("steps must be objects with 'step' and 'expected'")
            step, expected = str(s.get("step") or "").strip(), str(s.get("expected") or "").strip()
            if len(step) > 5000 or len(expected) > 5000:
                raise ValueError("a step text is too long")
            if step or expected:
                steps.append({"step": step, "expected": expected})
        return steps
    if t == "boolean":
        if isinstance(value, bool):
            return value
        if isinstance(value, str) and value.lower() in ("true", "false", "yes", "no", "1", "0"):
            return value.lower() in ("true", "yes", "1")
        raise ValueError("must be true or false")
    if t == "date":
        try:
            return date.fromisoformat(str(value)[:10]).isoformat()
        except ValueError:
            raise ValueError("must be a date (YYYY-MM-DD)") from None
    if t == "enum":
        if value not in f.option_keys():
            raise ValueError(f"must be one of {sorted(f.option_keys())}")
        return value
    if t == "multienum":
        values = value if isinstance(value, list) else [value]
        bad = [v for v in values if v not in f.option_keys()]
        if bad:
            raise ValueError(f"contains unknown options {bad}")
        return list(dict.fromkeys(values))
    if t == "tags":
        if isinstance(value, str):
            value = [v for v in re.split(r"[,\s]+", value) if v]
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            raise ValueError("must be a list of strings")
        return list(dict.fromkeys(v.strip() for v in value if v.strip()))
    if t == "user":
        try:
            uid = uuid.UUID(str(value))
        except ValueError:
            raise ValueError("must be a user id") from None
        if not db.execute(select(User.id).where(User.id == uid, User.is_active.is_(True))).scalar():
            raise ValueError("unknown or inactive user")
        return str(uid)
    raise ValueError(f"unsupported field type {t}")


def _bounded(f: FieldDef, value: float) -> float:
    if f.min is not None and value < f.min:
        raise ValueError(f"must be at least {f.min:g}")
    if f.max is not None and value > f.max:
        raise ValueError(f"must be at most {f.max:g}")
    return value


def apply_computed(defs: list[FieldDef], values: dict[str, Any]) -> dict[str, Any]:
    """Recompute formula and classification fields (in definition order) from the other values."""
    out = dict(values)
    for f in defs:
        if f.formula:
            v = eval_formula(f.formula, out)
            if v is None:
                out.pop(f.key, None)
            else:
                out[f.key] = int(round(v)) if f.type == "integer" else round(float(v), 6)
        elif f.classify:
            base = out.get(f.classify.field)
            if isinstance(base, (int, float)) and not isinstance(base, bool):
                level = None
                for threshold, option in sorted(f.classify.bands):
                    if base >= threshold:
                        level = option
                if level is None:
                    out.pop(f.key, None)
                else:
                    out[f.key] = level
            else:
                out.pop(f.key, None)
    return out


def _is_empty(value: Any) -> bool:
    return value is None or value == "" or value == []


def normalize_fields(
    db: Session,
    defs: list[FieldDef],
    values: dict[str, Any] | None,
    *,
    base: dict[str, Any] | None = None,
    apply_defaults: bool = False,
    what: str = "field",
) -> dict[str, Any]:
    """Merge ``values`` onto ``base`` (``None`` removes a value), validate and return the result."""
    by_key = {f.key: f for f in defs}
    result = dict(base or {})
    errors: dict[str, str] = {}
    for key, value in (values or {}).items():
        f = by_key.get(key)
        if f is None:
            errors[key] = f"unknown {what}"
            continue
        if f.computed:
            continue  # computed from other fields; input is ignored
        if _is_empty(value):
            result.pop(key, None)
            continue
        try:
            result[key] = _coerce(db, f, value)
        except ValueError as exc:
            errors[key] = f"{f.label} {exc}"
    if apply_defaults:
        for f in defs:
            if f.key not in result and f.default is not None:
                result[f.key] = f.default
    for f in defs:
        if f.required and _is_empty(result.get(f.key)) and f.key not in errors:
            errors[f.key] = f"{f.label} is required"
    # Drop values of fields that no longer exist in the configuration.
    result = {k: v for k, v in result.items() if k in by_key}
    if any(f.computed for f in defs):
        result = apply_computed(defs, result)
    if errors:
        raise ValidationFailed(f"Invalid {what} values", {"fields": errors})
    return result
