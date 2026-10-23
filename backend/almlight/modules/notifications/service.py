"""Who gets notified about what.

Every audited change is offered to ``on_audit``. Recipients:

* **watchers** of the changed item or of any document/structure that contains it,
* the **owner** of a changed item,
* **approvers** (members with a required role) when an approval is requested,
* users **@mentioned** in a comment.

The actor is never notified. Candidates are buffered for the transaction and written just before it commits
(dropped with rolled-back savepoints, e.g. dry runs); a person who would receive many notifications from one
transaction (an import, a merge) gets one summary instead. New notifications are pushed live to open browsers;
an optional e-mail digest is sent by the background worker when SMTP is configured.
"""

from __future__ import annotations

import contextlib
import logging
import re
import smtplib
import uuid
from collections import defaultdict
from datetime import timedelta
from email.message import EmailMessage
from typing import Any

from sqlalchemy import event, select, text
from sqlalchemy.orm import Session

from almlight.core import events
from almlight.core.config import get_settings
from almlight.core.db import utcnow
from almlight.modules.identity.models import User
from almlight.modules.items.models import Item
from almlight.modules.notifications.models import Notification, Subscription
from almlight.modules.projects.metamodel import ROLE_RANK
from almlight.modules.projects.models import Project, ProjectMember

log = logging.getLogger("almlight.notifications")
# @username — also e-mail-like user names from single sign-on (@alex@example.com)
MENTION = re.compile(r"(?<![\w@])@([A-Za-z0-9_.-]{2,64}(?:@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+)?)")
SUMMARY_THRESHOLD = 5
OWNER_ACTIONS = {"item.updated", "item.revised", "item.transitioned", "item.attachment_added",
                 "item.attachment_removed", "item.deleted", "item.restored", "comment.added", "testrun.result"}
WATCH_PREFIXES = ("item.", "link.", "comment.", "testrun.", "approval.", "baseline.", "document.")


def mentions(body: str) -> list[str]:
    return list(dict.fromkeys(m.lower().rstrip(".-") for m in MENTION.findall(body or "")))


def _ancestors(db: Session, project: Project, ids: set[uuid.UUID]) -> set[uuid.UUID]:
    structural = project.model.structural_link_types()
    if not ids or not structural:
        return set()
    rows = db.execute(text("""
        WITH RECURSIVE up(id, depth) AS (
            SELECT l.source_id, 1 FROM links l
            WHERE l.target_id = ANY(:ids) AND l.deleted_at IS NULL AND l.type_key = ANY(:types)
            UNION
            SELECT l.source_id, u.depth + 1 FROM links l JOIN up u ON l.target_id = u.id
            WHERE l.deleted_at IS NULL AND l.type_key = ANY(:types) AND u.depth < 25
        ) SELECT DISTINCT id FROM up"""), {"ids": list(ids), "types": structural}).scalars().all()
    return set(rows)


def _has_watchers(db: Session, project_id: uuid.UUID) -> bool:
    cache: dict = db.info.setdefault("watchers_cache", {})
    if project_id not in cache:
        cache[project_id] = db.execute(select(Subscription.id).where(Subscription.project_id == project_id)
                                       .limit(1)).scalar() is not None
    return cache[project_id]


def on_audit(db: Session, entry: Any, actor: User | None) -> None:
    project_id = entry.project_id
    if project_id is None:
        return
    action = entry.action
    details = entry.details or {}
    actor_id = actor.id if actor else None
    ids: set[uuid.UUID] = set(entry.related_ids or [])
    if entry.entity_type == "item" and entry.entity_id:
        with contextlib.suppress(ValueError):
            ids.add(uuid.UUID(entry.entity_id))
    candidates: dict[uuid.UUID, str] = {}  # user -> kind (strongest wins)
    rank = {"watch": 1, "owner": 2, "approval": 3, "mention": 4}

    def add(user_id: uuid.UUID | None, kind: str) -> None:
        if user_id is None or user_id == actor_id:
            return
        if rank[kind] > rank.get(candidates.get(user_id, ""), 0):
            candidates[user_id] = kind

    project: Project | None = None
    if action.startswith(WATCH_PREFIXES) and ids and _has_watchers(db, project_id):
        project = db.get(Project, project_id)
        scope = ids | _ancestors(db, project, ids)
        for (uid,) in db.execute(select(Subscription.user_id).where(Subscription.project_id == project_id,
                                                                    Subscription.item_id.in_(scope))).all():
            add(uid, "watch")
    if action in OWNER_ACTIONS and ids:
        for (owner,) in db.execute(select(Item.owner_id).where(Item.id.in_(ids), Item.owner_id.is_not(None))).all():
            add(owner, "owner")
    if action == "approval.requested":
        roles = details.get("roles") or []
        min_rank = min((ROLE_RANK.get(r, 99) for r in roles), default=99)
        for uid, role in db.execute(select(ProjectMember.user_id, ProjectMember.role)
                                    .where(ProjectMember.project_id == project_id)).all():
            if role in roles and ROLE_RANK.get(role, -1) >= min_rank:
                add(uid, "approval")
    if action == "comment.added" and details.get("mentions"):
        names = [n.lower() for n in details["mentions"]]
        members = {m for (m,) in db.execute(select(ProjectMember.user_id)
                                            .where(ProjectMember.project_id == project_id))}
        for uid, username, is_admin in db.execute(select(User.id, User.username, User.is_admin)
                                                  .where(User.is_active.is_(True))).all():
            if username.lower() in names and (uid in members or is_admin):
                add(uid, "mention")
    if not candidates:
        return
    # the notification opens the changed item itself, else the first related one (e.g. the commented item,
    # not the document it was commented in)
    primary = None
    if entry.entity_type == "item" and entry.entity_id:
        with contextlib.suppress(ValueError):
            primary = uuid.UUID(entry.entity_id)
    if primary is None and entry.related_ids:
        primary = entry.related_ids[0]
    key = db.execute(select(Item.key).where(Item.id == primary)).scalar() if primary else None
    buffer = db.info.setdefault("notif_buffer", [])
    for uid, kind in candidates.items():
        buffer.append({"user_id": uid, "project_id": project_id, "kind": kind, "title": entry.summary[:300],
                       "body": details.get("excerpt"), "item_key": key, "actor": entry.actor_name})


@event.listens_for(Session, "before_commit")
def _flush_notifications(session: Session) -> None:
    buffer = session.info.pop("notif_buffer", None)
    if not buffer:
        return
    by_user: dict[uuid.UUID, list[dict[str, Any]]] = defaultdict(list)
    for n in buffer:
        by_user[n["user_id"]].append(n)
    keys: dict[uuid.UUID, str] = {}
    for user_id, items in by_user.items():
        # drop exact duplicates (same title for the same person)
        seen, unique = set(), []
        for n in items:
            if (n["title"], n["kind"]) not in seen:
                seen.add((n["title"], n["kind"]))
                unique.append(n)
        important = [n for n in unique if n["kind"] in ("mention", "approval")]
        rest = [n for n in unique if n["kind"] not in ("mention", "approval")]
        rows = list(important)
        if len(rest) > SUMMARY_THRESHOLD:
            first = rest[0]
            if first["project_id"] not in keys:
                keys[first["project_id"]] = session.execute(select(Project.key).where(
                    Project.id == first["project_id"])).scalar() or ""
            actors = list(dict.fromkeys(n["actor"] for n in rest if n.get("actor")))
            who = actors[0] if len(actors) == 1 else ", ".join(actors[:3]) + (" …" if len(actors) > 3 else "")
            rows.append({**first, "kind": "digest", "actor": who,
                         "title": f"{len(rest)} changes in {keys[first['project_id']]} by {who}",
                         "body": "\n".join(n["title"] for n in rest[:20]) + ("\n…" if len(rest) > 20 else ""),
                         "item_key": None})
        else:
            rows += rest
        for n in rows:
            note = Notification(user_id=user_id, project_id=n["project_id"], kind=n["kind"], title=n["title"],
                                body=n.get("body"), item_key=n.get("item_key"), actor_name=n.get("actor"))
            session.add(note)
            session.flush()
            events.record(session, {"type": "notification", "user_id": str(user_id), "project_id": None,
                                    "id": str(note.id), "kind": note.kind, "title": note.title,
                                    "item_key": note.item_key, "actor": note.actor_name,
                                    "project": keys.get(n["project_id"]) or _project_key(session, n["project_id"])})


def _project_key(session: Session, project_id: uuid.UUID | None) -> str | None:
    if project_id is None:
        return None
    cache: dict = session.info.setdefault("project_key_cache", {})
    if project_id not in cache:
        cache[project_id] = session.execute(select(Project.key).where(Project.id == project_id)).scalar()
    return cache[project_id]


# --- watching ----------------------------------------------------------------------------------------------


def watch(db: Session, user: User, project: Project, item: Item, on: bool) -> bool:
    existing = db.execute(select(Subscription).where(Subscription.user_id == user.id,
                                                     Subscription.item_id == item.id)).scalar_one_or_none()
    if on and existing is None:
        db.add(Subscription(user_id=user.id, project_id=project.id, item_id=item.id))
    elif not on and existing is not None:
        db.delete(existing)
    db.info.pop("watchers_cache", None)
    return on


# --- e-mail digests -----------------------------------------------------------------------------------------


def email_enabled() -> bool:
    s = get_settings()
    return bool(s.smtp_host and s.smtp_from)


def send_digests(db: Session, *, min_age_seconds: float = 30.0) -> int:
    """Send one e-mail per user with their notifications not yet e-mailed (oldest first). Returns mails sent."""
    if not email_enabled():
        return 0
    s = get_settings()
    cutoff = utcnow() - timedelta(seconds=min_age_seconds)
    pending = db.execute(
        select(Notification, User).join(User, User.id == Notification.user_id)
        .where(Notification.emailed_at.is_(None), Notification.read_at.is_(None), Notification.created_at <= cutoff,
               User.email_notifications.is_(True), User.email.is_not(None), User.is_active.is_(True))
        .order_by(Notification.created_at).limit(2000).with_for_update(of=Notification, skip_locked=True)
    ).all()
    by_user: dict[uuid.UUID, tuple[User, list[Notification]]] = {}
    for note, user in pending:
        by_user.setdefault(user.id, (user, []))[1].append(note)
    sent = 0
    base = (s.public_url or "").rstrip("/")
    for user, notes in by_user.values():
        msg = EmailMessage()
        msg["Subject"] = f"[{_product()}] {len(notes)} new notification{'s' if len(notes) != 1 else ''}"
        msg["From"] = s.smtp_from
        msg["To"] = user.email
        lines = [f"Hello {user.display_name},", "", "here is what happened since the last e-mail:", ""]
        for n in notes:
            link = f"{base}/p/{_project_key(db, n.project_id)}/items/{n.item_key}" if base and n.item_key else ""
            lines.append(f"- {n.title}" + (f"\n  {link}" if link else ""))
        lines += ["", "You can switch these e-mails off on your account page."]
        msg.set_content("\n".join(lines))
        try:
            _send(msg)
        except Exception:  # noqa: BLE001 — retried next round
            log.exception("sending a notification e-mail to %s failed", user.email)
            continue
        for n in notes:
            n.emailed_at = utcnow()
        sent += 1
    db.commit()
    return sent


def _product() -> str:
    from almlight import PRODUCT

    return PRODUCT


def _send(msg: EmailMessage) -> None:
    s = get_settings()
    if s.smtp_security == "ssl":
        with smtplib.SMTP_SSL(s.smtp_host, s.smtp_port, timeout=20) as smtp:
            if s.smtp_user:
                smtp.login(s.smtp_user, s.smtp_password or "")
            smtp.send_message(msg)
        return
    with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=20) as smtp:
        if s.smtp_security == "starttls":
            smtp.starttls()
        if s.smtp_user:
            smtp.login(s.smtp_user, s.smtp_password or "")
        smtp.send_message(msg)
