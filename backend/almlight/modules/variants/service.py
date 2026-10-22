"""Feature model, variant validation and the 150% -> 100% filter.

Features and variants are ordinary items (so they are versioned, traceable and have a
lifecycle). By convention, item types of category ``variability`` with a ``code`` field are
features and those with a ``selection`` field are variants. The feature tree uses the
structural link type; ``requires`` / ``excludes`` links express cross-tree constraints.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from almlight.modules.items.lifecycle import state_def
from almlight.modules.items.models import Item
from almlight.modules.links.models import Link
from almlight.modules.projects.models import Project
from almlight.modules.variants import expressions


def _types_with_field(project: Project, field_key: str) -> list[str]:
    return [
        t.key for t in project.model.item_types
        if t.category == "variability" and t.field(field_key) is not None
    ]


@dataclass
class Feature:
    item: Item
    code: str
    kind: str
    group: str
    obsolete: bool
    parent: str | None = None
    children: list[str] = field(default_factory=list)


@dataclass
class FeatureModel:
    features: dict[str, Feature]
    requires: list[tuple[str, str]]
    excludes: list[tuple[str, str]]

    @property
    def roots(self) -> list[Feature]:
        return [f for f in self.features.values() if f.parent is None]


def load_feature_model(db: Session, project: Project) -> FeatureModel:
    types = _types_with_field(project, "code")
    items = db.execute(
        select(Item).where(Item.project_id == project.id, Item.type_key.in_(types), Item.deleted_at.is_(None))
        .order_by(Item.seq)
    ).scalars().all() if types else []
    by_id: dict[uuid.UUID, Feature] = {}
    for it in items:
        code = str(it.fields.get("code") or it.key)
        s = state_def(project, it)
        by_id[it.id] = Feature(item=it, code=code, kind=it.fields.get("feature_kind", "optional"),
                               group=it.fields.get("group", "none"), obsolete=bool(s and s.category == "obsolete"))
    requires: list[tuple[str, str]] = []
    excludes: list[tuple[str, str]] = []
    if by_id:
        structural = project.model.structural_link_types()
        rows = db.execute(
            select(Link).where(Link.source_id.in_(by_id), Link.target_id.in_(by_id), Link.deleted_at.is_(None))
            .order_by(Link.position.nulls_last())
        ).scalars().all()
        for link in rows:
            src, tgt = by_id[link.source_id], by_id[link.target_id]
            if link.type_key in structural:
                tgt.parent = src.code
                src.children.append(tgt.code)
            elif link.type_key == project.model.semantics.requires_link:
                requires.append((src.code, tgt.code))
            elif link.type_key == project.model.semantics.excludes_link:
                excludes.append((src.code, tgt.code))
    return FeatureModel(features={f.code: f for f in by_id.values()}, requires=requires, excludes=excludes)


def validate_selection(model: FeatureModel, selection: set[str]) -> list[str]:
    """Check a feature selection against the feature model. Returns human-readable violations."""
    errors: list[str] = []
    feats = model.features
    for code in sorted(selection - feats.keys()):
        errors.append(f"Unknown feature '{code}'")
    chosen = selection & feats.keys()
    for code in sorted(chosen):
        f = feats[code]
        if f.obsolete:
            errors.append(f"Feature '{code}' is obsolete")
        if f.parent and f.parent not in chosen:
            errors.append(f"'{code}' needs its parent feature '{f.parent}'")
    for f in model.roots:
        if f.kind == "mandatory" and f.code not in chosen and not f.obsolete:
            errors.append(f"Mandatory feature '{f.code}' is missing")
    for code in sorted(chosen):
        f = feats[code]
        kids = [feats[c] for c in f.children if not feats[c].obsolete]
        picked = [k for k in kids if k.code in chosen]
        for k in kids:
            if k.kind == "mandatory" and k.code not in chosen:
                errors.append(f"'{code}' requires its mandatory sub-feature '{k.code}'")
        if f.group == "alternative" and kids and len(picked) != 1:
            errors.append(f"Choose exactly one of {[k.code for k in kids]} under '{code}' "
                          f"(selected: {[k.code for k in picked]})")
        if f.group == "or" and kids and not picked:
            errors.append(f"Choose at least one of {[k.code for k in kids]} under '{code}'")
    for a, b in model.requires:
        if a in chosen and b not in chosen:
            errors.append(f"'{a}' requires '{b}'")
    for a, b in model.excludes:
        if a in chosen and b in chosen:
            errors.append(f"'{a}' excludes '{b}'")
    return errors


def selection_of(variant: Item) -> set[str]:
    return set(variant.fields.get("selection") or [])


def resolve(db: Session, project: Project, selection: set[str]) -> dict[str, Any]:
    """Apply a selection to the 150% model: which items and links are part of this configuration."""
    feature_types = set(_types_with_field(project, "code")) | set(_types_with_field(project, "selection"))
    items = db.execute(
        select(Item).where(Item.project_id == project.id, Item.deleted_at.is_(None))
    ).scalars().all()
    included, excluded, invalid = [], [], []
    for it in items:
        if it.type_key in feature_types:
            continue
        try:
            (included if expressions.applies(it.applicability, selection) else excluded).append(it)
        except Exception:  # noqa: BLE001 — a broken expression must not break the whole view
            invalid.append(it)
    excluded_links = []
    for link in db.execute(
        select(Link).where(Link.project_id == project.id, Link.deleted_at.is_(None),
                           Link.applicability.is_not(None))
    ).scalars():
        try:
            if not expressions.applies(link.applicability, selection):
                excluded_links.append(link.id)
        except Exception:  # noqa: BLE001
            excluded_links.append(link.id)
    return {"included": included, "excluded": excluded, "invalid": invalid, "excluded_link_ids": excluded_links}


def unknown_codes(db: Session, project: Project) -> list[dict[str, Any]]:
    """Items whose applicability references feature codes that do not exist."""
    known = set(load_feature_model(db, project).features)
    out = []
    for it in db.execute(
        select(Item).where(Item.project_id == project.id, Item.deleted_at.is_(None), Item.applicability.is_not(None))
    ).scalars():
        try:
            missing = expressions.identifiers(expressions.parse(it.applicability or "")) - known
        except Exception:  # noqa: BLE001
            missing = {"<syntax error>"}
        if missing:
            out.append({"key": it.key, "missing": sorted(missing)})
    return out
