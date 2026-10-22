from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from almlight.core.db import get_db
from almlight.core.deps import current_user
from almlight.core.errors import NotFound
from almlight.core.schemas import Ok, UserDirectory
from almlight.modules.identity.models import User
from almlight.modules.items import service as items_svc
from almlight.modules.items.models import Item
from almlight.modules.projects.access import get_project, project_role
from almlight.modules.projects.models import Project, ProjectMember
from almlight.modules.workflow import engine
from almlight.modules.workflow.models import ApprovalRequest, ApprovalVote

router = APIRouter(tags=["workflow"])


class TransitionIn(BaseModel):
    comment: str | None = None
    password: str | None = None


class VoteIn(BaseModel):
    decision: str
    comment: str | None = None
    password: str | None = None


def _request_out(db: Session, project: Project, req: ApprovalRequest, item: Item, user: User,
                 users: UserDirectory) -> dict[str, Any]:
    votes = db.execute(select(ApprovalVote).where(ApprovalVote.request_id == req.id)
                       .order_by(ApprovalVote.created_at)).scalars().all()
    wf = project.model.workflow_for(item.type_key)
    t = wf.transition(req.transition_key) if wf else None
    ok, reason = engine.can_vote(db, project, user, req)
    return {
        "id": str(req.id), "project_key": project.key, "item_key": item.key, "item_title": item.title,
        "item_type": item.type_key, "transition": req.transition_key, "label": t.label if t else req.transition_key,
        "from_state": req.from_state, "to_state": req.to_state, "version_no": req.version_no,
        "status": req.status, "required": req.required_count, "roles": req.roles,
        "signature_required": req.signature_required, "comment": req.comment,
        "requested_by": users.ref(req.requested_by), "created_at": req.created_at.isoformat(),
        "resolved_at": req.resolved_at.isoformat() if req.resolved_at else None,
        "votes": [{"user": users.ref(v.user_id), "decision": v.decision, "comment": v.comment, "signed": v.signed,
                   "meaning": v.meaning, "at": v.created_at.isoformat()} for v in votes],
        "can_vote": ok, "cannot_vote_reason": reason,
    }


@router.get("/projects/{project_key}/items/{item_key}/transitions")
def transitions(project_key: str, item_key: str, user: User = Depends(current_user),
                db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    project = get_project(db, project_key, user)
    item = items_svc.get_item(db, project, item_key)
    out = []
    for opt in engine.available_transitions(db, project, item, user):
        t = opt.transition
        out.append({
            "key": t.key, "label": t.label, "to": t.to, "to_label": opt.to_label, "min_role": t.min_role,
            "allowed": opt.allowed, "blocked_by": opt.blocked_by, "comment_required": t.comment_required,
            "signature": t.signature,
            "approval": t.approval.model_dump() if t.approval else None,
            "pending_request_id": str(opt.pending_request.id) if opt.pending_request else None,
        })
    return out


@router.post("/projects/{project_key}/items/{item_key}/transitions/{transition_key}")
def run_transition(project_key: str, item_key: str, transition_key: str, body: TransitionIn,
                   user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    project = get_project(db, project_key, user, "viewer")
    item = items_svc.get_item(db, project, item_key)
    result = engine.execute_transition(db, project, user, item, transition_key, comment=body.comment,
                                       password=body.password)
    db.commit()
    return result


@router.get("/projects/{project_key}/items/{item_key}/approvals")
def item_approvals(project_key: str, item_key: str, user: User = Depends(current_user),
                   db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    project = get_project(db, project_key, user)
    item = items_svc.get_item(db, project, item_key)
    reqs = db.execute(select(ApprovalRequest).where(ApprovalRequest.item_id == item.id)
                      .order_by(ApprovalRequest.created_at.desc())).scalars().all()
    users = UserDirectory(db)
    return [_request_out(db, project, r, item, user, users) for r in reqs]


@router.get("/approvals", summary="Approval inbox across projects")
def inbox(status: str = "pending", mine: bool = True, user: User = Depends(current_user),
          db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    stmt = select(ApprovalRequest, Item, Project).join(Item, Item.id == ApprovalRequest.item_id) \
        .join(Project, Project.id == ApprovalRequest.project_id).where(ApprovalRequest.status == status)
    if not user.is_admin:
        stmt = stmt.join(ProjectMember, (ProjectMember.project_id == Project.id)
                         & (ProjectMember.user_id == user.id))
    users = UserDirectory(db)
    out = []
    for req, item, project in db.execute(stmt.order_by(ApprovalRequest.created_at.desc()).limit(200)).all():
        if project_role(db, project, user) is None:
            continue
        entry = _request_out(db, project, req, item, user, users)
        if mine and status == "pending" and not entry["can_vote"] and req.requested_by != user.id:
            continue
        out.append(entry)
    return out


def _get_request(db: Session, project: Project, request_id: uuid.UUID) -> ApprovalRequest:
    req = db.get(ApprovalRequest, request_id)
    if req is None or req.project_id != project.id:
        raise NotFound("Approval request not found")
    return req


@router.post("/projects/{project_key}/approvals/{request_id}/vote")
def vote(project_key: str, request_id: uuid.UUID, body: VoteIn, user: User = Depends(current_user),
         db: Session = Depends(get_db)) -> dict[str, Any]:
    project = get_project(db, project_key, user)
    req = _get_request(db, project, request_id)
    result = engine.vote(db, project, user, req, decision=body.decision, comment=body.comment,
                         password=body.password)
    db.commit()
    return result


@router.post("/projects/{project_key}/approvals/{request_id}/cancel", response_model=Ok)
def cancel(project_key: str, request_id: uuid.UUID, user: User = Depends(current_user),
           db: Session = Depends(get_db)) -> Ok:
    project = get_project(db, project_key, user, "contributor")
    engine.cancel_request(db, project, user, _get_request(db, project, request_id))
    db.commit()
    return Ok()
