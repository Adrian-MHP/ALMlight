"""The assistant's conversation loop.

A question runs the model with the project's tools until it has an answer. Reading tools run straight away;
tools that change data are previewed in a rolled-back savepoint and wait for the person's confirmation — the
model never writes on its own. Everything the assistant changes goes through the normal services, so it carries
the person's role, creates normal versions and lands in the audit trail.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from almlight.core.db import utcnow
from almlight.core.errors import DomainError, NotFound, ValidationFailed
from almlight.modules.assistant import llm, tools
from almlight.modules.assistant.models import AssistantMessage, AssistantThread
from almlight.modules.audit import service as audit
from almlight.modules.identity.models import User
from almlight.modules.projects.models import Project

log = logging.getLogger("almlight.assistant")
MAX_RESULT_CHARS = 30_000
MAX_RESULT_CHARS_LOCAL = 8_000  # local models have a much smaller context
TITLE_CHARS = 120

SYSTEM_PROMPT = """You are the assistant of Ariadne, an ALM/PLM system for engineering teams. You work inside the
project {project_key} ({project_name}) for {user_name}, whose role there is {role}.

How to work:
- Answer from the project's data, never from memory: use the tools. Call project_overview when you need to know
  which item types, fields, states or link types exist — do not guess their names.
- Item keys look like SYS-12. Never invent a key, a field value or a number; if a tool found nothing, say so.
- Keep answers short and factual. Use the item key when you mention an item. Tables help for lists.
- Answer in the language of the person's last message.
{write_rules}
Today is {today}."""

WRITE_RULES = """- You may propose changes (create_item, update_item, create_link, add_comment). They are NOT carried
  out when you call them: the person sees exactly what would change and confirms or discards it. Propose only what
  was asked for, one step at a time, and say in your answer what you proposed.
"""
READ_ONLY_RULES = """- This person may only read ({role} role), so you cannot change anything. If they ask for a
  change, say which role is needed.
"""


def _thread(db: Session, project: Project, user: User, thread_id: uuid.UUID) -> AssistantThread:
    thread = db.get(AssistantThread, thread_id)
    if thread is None or thread.project_id != project.id or thread.user_id != user.id:
        raise NotFound("Conversation not found")
    return thread


def threads(db: Session, project: Project, user: User, limit: int = 30) -> list[dict[str, Any]]:
    rows = db.execute(
        select(AssistantThread).where(AssistantThread.project_id == project.id, AssistantThread.user_id == user.id)
        .order_by(AssistantThread.updated_at.desc()).limit(limit)
    ).scalars().all()
    return [{"id": str(t.id), "title": t.title or "…", "updated_at": t.updated_at.isoformat(),
             "pending": len(t.pending), "model": t.model or None} for t in rows]


def create_thread(db: Session, project: Project, user: User, model: str | None = None) -> AssistantThread:
    chosen = llm.resolve(model)
    if model and (chosen is None or chosen.id != model):
        raise ValidationFailed(f"The language model '{model}' is not available in this installation")
    thread = AssistantThread(project_id=project.id, user_id=user.id, title="", pending=[],
                             model=chosen.id if chosen else "")
    db.add(thread)
    db.flush()
    return thread


def delete_thread(db: Session, project: Project, user: User, thread_id: uuid.UUID) -> None:
    thread = _thread(db, project, user, thread_id)
    db.execute(delete(AssistantMessage).where(AssistantMessage.thread_id == thread.id))
    db.delete(thread)


def messages(db: Session, thread: AssistantThread) -> list[AssistantMessage]:
    return list(db.execute(select(AssistantMessage).where(AssistantMessage.thread_id == thread.id)
                           .order_by(AssistantMessage.seq)).scalars())


def _add(db: Session, thread: AssistantThread, role: str, content: str,
         meta: dict[str, Any] | None = None) -> AssistantMessage:
    seq = db.execute(select(func.coalesce(func.max(AssistantMessage.seq), 0))
                     .where(AssistantMessage.thread_id == thread.id)).scalar_one() + 1
    message = AssistantMessage(thread_id=thread.id, seq=seq, role=role, content=content, meta=meta or {})
    db.add(message)
    db.flush()
    thread.updated_at = utcnow()
    return message


def message_out(m: AssistantMessage) -> dict[str, Any]:
    return {"id": str(m.id), "role": m.role, "content": m.content, "meta": m.meta,
            "created_at": m.created_at.isoformat()}


def _system(ctx: tools.Context) -> str:
    role = "manager" if ctx.user.is_admin else ("contributor" if ctx.may_write() else "viewer")
    return SYSTEM_PROMPT.format(
        project_key=ctx.project.key, project_name=ctx.project.name, user_name=ctx.user.display_name, role=role,
        write_rules=WRITE_RULES if ctx.may_write() else READ_ONLY_RULES.format(role=role),
        today=datetime.now(UTC).date().isoformat(),
    )


def _history(db: Session, thread: AssistantThread, ctx: tools.Context) -> list[dict[str, Any]]:
    """The conversation in the shape the model expects (system prompt + the last messages)."""
    from almlight.core.config import get_settings

    stored = messages(db, thread)[-get_settings().assistant_max_history:]
    # a tool answer without its assistant call would be rejected by the model
    while stored and stored[0].role == "tool":
        stored.pop(0)
    out: list[dict[str, Any]] = [{"role": "system", "content": _system(ctx)}]
    for m in stored:
        if m.role == "tool":
            out.append({"role": "tool", "tool_call_id": m.meta.get("call_id", ""), "content": m.content})
        elif m.role == "assistant" and m.meta.get("tool_calls"):
            out.append({"role": "assistant", "content": m.content or None,
                        "tool_calls": [{"id": c["id"], "type": "function",
                                        "function": {"name": c["name"], "arguments": json.dumps(c["arguments"])}}
                                       for c in m.meta["tool_calls"]]})
        else:
            out.append({"role": m.role, "content": m.content})
    return out


def _result_text(value: Any, limit: int = MAX_RESULT_CHARS) -> str:
    """A tool answer as JSON. An oversized one stays valid JSON, so the model can still read what came back."""
    text = json.dumps(value, ensure_ascii=False, default=str)
    if len(text) <= limit:
        return text
    return json.dumps({"truncated": True, "partial": text[:limit],
                       "note": "The answer was too large. Narrow it down (a filter, fewer rows, one item)."},
                      ensure_ascii=False)


def _limit(model: llm.Model | None) -> int:
    """How much of a tool answer the chosen model can take."""
    return MAX_RESULT_CHARS_LOCAL if model and model.local else MAX_RESULT_CHARS


def _run_tool(ctx: tools.Context, call: dict[str, Any], limit: int = MAX_RESULT_CHARS) -> tuple[str, bool]:
    try:
        return _result_text(tools.run(ctx, call["name"], call["arguments"]), limit), True
    except DomainError as exc:
        return _result_text({"error": exc.message}, limit), False
    except Exception as exc:  # noqa: BLE001 — the model must learn about the failure, the loop must go on
        log.exception("assistant tool %s failed", call["name"])
        return _result_text({"error": f"{type(exc).__name__}: {exc}"[:300]}, limit), False


def _answer(messages: list[dict[str, Any]], schemas: list[dict[str, Any]], model: llm.Model | None,
            stream: bool) -> Iterator[tuple[str, Any]]:
    """One round with the model, either in one piece or while it writes."""
    if stream:
        yield from llm.chat_stream(messages, schemas, model=model)
    else:
        yield "reply", llm.chat(messages, schemas, model=model)


def _loop(db: Session, thread: AssistantThread, ctx: tools.Context, stream: bool = False) -> Iterator[dict[str, Any]]:
    """Ask the model until it answers, running read tools and parking changing ones for confirmation.

    Yields what happens, so the browser can show it while it happens; the plain endpoint just drains it.
    """
    from almlight.core.config import get_settings

    steps = get_settings().assistant_max_steps
    schemas = tools.schemas(ctx)
    model = llm.resolve(thread.model or None)
    limit = _limit(model)
    for _ in range(steps):
        reply = None
        for kind, value in _answer(_history(db, thread, ctx), schemas, model, stream):
            if kind == "delta":
                yield {"type": "delta", "text": value}
            else:
                reply = value
        if reply is None:  # pragma: no cover — _answer always ends with a reply
            reply = llm.Reply(content="")
        if not reply.tool_calls:
            _add(db, thread, "assistant", reply.content or "…",
                 {"usage": reply.usage, "model": model.label if model else None})
            return
        calls = [{"id": c.id, "name": c.name, "arguments": c.arguments} for c in reply.tool_calls]
        _add(db, thread, "assistant", reply.content,
             {"tool_calls": calls, "usage": reply.usage, "model": model.label if model else None})
        pending: list[dict[str, Any]] = []
        for call in calls:
            tool = tools.BY_NAME.get(call["name"])
            if tool is not None and tool.writes and ctx.may_write():
                try:
                    preview = tools.preview(ctx, call["name"], call["arguments"])
                    error = None
                except DomainError as exc:
                    preview, error = None, exc.message
                except Exception as exc:  # noqa: BLE001
                    log.exception("assistant preview %s failed", call["name"])
                    preview, error = None, f"{type(exc).__name__}: {exc}"[:300]
                pending.append({"call_id": call["id"], "name": call["name"], "arguments": call["arguments"],
                                "summary": tools.describe(ctx, call["name"], call["arguments"]),
                                "preview": preview, "error": error})
            else:
                content, ok = _run_tool(ctx, call, limit)
                _add(db, thread, "tool", content, {"call_id": call["id"], "name": call["name"], "ok": ok})
                yield {"type": "tool", "name": call["name"], "ok": ok}
        if pending:  # wait for the person; the conversation continues after confirm()
            thread.pending = pending
            yield {"type": "pending", "count": len(pending)}
            return
    _add(db, thread, "assistant",
         "I stopped after several steps without reaching an answer. Please ask something more specific.", {})


def _begin_ask(db: Session, project: Project, user: User, thread: AssistantThread, text: str) -> tools.Context:
    """Everything before the model is asked: checks, the dropped proposals, the question and the audit entry."""
    text = (text or "").strip()
    if not text:
        raise ValidationFailed("Write a question for the assistant")
    if len(text) > 8000:
        raise ValidationFailed("The question is too long (at most 8000 characters)")
    if not llm.enabled():
        raise ValidationFailed("The AI assistant is not configured on this installation "
                               "(endpoint, key and deployment of the language model are missing)")
    ctx = tools.Context(db=db, project=project, user=user)
    if thread.pending:  # a new question drops proposals that were waiting
        _settle(db, thread, ctx, approve=False, note="The person asked something else instead.")
    if not thread.title:
        thread.title = text[:TITLE_CHARS]
    _add(db, thread, "user", text)
    audit.record(db, actor=user, action="assistant.asked", entity_type="project", entity_id=project.id,
                 project_id=project.id, summary=f"Asked the assistant in {project.key}",
                 details={"thread": str(thread.id), "question": text[:TITLE_CHARS]})
    return ctx


def ask(db: Session, project: Project, user: User, thread: AssistantThread, text: str) -> dict[str, Any]:
    """Ask and wait for the whole answer."""
    ctx = _begin_ask(db, project, user, thread, text)
    for _ in _loop(db, thread, ctx):
        pass
    return state(db, thread)


def ask_stream(db: Session, project: Project, user: User, thread: AssistantThread,
               text: str) -> Iterator[dict[str, Any]]:
    """Ask and follow along: yields the text as it is written and what the tools do."""
    ctx = _begin_ask(db, project, user, thread, text)
    yield from _loop(db, thread, ctx, stream=True)


def _settle(db: Session, thread: AssistantThread, ctx: tools.Context, *, approve: bool, note: str = "") -> int:
    """Apply or discard the waiting proposals and tell the model what happened."""
    applied = 0
    limit = _limit(llm.resolve(thread.model or None))  # a local model has a much smaller context
    for call in thread.pending:
        if approve and not call.get("error"):
            content, ok = _run_tool(ctx, call, limit)
            applied += int(ok)
            meta = {"call_id": call["call_id"], "name": call["name"], "ok": ok, "applied": ok,
                    "summary": call.get("summary")}
        else:
            reason = note or ("The person discarded this change." if approve is False else "")
            content = _result_text({"not_executed": call.get("error") or reason or "discarded by the person"},
                                   limit)
            meta = {"call_id": call["call_id"], "name": call["name"], "ok": False, "applied": False,
                    "summary": call.get("summary")}
        _add(db, thread, "tool", content, meta)
    thread.pending = []
    return applied


def _begin_confirm(db: Session, project: Project, user: User, thread: AssistantThread,
                   approve: bool) -> tuple[tools.Context, int]:
    if not thread.pending:
        raise ValidationFailed("There is nothing waiting for confirmation")
    ctx = tools.Context(db=db, project=project, user=user)
    if approve and not ctx.may_write():
        raise ValidationFailed("Changing the project needs the contributor role")
    proposals = [p.get("summary") or p["name"] for p in thread.pending]
    applied = _settle(db, thread, ctx, approve=approve)
    if approve:
        audit.record(db, actor=user, action="assistant.applied", entity_type="project", entity_id=project.id,
                     project_id=project.id,
                     summary=f"Applied {applied} change(s) proposed by the assistant in {project.key}",
                     details={"thread": str(thread.id), "proposals": proposals})
    return ctx, applied


def confirm(db: Session, project: Project, user: User, thread: AssistantThread, approve: bool) -> dict[str, Any]:
    ctx, _ = _begin_confirm(db, project, user, thread, approve)
    for _ in _loop(db, thread, ctx):
        pass
    return state(db, thread)


def confirm_stream(db: Session, project: Project, user: User, thread: AssistantThread,
                   approve: bool) -> Iterator[dict[str, Any]]:
    ctx, applied = _begin_confirm(db, project, user, thread, approve)
    yield {"type": "applied", "count": applied}
    yield from _loop(db, thread, ctx, stream=True)


def state(db: Session, thread: AssistantThread) -> dict[str, Any]:
    model = llm.resolve(thread.model or None)
    return {"id": str(thread.id), "title": thread.title or "…",
            "model": model.id if model else None, "model_label": model.label if model else None,
            "messages": [message_out(m) for m in messages(db, thread)],
            "pending": [{"summary": p.get("summary"), "name": p["name"], "arguments": p["arguments"],
                         "preview": p.get("preview"), "error": p.get("error")} for p in thread.pending]}
