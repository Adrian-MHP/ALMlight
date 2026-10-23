"""Workflow engine: transitions, guards, effects, approvals and electronic signatures.

Workflows are configured per item type in the project's information model. A transition
may require a minimum project role, a comment, a direct e-signature (password
re-entry) or an approval by N users of a given role (four-eyes principle by default).
Guards block a transition until a condition holds; effects run after it, e.g. a released
change order releases all items revised under it (closed-loop change, CMII style).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from almlight.core.db import utcnow
from almlight.core.errors import Conflict, Forbidden, NotFound, ValidationFailed
from almlight.core.security import verify_password
from almlight.modules.audit import service as audit
from almlight.modules.identity.models import User
from almlight.modules.integrations.outbox import emit
from almlight.modules.items.lifecycle import state_def
from almlight.modules.items.models import Item, ItemVersion
from almlight.modules.links import service as links
from almlight.modules.links.models import Link
from almlight.modules.projects.access import has_role, project_role
from almlight.modules.projects.metamodel import ROLE_RANK, TransitionDef, WorkflowDef
from almlight.modules.projects.models import Project
from almlight.modules.verification.models import TestRecord
from almlight.modules.workflow.models import ApprovalRequest, ApprovalVote, WorkflowEvent


@dataclass
class TransitionOption:
    transition: TransitionDef
    to_label: str
    allowed: bool
    blocked_by: list[str] = field(default_factory=list)
    pending_request: ApprovalRequest | None = None


def _workflow(project: Project, item: Item) -> WorkflowDef:
    wf = project.model.workflow_for(item.type_key)
    if wf is None:
        raise Conflict(f"Items of type '{item.type_key}' have no workflow")
    return wf


def pending_request(db: Session, item: Item) -> ApprovalRequest | None:
    return db.execute(
        select(ApprovalRequest).where(ApprovalRequest.item_id == item.id, ApprovalRequest.status == "pending")
    ).scalar_one_or_none()


# --- guards -------------------------------------------------------------------------------


def _affected(db: Session, project: Project, item: Item) -> list[tuple[Link, Item]]:
    rows = db.execute(
        select(Link, Item)
        .join(Item, Item.id == Link.target_id)
        .where(Link.source_id == item.id, Link.type_key == project.model.semantics.affects_link,
               Link.deleted_at.is_(None),
               Item.deleted_at.is_(None))
    ).all()
    return [(link, it) for link, it in rows]


def _guard_failures(db: Session, project: Project, item: Item, guard: str) -> list[str]:
    if guard == "has_affected_items":
        return [] if _affected(db, project, item) else ["List at least one affected item"]
    if guard == "affected_items_revised":
        problems = []
        for link, it in _affected(db, project, item):
            action = link.attributes.get("action", "revise")
            if action == "revise":
                if _head_change_order(db, it) != item.id:
                    problems.append(f"{it.key} has not been revised under {item.key}")
            elif action == "add" and it.released_version_id is not None:
                problems.append(f"{it.key} is marked 'add' but was already released")
        return problems
    if guard == "contained_items_released":
        structural = project.model.structural_link_types()
        ids = links.descendant_ids(db, item.id, structural)
        problems = []
        for child in db.execute(select(Item).where(Item.id.in_(ids))).scalars():
            s = state_def(project, child)
            if s is not None and not (s.released or s.category == "obsolete"):
                problems.append(f"{child.key} is '{s.label}'")
        return problems
    if guard == "all_records_executed":
        results = db.execute(select(TestRecord.result).where(TestRecord.run_id == item.id)).scalars().all()
        if not results:
            return ["The test run has no test cases"]
        open_count = sum(1 for r in results if r == "not_run")
        return [f"{open_count} test case(s) not executed yet"] if open_count else []
    return [f"Unknown guard '{guard}'"]


def _checkout_blockers(db: Session, project: Project, item: Item, t: TransitionDef) -> list[str]:
    """Checked-out files keep an item (and the items a change order releases) from being frozen."""
    target = _workflow(project, item).state(t.to)
    items = [item] if target and target.frozen else []
    if "release_affected_items" in t.effects:
        items += [it for _, it in _affected(db, project, item)]
    if not items:
        return []
    from almlight.modules.files.service import release_blockers

    return release_blockers(db, items)


def _head_change_order(db: Session, it: Item) -> uuid.UUID | None:
    return db.execute(select(ItemVersion.change_order_id).where(ItemVersion.id == it.head_version_id)).scalar()


# --- options ------------------------------------------------------------------------------


def available_transitions(db: Session, project: Project, item: Item, user: User) -> list[TransitionOption]:
    wf = project.model.workflow_for(item.type_key)
    if wf is None:
        return []
    req = pending_request(db, item)
    role = project_role(db, project, user)
    options = []
    for t in wf.transitions:
        if item.state not in t.from_:
            continue
        blocked: list[str] = []
        allowed = role is not None and ROLE_RANK[role] >= ROLE_RANK[t.min_role]
        if not allowed:
            blocked.append(f"Needs role '{t.min_role}'")
        for g in t.guards:
            blocked += _guard_failures(db, project, item, g)
        blocked += _checkout_blockers(db, project, item, t)
        target = wf.state(t.to)
        options.append(
            TransitionOption(
                transition=t,
                to_label=target.label if target else t.to,
                allowed=allowed and not blocked,
                blocked_by=blocked,
                pending_request=req if req and req.transition_key == t.key else None,
            )
        )
    return options


# --- execution ----------------------------------------------------------------------------


def _check_signature(user: User, password: str | None) -> None:
    if not password or not verify_password(user.password_hash, password):
        raise Forbidden("Electronic signature failed: password incorrect", {"signature": "invalid"})


def execute_transition(
    db: Session,
    project: Project,
    actor: User,
    item: Item,
    transition_key: str,
    *,
    comment: str | None = None,
    password: str | None = None,
) -> dict[str, Any]:
    """Run a transition. Returns ``{"status": "done"}`` or ``{"status": "approval_requested", ...}``."""
    wf = _workflow(project, item)
    t = wf.transition(transition_key)
    if t is None:
        raise NotFound(f"Transition '{transition_key}' does not exist")
    if item.state not in t.from_:
        raise Conflict(f"Transition '{t.label}' is not possible from state '{item.state}'")
    if not has_role(db, project, actor, t.min_role):
        raise Forbidden(f"Transition '{t.label}' needs the '{t.min_role}' role")
    if t.comment_required and not (comment or "").strip():
        raise ValidationFailed(f"Transition '{t.label}' requires a comment")
    failures = [f for g in t.guards for f in _guard_failures(db, project, item, g)]
    failures += _checkout_blockers(db, project, item, t)
    if failures:
        raise Conflict(f"'{t.label}' is blocked", {"blocked_by": failures})

    if t.approval:
        existing = pending_request(db, item)
        if existing:
            if existing.transition_key == t.key:
                raise Conflict("An approval for this transition is already pending", {"request_id": str(existing.id)})
            _cancel(db, project, actor, existing, f"superseded by '{t.label}'")
        req = ApprovalRequest(
            project_id=project.id,
            item_id=item.id,
            transition_key=t.key,
            from_state=item.state,
            to_state=t.to,
            version_no=item.version_no,
            required_count=t.approval.count,
            roles=list(t.approval.roles),
            signature_required=t.approval.signature,
            allow_self_approval=t.approval.allow_self_approval,
            reject_to=t.approval.reject_to,
            comment=comment,
            requested_by=actor.id,
        )
        db.add(req)
        db.flush()
        audit.record(db, actor=actor, action="approval.requested", entity_type="approval", entity_id=req.id,
                     project_id=project.id,
                     summary=f"Requested approval '{t.label}' for {item.key} {item.version_label}",
                     details={"transition": t.key, "roles": req.roles, "count": req.required_count,
                              "comment": comment},
                     related_ids=[item.id])
        emit(db, "approval.requested", project.id, {"project": project.key, "item": item.key,
                                                    "transition": t.key, "request_id": req.id})
        return {"status": "approval_requested", "request_id": str(req.id)}

    if t.signature:
        _check_signature(actor, password)
    existing = pending_request(db, item)
    if existing:
        _cancel(db, project, actor, existing, f"superseded by '{t.label}'")
    _apply(db, project, actor, item, t, via="transition", comment=comment, signed=t.signature)
    return {"status": "done", "state": item.state}


def _apply(
    db: Session,
    project: Project,
    actor: User | None,
    item: Item,
    t: TransitionDef,
    *,
    via: str,
    comment: str | None,
    signed: bool,
    request: ApprovalRequest | None = None,
) -> None:
    wf = _workflow(project, item)
    old = item.state
    item.state = t.to
    target = wf.state(t.to)
    if target and target.released:
        item.released_version_id = item.head_version_id
    item.updated_at = utcnow()
    db.add(WorkflowEvent(item_id=item.id, transition_key=t.key, from_state=old, to_state=t.to, via=via,
                         actor_id=actor.id if actor else None, comment=comment, version_no=item.version_no,
                         approval_request_id=request.id if request else None, signed=signed))
    db.flush()
    db.info.setdefault("access_changed", set()).add(item.id)  # live editing sessions re-check write access
    audit.record(db, actor=actor, action="item.transitioned", entity_type="item", entity_id=item.id,
                 project_id=project.id,
                 summary=f"{item.key} {item.version_label}: {old} -> {t.to} ({t.label})",
                 details={"transition": t.key, "from": old, "to": t.to, "via": via, "comment": comment,
                          "signed": signed},
                 related_ids=[item.id])
    emit(db, "item.transitioned", project.id, {"project": project.key, "item": item.key, "from": old,
                                               "to": t.to, "transition": t.key, "version": item.version_label})
    for effect in t.effects:
        if effect == "release_affected_items":
            _release_affected(db, project, actor, item)


def _release_affected(db: Session, project: Project, actor: User | None, change_order: Item) -> None:
    for link, it in _affected(db, project, change_order):
        action = link.attributes.get("action", "revise")
        wf = project.model.workflow_for(it.type_key)
        if wf is None:
            continue
        if action in ("revise", "add"):
            target = wf.released_state
        elif action == "obsolete":
            target = next((s for s in wf.states if s.category == "obsolete"), None)
        else:
            continue
        if target is None or it.state == target.key:
            continue
        req = pending_request(db, it)
        if req:
            _cancel(db, project, actor, req, f"released via {change_order.key}")
        old = it.state
        it.state = target.key
        if target.released:
            it.released_version_id = it.head_version_id
        db.add(WorkflowEvent(item_id=it.id, transition_key=None, from_state=old, to_state=target.key,
                             via="change_order", actor_id=actor.id if actor else None,
                             comment=f"Released via {change_order.key}", version_no=it.version_no,
                             change_order_id=change_order.id))
        audit.record(db, actor=actor, action="item.transitioned", entity_type="item", entity_id=it.id,
                     project_id=project.id,
                     summary=f"{it.key} {it.version_label}: {old} -> {target.key} via {change_order.key}",
                     details={"from": old, "to": target.key, "via": "change_order",
                              "change_order": change_order.key},
                     related_ids=[it.id, change_order.id])
        emit(db, "item.transitioned", project.id, {"project": project.key, "item": it.key, "from": old,
                                                   "to": target.key, "via": change_order.key})


def _cancel(db: Session, project: Project, actor: User | None, req: ApprovalRequest, reason: str) -> None:
    req.status = "cancelled"
    req.resolved_at = utcnow()
    audit.record(db, actor=actor, action="approval.cancelled", entity_type="approval", entity_id=req.id,
                 project_id=project.id, summary=f"Approval '{req.transition_key}' cancelled: {reason}",
                 related_ids=[req.item_id])


def cancel_request(db: Session, project: Project, actor: User, req: ApprovalRequest) -> None:
    if req.status != "pending":
        raise Conflict("The approval request is no longer pending")
    if req.requested_by != actor.id and not has_role(db, project, actor, "manager"):
        raise Forbidden("Only the requester or a project manager can cancel")
    _cancel(db, project, actor, req, "withdrawn")


def can_vote(db: Session, project: Project, user: User, req: ApprovalRequest) -> tuple[bool, str | None]:
    if req.status != "pending":
        return False, "not pending"
    role = project_role(db, project, user)
    min_rank = min(ROLE_RANK[r] for r in req.roles) if req.roles else ROLE_RANK["reviewer"]
    if role is None or ROLE_RANK[role] < min_rank:
        return False, f"needs role {req.roles}"
    if not req.allow_self_approval and req.requested_by == user.id:
        return False, "four-eyes principle: requester cannot approve"
    voted = db.execute(
        select(ApprovalVote.id).where(ApprovalVote.request_id == req.id, ApprovalVote.user_id == user.id)
    ).scalar()
    if voted:
        return False, "already voted"
    return True, None


def vote(
    db: Session,
    project: Project,
    actor: User,
    req: ApprovalRequest,
    *,
    decision: str,
    comment: str | None = None,
    password: str | None = None,
) -> dict[str, Any]:
    if decision not in ("approve", "reject"):
        raise ValidationFailed("decision must be 'approve' or 'reject'")
    ok, reason = can_vote(db, project, actor, req)
    if not ok:
        raise Forbidden(f"You cannot vote on this request ({reason})")
    item = db.get(Item, req.item_id)
    assert item is not None
    if item.version_no != req.version_no or item.state != req.from_state:
        _cancel(db, project, actor, req, "item changed since the request")
        raise Conflict("The item changed since approval was requested; request a new approval")
    if decision == "reject" and not (comment or "").strip():
        raise ValidationFailed("A rejection needs a comment")
    if req.signature_required:
        _check_signature(actor, password)
    wf = _workflow(project, item)
    t = wf.transition(req.transition_key)
    assert t is not None
    meaning = f"{'Approved' if decision == 'approve' else 'Rejected'}: {t.label} of {item.key} {item.version_label}"
    db.add(ApprovalVote(request_id=req.id, user_id=actor.id, decision=decision, comment=comment,
                        signed=req.signature_required, meaning=meaning,
                        details={"version": item.version_label}))
    db.flush()
    audit.record(db, actor=actor, action=f"approval.{decision}d", entity_type="approval", entity_id=req.id,
                 project_id=project.id, summary=meaning,
                 details={"comment": comment, "signed": req.signature_required}, related_ids=[item.id])
    if decision == "reject":
        req.status = "rejected"
        req.resolved_at = utcnow()
        if req.reject_to and req.reject_to != item.state:
            back = TransitionDef.model_validate(
                {"key": f"{t.key}_rejected", "label": f"{t.label} rejected", "from": [item.state],
                 "to": req.reject_to}
            )
            _apply(db, project, actor, item, back, via="approval", comment=comment, signed=req.signature_required,
                   request=req)
        return {"status": "rejected", "state": item.state}
    approvals = db.execute(
        select(ApprovalVote).where(ApprovalVote.request_id == req.id, ApprovalVote.decision == "approve")
    ).scalars().all()
    if len(approvals) >= req.required_count:
        failures = [f for g in t.guards for f in _guard_failures(db, project, item, g)]
        failures += _checkout_blockers(db, project, item, t)
        if failures:
            raise Conflict(f"'{t.label}' is blocked", {"blocked_by": failures})
        req.status = "approved"
        req.resolved_at = utcnow()
        _apply(db, project, actor, item, t, via="approval", comment=comment, signed=req.signature_required,
               request=req)
        return {"status": "approved", "state": item.state}
    return {"status": "pending", "approvals": len(approvals), "required": req.required_count}
