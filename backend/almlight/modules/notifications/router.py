from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from almlight.core.db import get_db, utcnow
from almlight.core.deps import current_user
from almlight.core.schemas import Ok
from almlight.modules.identity.models import User
from almlight.modules.items import service as items_svc
from almlight.modules.items.models import Item
from almlight.modules.notifications import service
from almlight.modules.notifications.models import Notification, Subscription
from almlight.modules.projects.access import get_project
from almlight.modules.projects.models import Project

router = APIRouter(tags=["notifications"])


class ReadIn(BaseModel):
    ids: list[uuid.UUID] = []
    all: bool = False


class PreferencesIn(BaseModel):
    email_notifications: bool


def _out(n: Notification, keys: dict[uuid.UUID, str]) -> dict[str, Any]:
    return {"id": str(n.id), "kind": n.kind, "title": n.title, "body": n.body, "item_key": n.item_key,
            "project": keys.get(n.project_id) if n.project_id else None, "actor": n.actor_name,
            "created_at": n.created_at.isoformat(), "read": n.read_at is not None}


@router.get("/notifications", summary="My notifications (newest first)")
def list_notifications(unread_only: bool = False, limit: int = 50, user: User = Depends(current_user),
                       db: Session = Depends(get_db)) -> dict[str, Any]:
    stmt = select(Notification).where(Notification.user_id == user.id)
    if unread_only:
        stmt = stmt.where(Notification.read_at.is_(None))
    rows = db.execute(stmt.order_by(Notification.created_at.desc()).limit(min(limit, 200))).scalars().all()
    unread = db.execute(select(func.count()).select_from(Notification).where(
        Notification.user_id == user.id, Notification.read_at.is_(None))).scalar_one()
    pids = {n.project_id for n in rows if n.project_id}
    keys = dict(db.execute(select(Project.id, Project.key).where(Project.id.in_(pids))).all()) if pids else {}
    return {"unread": unread, "items": [_out(n, keys) for n in rows], "email": service.email_enabled(),
            "email_notifications": user.email_notifications}


@router.post("/notifications/read", response_model=Ok)
def mark_read(body: ReadIn, user: User = Depends(current_user), db: Session = Depends(get_db)) -> Ok:
    stmt = update(Notification).where(Notification.user_id == user.id, Notification.read_at.is_(None))
    if not body.all:
        stmt = stmt.where(Notification.id.in_(body.ids))
    db.execute(stmt.values(read_at=utcnow()))
    db.commit()
    return Ok()


@router.put("/notifications/preferences", response_model=Ok)
def preferences(body: PreferencesIn, user: User = Depends(current_user), db: Session = Depends(get_db)) -> Ok:
    db.get(User, user.id).email_notifications = body.email_notifications
    db.commit()
    return Ok()


@router.get("/subscriptions", summary="Items and documents I watch")
def my_subscriptions(user: User = Depends(current_user), db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    rows = db.execute(select(Subscription, Item, Project).join(Item, Item.id == Subscription.item_id)
                      .join(Project, Project.id == Subscription.project_id)
                      .where(Subscription.user_id == user.id, Item.deleted_at.is_(None))
                      .order_by(Subscription.created_at.desc())).all()
    return [{"project": p.key, "key": i.key, "title": i.title, "type_key": i.type_key,
             "since": s.created_at.isoformat()} for s, i, p in rows]


@router.get("/projects/{project_key}/items/{item_key}/watch")
def watch_status(project_key: str, item_key: str, user: User = Depends(current_user),
                 db: Session = Depends(get_db)) -> dict[str, Any]:
    project = get_project(db, project_key, user)
    item = items_svc.get_item(db, project, item_key)
    watchers = db.execute(select(func.count()).select_from(Subscription).where(Subscription.item_id == item.id)
                          ).scalar_one()
    mine = db.execute(select(Subscription.id).where(Subscription.item_id == item.id,
                                                    Subscription.user_id == user.id)).scalar() is not None
    return {"watching": mine, "watchers": watchers}


@router.put("/projects/{project_key}/items/{item_key}/watch")
def start_watching(project_key: str, item_key: str, user: User = Depends(current_user),
                   db: Session = Depends(get_db)) -> dict[str, Any]:
    project = get_project(db, project_key, user)
    service.watch(db, user, project, items_svc.get_item(db, project, item_key), True)
    db.commit()
    return watch_status(project_key, item_key, user, db)


@router.delete("/projects/{project_key}/items/{item_key}/watch")
def stop_watching(project_key: str, item_key: str, user: User = Depends(current_user),
                  db: Session = Depends(get_db)) -> dict[str, Any]:
    project = get_project(db, project_key, user)
    service.watch(db, user, project, items_svc.get_item(db, project, item_key), False)
    db.commit()
    return watch_status(project_key, item_key, user, db)
