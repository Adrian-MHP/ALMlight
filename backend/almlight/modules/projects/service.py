from __future__ import annotations

import re
import uuid
from typing import Any

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from almlight.core.errors import Conflict, NotFound, ValidationFailed
from almlight.modules.audit import service as audit
from almlight.modules.identity.models import User
from almlight.modules.items.models import Item
from almlight.modules.links.models import Link
from almlight.modules.projects.metamodel import ROLE_RANK, available_templates, dump_config, parse_config
from almlight.modules.projects.models import Project, ProjectMember
from almlight.modules.workflow.models import ApprovalRequest

PROJECT_KEY_RE = re.compile(r"^[A-Z][A-Z0-9]{1,15}$")


def create_project(db: Session, actor: User, *, key: str, name: str, template_key: str,
                   description: str | None = None) -> Project:
    key = (key or "").strip().upper()
    if not PROJECT_KEY_RE.match(key):
        raise ValidationFailed("Project key: 2-16 characters, uppercase letters and digits, starting with a letter")
    if not (name or "").strip():
        raise ValidationFailed("Project name is required")
    templates = available_templates()
    if template_key not in templates:
        raise ValidationFailed(f"Unknown template '{template_key}'", {"available": sorted(templates)})
    if db.execute(select(Project.id).where(Project.key == key)).scalar():
        raise Conflict(f"Project key '{key}' is already in use")
    project = Project(key=key, name=name.strip()[:200], description=description, template_key=template_key,
                      config=dump_config(templates[template_key]), created_by=actor.id)
    db.add(project)
    db.flush()
    db.add(ProjectMember(project_id=project.id, user_id=actor.id, role="manager"))
    audit.record(db, actor=actor, action="project.created", entity_type="project", entity_id=project.id,
                 project_id=project.id, summary=f"Created project {key} from template '{template_key}'")
    return project


def update_project(db: Session, actor: User, project: Project, *, name: str | None = None,
                   description: str | None = None) -> Project:
    if name is not None:
        if not name.strip():
            raise ValidationFailed("Project name is required")
        project.name = name.strip()[:200]
    if description is not None:
        project.description = description
    audit.record(db, actor=actor, action="project.updated", entity_type="project", entity_id=project.id,
                 project_id=project.id, summary=f"Updated project {project.key}")
    return project


def update_config(db: Session, actor: User, project: Project, config: dict[str, Any]) -> Project:
    """Replace the information model after checking it is valid and compatible with existing data."""
    try:
        new = parse_config(config)
    except ValidationError as exc:
        raise ValidationFailed("Invalid configuration", {"errors": [
            {"loc": list(e["loc"]), "msg": e["msg"]} for e in exc.errors()]}) from None
    problems = []
    used_types = db.execute(
        select(Item.type_key).where(Item.project_id == project.id, Item.deleted_at.is_(None)).distinct()
    ).scalars().all()
    for t in used_types:
        if new.item_type(t) is None:
            problems.append(f"Item type '{t}' is in use and cannot be removed")
    for t, state in db.execute(
        select(Item.type_key, Item.state).where(Item.project_id == project.id, Item.deleted_at.is_(None))
        .group_by(Item.type_key, Item.state)
    ).all():
        wf = new.workflow_for(t)
        if state is not None and (wf is None or wf.state(state) is None):
            problems.append(f"State '{state}' of type '{t}' is in use and must stay in its workflow")
    used_links = db.execute(
        select(Link.type_key).where(Link.project_id == project.id, Link.deleted_at.is_(None)).distinct()
    ).scalars().all()
    for lk in used_links:
        if new.link_type(lk) is None:
            problems.append(f"Link type '{lk}' is in use and cannot be removed")
    old_prefixes = {t.key: t.prefix for t in project.model.item_types}
    for t in new.item_types:
        if t.key in used_types and old_prefixes.get(t.key) not in (None, t.prefix):
            problems.append(f"Prefix of '{t.key}' cannot change while items exist")
    if problems:
        raise Conflict("The configuration is not compatible with existing data", {"problems": problems})
    old_version = project.config_version
    project.config = dump_config(new)
    project.config_version = old_version + 1
    audit.record(db, actor=actor, action="project.config_changed", entity_type="project", entity_id=project.id,
                 project_id=project.id,
                 summary=f"Changed information model of {project.key} (v{old_version} -> v{project.config_version})")
    return project


def set_member(db: Session, actor: User, project: Project, user: User, role: str, *,
               hours_per_day: float | None = None) -> ProjectMember:
    if role not in ROLE_RANK:
        raise ValidationFailed(f"role must be one of {list(ROLE_RANK)}")
    member = db.get(ProjectMember, (project.id, user.id))
    if member is None:
        member = ProjectMember(project_id=project.id, user_id=user.id, role=role)
        db.add(member)
    else:
        if member.role == "manager" and role != "manager":
            _ensure_other_manager(db, project, user.id)
        member.role = role
    if hours_per_day is not None:
        member.hours_per_day = round(hours_per_day, 2)
    db.flush()
    db.info.pop("role_cache", None)
    hours = f", {member.hours_per_day:g} h/day" if hours_per_day is not None else ""
    audit.record(db, actor=actor, action="member.set", entity_type="project", entity_id=project.id,
                 project_id=project.id, summary=f"{user.username} is now {role} in {project.key}{hours}")
    return member


def remove_member(db: Session, actor: User, project: Project, user_id: uuid.UUID) -> None:
    member = db.get(ProjectMember, (project.id, user_id))
    if member is None:
        raise NotFound("Member not found")
    if member.role == "manager":
        _ensure_other_manager(db, project, user_id)
    db.delete(member)
    db.info.pop("role_cache", None)
    user = db.get(User, user_id)
    audit.record(db, actor=actor, action="member.removed", entity_type="project", entity_id=project.id,
                 project_id=project.id, summary=f"Removed {user.username if user else user_id} from {project.key}")


def _ensure_other_manager(db: Session, project: Project, user_id: uuid.UUID) -> None:
    others = db.execute(
        select(func.count()).select_from(ProjectMember).where(
            ProjectMember.project_id == project.id, ProjectMember.role == "manager", ProjectMember.user_id != user_id)
    ).scalar_one()
    if others == 0:
        raise ValidationFailed("A project needs at least one manager")


def stats(db: Session, project: Project) -> dict[str, Any]:
    model = project.model
    by_type: dict[str, dict[str, int]] = {}
    for type_key, state, n in db.execute(
        select(Item.type_key, Item.state, func.count()).where(Item.project_id == project.id,
                                                              Item.deleted_at.is_(None))
        .group_by(Item.type_key, Item.state)
    ).all():
        by_type.setdefault(type_key, {})[state or "-"] = n
    suspect = db.execute(
        select(func.count()).select_from(Link).where(Link.project_id == project.id, Link.suspect.is_(True),
                                                     Link.deleted_at.is_(None))
    ).scalar_one()
    pending = db.execute(
        select(func.count()).select_from(ApprovalRequest).where(ApprovalRequest.project_id == project.id,
                                                                ApprovalRequest.status == "pending")
    ).scalar_one()
    open_changes = 0
    for t in model.item_types:
        if t.category != "change":
            continue
        wf = model.workflow(t.workflow)
        for state, n in by_type.get(t.key, {}).items():
            s = wf.state(state) if wf else None
            if s is None or s.category not in ("closed", "released", "obsolete"):
                open_changes += n
    return {"items_by_type": by_type, "suspect_links": suspect, "pending_approvals": pending,
            "open_changes": open_changes,
            "total_items": sum(sum(v.values()) for v in by_type.values())}


# --- template updates --------------------------------------------------------------------------------------


def template_updates(project: Project) -> dict[str, Any]:
    """Additive differences between the project's information model and the shipped template it came from."""
    shipped = available_templates().get(project.template_key)
    cfg = project.model
    empty = {"template": project.template_key, "available": False, "count": 0, "item_types": [], "fields": [],
             "link_types": [], "link_attributes": [], "link_endpoints": [], "workflows": [], "translations": [],
             "skipped": []}
    if shipped is None:
        return empty
    out = dict(empty, available=True, template_version=shipped.version)
    used_prefixes = {t.prefix for t in cfg.item_types}
    for t in shipped.item_types:
        current = cfg.item_type(t.key)
        if current is None:
            if t.prefix in used_prefixes:
                out["skipped"].append(f"Item type '{t.key}': prefix {t.prefix} is already used")
                continue
            out["item_types"].append({"key": t.key, "label": t.label, "prefix": t.prefix})
        else:
            for f in t.fields:
                if current.field(f.key) is None:
                    out["fields"].append({"type": t.key, "key": f.key, "label": f.label, "field_type": f.type})
    new_types = {x["key"] for x in out["item_types"]}
    known_types = {t.key for t in cfg.item_types} | new_types
    for lt in shipped.link_types:
        current = cfg.link_type(lt.key)
        if current is None:
            out["link_types"].append({"key": lt.key, "label": lt.label})
            continue
        for a in lt.attributes:
            if not any(x.key == a.key for x in current.attributes):
                out["link_attributes"].append({"link": lt.key, "key": a.key, "label": a.label})
        add_src = [x for x in lt.sources
                   if x not in current.sources and "*" not in current.sources and x in known_types]
        add_tgt = [x for x in lt.targets
                   if x not in current.targets and "*" not in current.targets and x in known_types]
        if add_src or add_tgt:
            out["link_endpoints"].append({"link": lt.key, "sources": add_src, "targets": add_tgt})
    for w in shipped.workflows:
        if cfg.workflow(w.key) is None and any(t.workflow == w.key for t in shipped.item_types
                                               if t.key in new_types or cfg.item_type(t.key)):
            out["workflows"].append({"key": w.key, "label": w.label})
    for loc, labels in shipped.translations.items():
        have = cfg.translations.get(loc, {})
        missing = [k for k in labels if k not in have]
        if missing:
            out["translations"].append({"locale": loc, "count": len(missing)})
    out["count"] = sum(len(out[k]) for k in ("item_types", "fields", "link_types", "link_attributes",
                                              "link_endpoints", "workflows", "translations"))
    return out


def apply_template_updates(db: Session, actor: User, project: Project) -> dict[str, Any]:
    diff = template_updates(project)
    if not diff["count"]:
        return diff
    shipped = available_templates()[project.template_key]
    cfg = dump_config(project.model)
    by_type = {t["key"]: t for t in cfg["item_types"]}
    by_link = {lt["key"]: lt for lt in cfg["link_types"]}
    wf_keys = {w["key"] for w in diff["workflows"]}
    for w in shipped.workflows:
        if w.key in wf_keys:
            cfg["workflows"].append(w.model_dump(mode="json", by_alias=True))
    for t in shipped.item_types:
        if any(x["key"] == t.key for x in diff["item_types"]):
            cfg["item_types"].append(t.model_dump(mode="json", by_alias=True))
        for f in t.fields:
            if any(x["type"] == t.key and x["key"] == f.key for x in diff["fields"]):
                by_type[t.key]["fields"].append(f.model_dump(mode="json", by_alias=True))
    for lt in shipped.link_types:
        if any(x["key"] == lt.key for x in diff["link_types"]):
            cfg["link_types"].append(lt.model_dump(mode="json", by_alias=True))
            continue
        for a in lt.attributes:
            if any(x["link"] == lt.key and x["key"] == a.key for x in diff["link_attributes"]):
                by_link[lt.key]["attributes"].append(a.model_dump(mode="json", by_alias=True))
        for ep in diff["link_endpoints"]:
            if ep["link"] == lt.key:
                by_link[lt.key]["sources"] += ep["sources"]
                by_link[lt.key]["targets"] += ep["targets"]
    for entry in diff["translations"]:
        own = cfg.setdefault("translations", {}).setdefault(entry["locale"], {})
        for k, v in shipped.translations.get(entry["locale"], {}).items():
            own.setdefault(k, v)  # tailored translations of the project are kept
    update_config(db, actor, project, cfg)
    audit.record(db, actor=actor, action="project.template_updated", entity_type="project", entity_id=project.id,
                 project_id=project.id, summary=f"Took over {diff['count']} additions from template "
                 f"'{project.template_key}' v{diff.get('template_version')}", details=diff)
    return diff
