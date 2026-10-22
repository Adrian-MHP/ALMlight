from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from almlight.core.db import get_db
from almlight.core.deps import current_user
from almlight.core.errors import ValidationFailed
from almlight.core.schemas import UserDirectory
from almlight.modules.identity.models import User
from almlight.modules.items import service as items_svc
from almlight.modules.items.models import Item
from almlight.modules.items.schemas import items_out
from almlight.modules.projects.access import get_project
from almlight.modules.variants import expressions, service

router = APIRouter(prefix="/projects/{project_key}/variants", tags=["variants"])


class SelectionIn(BaseModel):
    selection: list[str] = Field(default_factory=list)


class ExpressionIn(BaseModel):
    expression: str


@router.get("/feature-model")
def feature_model(project_key: str, user: User = Depends(current_user), db: Session = Depends(get_db)
                  ) -> dict[str, Any]:
    project = get_project(db, project_key, user)
    model = service.load_feature_model(db, project)

    def node(code: str) -> dict[str, Any]:
        f = model.features[code]
        return {"code": f.code, "key": f.item.key, "title": f.item.title, "kind": f.kind, "group": f.group,
                "obsolete": f.obsolete, "children": [node(c) for c in f.children]}

    variant_types = service._types_with_field(project, "selection")
    variants = db.execute(
        select(Item).where(Item.project_id == project.id, Item.type_key.in_(variant_types), Item.deleted_at.is_(None))
        .order_by(Item.seq)
    ).scalars().all() if variant_types else []
    return {
        "roots": [node(f.code) for f in model.roots],
        "requires": [{"from": a, "to": b} for a, b in model.requires],
        "excludes": [{"from": a, "to": b} for a, b in model.excludes],
        "variants": [{"key": v.key, "title": v.title, "selection": sorted(service.selection_of(v)),
                      "state": v.state, "errors": service.validate_selection(model, service.selection_of(v))}
                     for v in variants],
        "unknown_codes": service.unknown_codes(db, project),
    }


@router.post("/validate")
def validate(project_key: str, body: SelectionIn, user: User = Depends(current_user),
             db: Session = Depends(get_db)) -> dict[str, Any]:
    project = get_project(db, project_key, user)
    errors = service.validate_selection(service.load_feature_model(db, project), set(body.selection))
    return {"valid": not errors, "errors": errors}


@router.post("/check-expression")
def check_expression(project_key: str, body: ExpressionIn, user: User = Depends(current_user),
                     db: Session = Depends(get_db)) -> dict[str, Any]:
    project = get_project(db, project_key, user)
    try:
        node = expressions.parse(body.expression)
    except ValidationFailed as exc:
        return {"valid": False, "error": exc.message, "unknown": []}
    known = set(service.load_feature_model(db, project).features)
    return {"valid": True, "error": None, "unknown": sorted(expressions.identifiers(node) - known)}


def _resolved(db: Session, project, selection: set[str]) -> dict[str, Any]:
    model = service.load_feature_model(db, project)
    res = service.resolve(db, project, selection)
    users = UserDirectory(db)
    counts: dict[str, dict[str, int]] = {}
    for bucket in ("included", "excluded"):
        for it in res[bucket]:
            counts.setdefault(it.type_key, {"included": 0, "excluded": 0})[bucket] += 1
    return {
        "selection": sorted(selection),
        "errors": service.validate_selection(model, selection),
        "counts": counts,
        "included": [i.model_dump(mode="json") for i in items_out(project, res["included"], users)],
        "excluded": [i.model_dump(mode="json") for i in items_out(project, res["excluded"], users)],
        "invalid": [i.key for i in res["invalid"]],
        "excluded_link_ids": [str(x) for x in res["excluded_link_ids"]],
    }


@router.post("/configure", summary="Resolve an ad-hoc feature selection (150% -> 100%)")
def configure(project_key: str, body: SelectionIn, user: User = Depends(current_user),
              db: Session = Depends(get_db)) -> dict[str, Any]:
    project = get_project(db, project_key, user)
    return _resolved(db, project, set(body.selection))


@router.get("/{variant_key}/resolve")
def resolve_variant(project_key: str, variant_key: str, user: User = Depends(current_user),
                    db: Session = Depends(get_db)) -> dict[str, Any]:
    project = get_project(db, project_key, user)
    variant = items_svc.get_item(db, project, variant_key)
    out = _resolved(db, project, service.selection_of(variant))
    out["variant"] = {"key": variant.key, "title": variant.title}
    return out
