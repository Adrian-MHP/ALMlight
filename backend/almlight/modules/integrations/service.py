"""Inbound integrations (Git hosting, Azure DevOps), external references and outbound webhooks.

Inbound: tools call ALMlight's webhook endpoints. Item keys mentioned in commit messages,
pull requests or work items (e.g. "Fix SYS-12 range check") create *external references*
on those items — the digital thread from requirement to code without copying data.
Outbound: domain events from the outbox are POSTed to subscribed URLs, signed with HMAC-SHA256.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import re
import secrets
import threading
import time
import uuid
from datetime import timedelta
from typing import Any

import httpx
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from almlight.core.db import session_factory, utcnow
from almlight.core.errors import NotFound, Unauthorized, ValidationFailed
from almlight.modules.audit import service as audit
from almlight.modules.identity.models import User
from almlight.modules.integrations.models import ExternalRef, IntegrationSetting, OutboxEvent, Webhook, WebhookDelivery
from almlight.modules.items.models import Item
from almlight.modules.projects.models import Project

log = logging.getLogger("almlight.integrations")
KEY_RE = re.compile(r"(?<![A-Za-z0-9])([A-Z][A-Z0-9]{0,7}-\d+)(?![0-9])")
SYSTEMS = ("github", "gitlab", "azure_devops", "git", "cad", "pdm", "ci", "url", "other")
INBOUND_SYSTEMS = ("github", "azure_devops")
EVENTS = ("item.created", "item.updated", "item.revised", "item.transitioned", "item.deleted", "link.created",
          "link.deleted", "comment.added", "approval.requested", "baseline.created")


# --- external references --------------------------------------------------------------------


def upsert_ref(db: Session, project: Project, item: Item, *, system: str, kind: str, external_id: str,
               url: str | None, title: str | None, status: str | None = None, data: dict[str, Any] | None = None,
               actor: User | None = None) -> None:
    stmt = pg_insert(ExternalRef).values(
        id=uuid.uuid4(), project_id=project.id, item_id=item.id, system=system, kind=kind,
        external_id=external_id[:255], url=url, title=(title or "")[:2000], status=status, data=data or {},
        created_by=actor.id if actor else None, created_at=utcnow(), updated_at=utcnow(),
    )
    db.execute(stmt.on_conflict_do_update(
        constraint="uq_external_refs_identity",
        set_={"url": stmt.excluded.url, "title": stmt.excluded.title, "status": stmt.excluded.status,
              "data": stmt.excluded.data, "updated_at": stmt.excluded.updated_at},
    ))


def add_manual_ref(db: Session, project: Project, actor: User, item: Item, *, system: str, kind: str,
                   url: str | None, title: str | None, external_id: str | None) -> None:
    if system not in SYSTEMS:
        raise ValidationFailed(f"system must be one of {SYSTEMS}")
    if url and not re.match(r"^https?://", url):
        raise ValidationFailed("url must start with http:// or https://")
    ext_id = external_id or url or secrets.token_hex(8)
    upsert_ref(db, project, item, system=system, kind=kind or "link", external_id=ext_id, url=url, title=title,
               actor=actor)
    audit.record(db, actor=actor, action="external_ref.added", entity_type="item", entity_id=item.id,
                 project_id=project.id, summary=f"Linked {item.key} to {system} {kind}: {title or url or ext_id}",
                 related_ids=[item.id])


def delete_ref(db: Session, project: Project, actor: User, item: Item, ref_id: uuid.UUID) -> None:
    ref = db.get(ExternalRef, ref_id)
    if ref is None or ref.item_id != item.id:
        raise NotFound("Reference not found")
    db.delete(ref)
    audit.record(db, actor=actor, action="external_ref.removed", entity_type="item", entity_id=item.id,
                 project_id=project.id, summary=f"Removed {ref.system} reference from {item.key}",
                 related_ids=[item.id])


def _items_mentioned(db: Session, project: Project, *texts: str | None) -> list[Item]:
    keys = {m for t in texts if t for m in KEY_RE.findall(t)}
    if not keys:
        return []
    return list(db.execute(
        select(Item).where(Item.project_id == project.id, Item.key.in_(keys), Item.deleted_at.is_(None))
    ).scalars())


# --- inbound settings ------------------------------------------------------------------------


def configure_inbound(db: Session, project: Project, actor: User, system: str, *, enabled: bool = True,
                      rotate_secret: bool = False) -> tuple[IntegrationSetting, str | None]:
    """Create or update an inbound integration. Returns the plaintext secret only when (re)generated."""
    if system not in INBOUND_SYSTEMS:
        raise ValidationFailed(f"system must be one of {INBOUND_SYSTEMS}")
    setting = db.execute(
        select(IntegrationSetting).where(IntegrationSetting.project_id == project.id,
                                         IntegrationSetting.system == system)
    ).scalar_one_or_none()
    new_secret = None
    if setting is None:
        new_secret = secrets.token_urlsafe(32)
        setting = IntegrationSetting(project_id=project.id, system=system, enabled=enabled, secret=new_secret)
        db.add(setting)
    else:
        setting.enabled = enabled
        if rotate_secret:
            new_secret = secrets.token_urlsafe(32)
            setting.secret = new_secret
    db.flush()
    audit.record(db, actor=actor, action="integration.configured", entity_type="project", entity_id=project.id,
                 project_id=project.id,
                 summary=f"Configured {system} integration (enabled={enabled}{', new secret' if new_secret else ''})")
    return setting, new_secret


def _setting(db: Session, project: Project, system: str) -> IntegrationSetting:
    setting = db.execute(
        select(IntegrationSetting).where(IntegrationSetting.project_id == project.id,
                                         IntegrationSetting.system == system, IntegrationSetting.enabled.is_(True))
    ).scalar_one_or_none()
    if setting is None:
        raise NotFound("Integration not configured")
    return setting


def handle_github(db: Session, project: Project, event: str, body: bytes, signature: str | None) -> dict[str, Any]:
    setting = _setting(db, project, "github")
    expected = "sha256=" + hmac.new(setting.secret.encode(), body, hashlib.sha256).hexdigest()
    if not signature or not hmac.compare_digest(expected, signature):
        raise Unauthorized("Invalid webhook signature")
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        raise ValidationFailed("Body is not JSON") from None
    linked = 0
    if event == "ping":
        return {"ok": True, "linked": 0}
    repo = (payload.get("repository") or {}).get("full_name", "")
    if event == "push":
        for c in payload.get("commits", []):
            for item in _items_mentioned(db, project, c.get("message")):
                upsert_ref(db, project, item, system="github", kind="commit", external_id=c.get("id", ""),
                           url=c.get("url"), title=(c.get("message") or "").splitlines()[0] if c.get("message") else "",
                           status="pushed", data={"repository": repo, "author": (c.get("author") or {}).get("name"),
                                                  "ref": payload.get("ref")})
                linked += 1
    elif event == "pull_request":
        pr = payload.get("pull_request") or {}
        status = "merged" if pr.get("merged") else pr.get("state")
        for item in _items_mentioned(db, project, pr.get("title"), pr.get("body"), (pr.get("head") or {}).get("ref")):
            upsert_ref(db, project, item, system="github", kind="pull_request",
                       external_id=f"{repo}#{pr.get('number')}", url=pr.get("html_url"), title=pr.get("title"),
                       status=status, data={"repository": repo, "action": payload.get("action")})
            linked += 1
    elif event in ("workflow_run", "check_run"):
        run = payload.get(event) or {}
        texts = [run.get("head_branch"), (run.get("head_commit") or {}).get("message"), run.get("display_title")]
        for item in _items_mentioned(db, project, *texts):
            upsert_ref(db, project, item, system="github", kind="build", external_id=str(run.get("id")),
                       url=run.get("html_url"), title=run.get("name"),
                       status=run.get("conclusion") or run.get("status"), data={"repository": repo})
            linked += 1
    if linked:
        audit.record(db, actor=None, actor_name="github", action="integration.inbound", entity_type="project",
                     entity_id=project.id, project_id=project.id,
                     summary=f"GitHub '{event}' linked {linked} reference(s)")
    return {"ok": True, "linked": linked}


def handle_azure_devops(db: Session, project: Project, body: bytes, token: str | None) -> dict[str, Any]:
    """Azure DevOps service hook ("Web Hooks" consumer). Authenticate with the shared secret sent as the
    basic-auth password or as the ``X-ALMlight-Token`` header."""
    setting = _setting(db, project, "azure_devops")
    if not token or not hmac.compare_digest(token, setting.secret):
        raise Unauthorized("Invalid token")
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        raise ValidationFailed("Body is not JSON") from None
    event = payload.get("eventType", "")
    res = payload.get("resource") or {}
    linked = 0
    if event == "git.push":
        repo = (res.get("repository") or {}).get("name", "")
        for c in res.get("commits", []):
            for item in _items_mentioned(db, project, c.get("comment")):
                upsert_ref(db, project, item, system="azure_devops", kind="commit", external_id=c.get("commitId", ""),
                           url=c.get("url"), title=c.get("comment"), status="pushed", data={"repository": repo})
                linked += 1
    elif event.startswith("git.pullrequest"):
        for item in _items_mentioned(db, project, res.get("title"), res.get("description"), res.get("sourceRefName")):
            upsert_ref(db, project, item, system="azure_devops", kind="pull_request",
                       external_id=str(res.get("pullRequestId")), url=(res.get("_links") or {}).get("web", {})
                       .get("href") or res.get("url"), title=res.get("title"), status=res.get("status"))
            linked += 1
    elif event.startswith("workitem."):
        fields = res.get("fields") or (res.get("revision") or {}).get("fields") or {}
        title = fields.get("System.Title") if isinstance(fields.get("System.Title"), str) else None
        wid = res.get("workItemId") or res.get("id")
        for item in _items_mentioned(db, project, title, fields.get("System.Description")
                                     if isinstance(fields.get("System.Description"), str) else None,
                                     fields.get("System.Tags") if isinstance(fields.get("System.Tags"), str) else None):
            state = fields.get("System.State")
            upsert_ref(db, project, item, system="azure_devops", kind="work_item", external_id=str(wid),
                       url=(res.get("_links") or {}).get("html", {}).get("href") or res.get("url"), title=title,
                       status=state if isinstance(state, str) else None)
            linked += 1
    if linked:
        audit.record(db, actor=None, actor_name="azure_devops", action="integration.inbound", entity_type="project",
                     entity_id=project.id, project_id=project.id,
                     summary=f"Azure DevOps '{event}' linked {linked} reference(s)")
    return {"ok": True, "linked": linked}


# --- outbound webhooks -----------------------------------------------------------------------


def create_webhook(db: Session, project: Project, actor: User, url: str, events: list[str]) -> tuple[Webhook, str]:
    if not re.match(r"^https?://", url or ""):
        raise ValidationFailed("url must start with http:// or https://")
    bad = [e for e in events if e != "*" and e not in EVENTS]
    if bad:
        raise ValidationFailed(f"Unknown events {bad}", {"known": list(EVENTS)})
    secret = secrets.token_urlsafe(32)
    hook = Webhook(project_id=project.id, url=url, secret=secret, events=events or ["*"], created_by=actor.id)
    db.add(hook)
    db.flush()
    audit.record(db, actor=actor, action="webhook.created", entity_type="project", entity_id=project.id,
                 project_id=project.id, summary=f"Added webhook to {url}", details={"events": hook.events})
    return hook, secret


def sign(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def prune(db: Session, keep_days: int = 30) -> None:
    """Delete delivered outbox events and delivery logs older than ``keep_days`` (the audit trail keeps history)."""
    cutoff = utcnow() - timedelta(days=keep_days)
    db.execute(delete(OutboxEvent).where(OutboxEvent.processed_at.is_not(None), OutboxEvent.processed_at < cutoff))
    db.execute(delete(WebhookDelivery).where(WebhookDelivery.created_at < cutoff))
    db.commit()


def deliver_pending(db: Session, client: httpx.Client, batch: int = 20) -> int:
    events = db.execute(
        select(OutboxEvent).where(OutboxEvent.processed_at.is_(None)).order_by(OutboxEvent.id)
        .limit(batch).with_for_update(skip_locked=True)
    ).scalars().all()
    for ev in events:
        hooks = db.execute(
            select(Webhook).where(Webhook.project_id == ev.project_id, Webhook.active.is_(True))
        ).scalars().all() if ev.project_id else []
        failed = False
        for hook in hooks:
            if "*" not in hook.events and ev.event not in hook.events:
                continue
            body = json.dumps({"id": ev.id, "event": ev.event, "created_at": ev.created_at.isoformat(),
                               "data": ev.payload}).encode()
            started = time.monotonic()
            status, error = None, None
            try:
                resp = client.post(hook.url, content=body, headers={
                    "Content-Type": "application/json", "X-ALMlight-Event": ev.event,
                    "X-ALMlight-Delivery": str(ev.id), "X-ALMlight-Signature": sign(hook.secret, body)})
                status = resp.status_code
                failed = failed or status >= 400
            except httpx.HTTPError as exc:
                error, failed = str(exc)[:1000], True
            db.add(WebhookDelivery(webhook_id=hook.id, outbox_id=ev.id, event=ev.event, status_code=status,
                                   error=error, duration_ms=int((time.monotonic() - started) * 1000)))
        ev.attempts += 1
        if not failed or ev.attempts >= 3:
            ev.processed_at = utcnow()
        else:
            ev.last_error = "delivery failed"
    db.commit()
    return len(events)


class OutboxWorker:
    """Background thread delivering outbox events. One per process; safe to run several (SKIP LOCKED)."""

    def __init__(self, interval: float = 2.0):
        self.interval = interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="outbox-worker", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _run(self) -> None:
        last_prune = 0.0
        with httpx.Client(timeout=10.0) as client:
            while not self._stop.is_set():
                try:
                    with session_factory()() as db:
                        n = deliver_pending(db, client)
                        if time.monotonic() - last_prune > 3600:
                            prune(db)
                            last_prune = time.monotonic()
                except Exception:  # noqa: BLE001 — never let the worker die
                    log.exception("outbox delivery failed")
                    n = 0
                if n == 0:
                    self._stop.wait(self.interval)
