from __future__ import annotations

import base64
import uuid
from typing import Any

from fastapi import APIRouter, Depends, Header, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from almlight.core.db import get_db
from almlight.core.deps import current_user
from almlight.core.errors import NotFound
from almlight.core.schemas import Ok
from almlight.modules.audit import service as audit
from almlight.modules.identity.models import User
from almlight.modules.integrations import service
from almlight.modules.integrations.models import ExternalRef, IntegrationSetting, Webhook, WebhookDelivery
from almlight.modules.items import service as items_svc
from almlight.modules.projects.access import get_project
from almlight.modules.projects.models import Project

router = APIRouter(tags=["integrations"])
MAX_HOOK_BODY = 5 * 1024 * 1024


class RefIn(BaseModel):
    system: str = "url"
    kind: str = "link"
    url: str | None = None
    title: str | None = None
    external_id: str | None = None


class InboundIn(BaseModel):
    enabled: bool = True
    rotate_secret: bool = False


class WebhookIn(BaseModel):
    url: str
    events: list[str] = Field(default_factory=lambda: ["*"])


@router.get("/projects/{project_key}/items/{item_key}/external-refs")
def list_refs(project_key: str, item_key: str, user: User = Depends(current_user),
              db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    project = get_project(db, project_key, user)
    item = items_svc.get_item(db, project, item_key)
    refs = db.execute(select(ExternalRef).where(ExternalRef.item_id == item.id)
                      .order_by(ExternalRef.updated_at.desc())).scalars().all()
    return [{"id": str(r.id), "system": r.system, "kind": r.kind, "external_id": r.external_id, "url": r.url,
             "title": r.title, "status": r.status, "data": r.data, "updated_at": r.updated_at.isoformat()}
            for r in refs]


@router.post("/projects/{project_key}/items/{item_key}/external-refs", response_model=Ok, status_code=201)
def add_ref(project_key: str, item_key: str, body: RefIn, user: User = Depends(current_user),
            db: Session = Depends(get_db)) -> Ok:
    project = get_project(db, project_key, user, "contributor")
    item = items_svc.get_item(db, project, item_key)
    service.add_manual_ref(db, project, user, item, system=body.system, kind=body.kind, url=body.url,
                           title=body.title, external_id=body.external_id)
    db.commit()
    return Ok()


@router.delete("/projects/{project_key}/items/{item_key}/external-refs/{ref_id}", response_model=Ok)
def delete_ref(project_key: str, item_key: str, ref_id: uuid.UUID, user: User = Depends(current_user),
               db: Session = Depends(get_db)) -> Ok:
    project = get_project(db, project_key, user, "contributor")
    service.delete_ref(db, project, user, items_svc.get_item(db, project, item_key), ref_id)
    db.commit()
    return Ok()


@router.get("/projects/{project_key}/integrations")
def list_integrations(project_key: str, request: Request, user: User = Depends(current_user),
                      db: Session = Depends(get_db)) -> dict[str, Any]:
    project = get_project(db, project_key, user, "manager")
    settings = db.execute(select(IntegrationSetting).where(IntegrationSetting.project_id == project.id)).scalars()
    hooks = db.execute(select(Webhook).where(Webhook.project_id == project.id)).scalars().all()
    base = str(request.base_url).rstrip("/")
    return {
        "inbound": [{"system": s.system, "enabled": s.enabled,
                     "endpoint": f"{base}/api/v1/hooks/{s.system.replace('_', '-')}/{project.key}"}
                    for s in settings],
        "webhooks": [{"id": str(h.id), "url": h.url, "events": h.events, "active": h.active} for h in hooks],
        "events": list(service.EVENTS),
    }


@router.put("/projects/{project_key}/integrations/{system}")
def configure_inbound(project_key: str, system: str, body: InboundIn, request: Request,
                      user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    project = get_project(db, project_key, user, "manager")
    setting, secret = service.configure_inbound(db, project, user, system, enabled=body.enabled,
                                                rotate_secret=body.rotate_secret)
    db.commit()
    base = str(request.base_url).rstrip("/")
    return {"system": setting.system, "enabled": setting.enabled,
            "endpoint": f"{base}/api/v1/hooks/{setting.system.replace('_', '-')}/{project.key}",
            "secret": secret, "secret_note": "Shown once. Configure it as the webhook secret in the other tool."
            if secret else None}


@router.post("/projects/{project_key}/webhooks", status_code=201)
def create_webhook(project_key: str, body: WebhookIn, user: User = Depends(current_user),
                   db: Session = Depends(get_db)) -> dict[str, Any]:
    project = get_project(db, project_key, user, "manager")
    hook, secret = service.create_webhook(db, project, user, body.url, body.events)
    db.commit()
    return {"id": str(hook.id), "url": hook.url, "events": hook.events, "secret": secret,
            "secret_note": "Shown once. Verify X-ALMlight-Signature (HMAC-SHA256) with it."}


@router.delete("/projects/{project_key}/webhooks/{hook_id}", response_model=Ok)
def delete_webhook(project_key: str, hook_id: uuid.UUID, user: User = Depends(current_user),
                   db: Session = Depends(get_db)) -> Ok:
    project = get_project(db, project_key, user, "manager")
    hook = db.get(Webhook, hook_id)
    if hook is None or hook.project_id != project.id:
        raise NotFound("Webhook not found")
    db.delete(hook)
    audit.record(db, actor=user, action="webhook.deleted", entity_type="project", entity_id=project.id,
                 project_id=project.id, summary=f"Removed webhook to {hook.url}")
    db.commit()
    return Ok()


@router.get("/projects/{project_key}/webhooks/{hook_id}/deliveries")
def deliveries(project_key: str, hook_id: uuid.UUID, user: User = Depends(current_user),
               db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    project = get_project(db, project_key, user, "manager")
    hook = db.get(Webhook, hook_id)
    if hook is None or hook.project_id != project.id:
        raise NotFound("Webhook not found")
    rows = db.execute(select(WebhookDelivery).where(WebhookDelivery.webhook_id == hook.id)
                      .order_by(WebhookDelivery.created_at.desc()).limit(100)).scalars()
    return [{"event": d.event, "status_code": d.status_code, "error": d.error, "duration_ms": d.duration_ms,
             "at": d.created_at.isoformat()} for d in rows]


# --- inbound endpoints (authenticated by shared secret, not by user session) ---------------------


def _project_by_key(db: Session, key: str) -> Project:
    project = db.execute(select(Project).where(Project.key == key.upper())).scalar_one_or_none()
    if project is None:
        raise NotFound("Integration not configured")
    return project


async def _body(request: Request) -> bytes:
    body = await request.body()
    if len(body) > MAX_HOOK_BODY:
        raise NotFound("Payload too large")
    return body


@router.post("/hooks/github/{project_key}", tags=["inbound hooks"])
async def github_hook(project_key: str, request: Request, db: Session = Depends(get_db),
                      x_github_event: str = Header(default=""),
                      x_hub_signature_256: str | None = Header(default=None)) -> dict[str, Any]:
    body = await _body(request)

    def work() -> dict[str, Any]:
        result = service.handle_github(db, _project_by_key(db, project_key), x_github_event, body,
                                       x_hub_signature_256)
        db.commit()
        return result

    return await run_in_threadpool(work)


@router.post("/hooks/azure-devops/{project_key}", tags=["inbound hooks"])
async def azure_devops_hook(project_key: str, request: Request, db: Session = Depends(get_db),
                            authorization: str | None = Header(default=None),
                            x_almlight_token: str | None = Header(default=None)) -> dict[str, Any]:
    body = await _body(request)
    token = x_almlight_token
    if token is None and authorization and authorization.lower().startswith("basic "):
        try:
            token = base64.b64decode(authorization[6:]).decode().split(":", 1)[1]
        except Exception:  # noqa: BLE001
            token = None

    def work() -> dict[str, Any]:
        result = service.handle_azure_devops(db, _project_by_key(db, project_key), body, token)
        db.commit()
        return result

    return await run_in_threadpool(work)
