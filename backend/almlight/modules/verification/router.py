from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, File, Form, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from almlight.core.db import get_db
from almlight.core.deps import current_user
from almlight.core.errors import ValidationFailed
from almlight.core.schemas import UserDirectory
from almlight.modules.identity.models import User
from almlight.modules.items import service as items_svc
from almlight.modules.projects.access import get_project
from almlight.modules.verification import service

router = APIRouter(prefix="/projects/{project_key}", tags=["verification"])
MAX_JUNIT = 20 * 1024 * 1024


class AddCasesIn(BaseModel):
    test_cases: list[str] = Field(description="Test case keys")


class StepResultIn(BaseModel):
    result: str = "not_run"
    actual: str | None = None
    comment: str | None = None


class ResultIn(BaseModel):
    result: str | None = Field(default=None, description="Omit (or 'auto') to derive it from the step results")
    comment: str | None = None
    duration_ms: int | None = None
    defect: str | None = Field(default=None, description="Key of a problem report")
    step_results: list[StepResultIn] | None = None


class DefectIn(BaseModel):
    title: str | None = None
    description: str | None = None
    step: int | None = Field(default=None, description="1-based number of the failed step")


def _records(db: Session, project, run) -> list[dict[str, Any]]:
    users = UserDirectory(db)
    defect_keys = {}
    rows = service.records_of(db, run)
    ids = [r.defect_id for r, _ in rows if r.defect_id]
    if ids:
        from sqlalchemy import select

        from almlight.modules.items.models import Item

        defect_keys = dict(db.execute(select(Item.id, Item.key).where(Item.id.in_(ids))).all())
    return [{"id": str(r.id), "test_case": tc.key, "title": tc.title, "result": r.result, "comment": r.comment,
             "tested_version": f"{r.test_case_revision}", "tested_version_no": r.test_case_version_no,
             "current_version": tc.version_label, "outdated": r.test_case_version_no < tc.version_no,
             "duration_ms": r.duration_ms, "executed_by": users.ref(r.executed_by),
             "executed_at": r.executed_at.isoformat() if r.executed_at else None,
             "steps": service.steps_of(db, project, r, tc), "step_results": r.step_results or [],
             "defect": defect_keys.get(r.defect_id)}
            for r, tc in rows]


@router.get("/test-runs/{run_key}/records")
def list_records(project_key: str, run_key: str, user: User = Depends(current_user),
                 db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    project = get_project(db, project_key, user)
    return _records(db, project, items_svc.get_item(db, project, run_key))


@router.post("/test-runs/{run_key}/records")
def add_records(project_key: str, run_key: str, body: AddCasesIn, user: User = Depends(current_user),
                db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    project = get_project(db, project_key, user, "contributor")
    run = items_svc.get_item(db, project, run_key)
    cases = [items_svc.get_item(db, project, k) for k in body.test_cases]
    service.add_test_cases(db, project, user, run, cases)
    db.commit()
    return _records(db, project, run)


@router.patch("/test-runs/{run_key}/records/{record_id}")
def set_result(project_key: str, run_key: str, record_id: uuid.UUID, body: ResultIn,
               user: User = Depends(current_user), db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    project = get_project(db, project_key, user, "contributor")
    run = items_svc.get_item(db, project, run_key)
    defect = items_svc.get_item(db, project, body.defect) if body.defect else None
    service.set_result(db, project, user, run, record_id, result=body.result, comment=body.comment,
                       duration_ms=body.duration_ms, defect=defect,
                       step_results=[s.model_dump() for s in body.step_results] if body.step_results is not None
                       else None)
    db.commit()
    return _records(db, project, run)


@router.post("/test-runs/{run_key}/records/{record_id}/defect", status_code=201,
             summary="Create a problem report for a failed test and link it")
def raise_defect(project_key: str, run_key: str, record_id: uuid.UUID, body: DefectIn,
                 user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    project = get_project(db, project_key, user, "contributor")
    run = items_svc.get_item(db, project, run_key)
    defect = service.raise_defect(db, project, user, run, record_id, title=body.title, description=body.description,
                                  step=body.step)
    db.commit()
    return {"defect": defect.key, "records": _records(db, project, run)}


@router.post("/test-runs/import-junit", summary="Create a test run from CI results (JUnit XML)")
def import_junit(project_key: str, file: UploadFile = File(...), title: str | None = Form(default=None),
                 environment: str | None = Form(default=None), build: str | None = Form(default=None),
                 variant: str | None = Form(default=None), user: User = Depends(current_user),
                 db: Session = Depends(get_db)) -> dict[str, Any]:
    project = get_project(db, project_key, user, "contributor")
    content = file.file.read(MAX_JUNIT + 1)
    if len(content) > MAX_JUNIT:
        raise ValidationFailed("JUnit file too large")
    result = service.import_junit(db, project, user, content, title=title, environment=environment, build=build,
                                  variant=variant)
    db.commit()
    return {"run": result["run"].key, "state": result["run"].state, "matched": result["matched"],
            "unmatched": result["unmatched"], "summary": result["summary"]}


@router.get("/items/{item_key}/verification")
def item_verification(project_key: str, item_key: str, variant: str | None = None,
                      user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    project = get_project(db, project_key, user)
    item = items_svc.get_item(db, project, item_key)
    return service.verification_status(db, project, [item], variant)[item.id]


@router.get("/coverage")
def coverage(project_key: str, type: str, variant: str | None = None, user: User = Depends(current_user),
             db: Session = Depends(get_db)) -> dict[str, Any]:
    project = get_project(db, project_key, user)
    items_svc.item_type(project, type)
    return service.coverage(db, project, type, variant)


@router.get("/maturity", summary="Maturity per system element: specified / realised / verified / validated")
def maturity(project_key: str, type: str | None = None, variant: str | None = None,
             user: User = Depends(current_user), db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    project = get_project(db, project_key, user)
    return service.maturity(db, project, type, variant)
