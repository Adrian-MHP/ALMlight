"""Project archive: a self-contained JSON export with configuration, full version history,
links, workflow history and baselines — for backups, migration between installations and
handing a project over. Import recreates the project under a new key with the same item keys.
Attachment and image *content* stays in the file store; the archive lists the blobs it references.
Format 2 stores item texts as rich text (canonical HTML); format 1 archives (Markdown) are converted on import.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from almlight.core.errors import Conflict, ValidationFailed
from almlight.core.richtext import image_shas, looks_like_html, markdown_to_html
from almlight.modules.audit import service as audit
from almlight.modules.audit.service import jsonable
from almlight.modules.baselines.models import Baseline, BaselineItem, BaselineLink
from almlight.modules.identity.models import User
from almlight.modules.images.models import InlineImage
from almlight.modules.items import storage
from almlight.modules.items.models import Blob, Item, ItemVersion
from almlight.modules.links.models import Link
from almlight.modules.projects.metamodel import parse_config
from almlight.modules.projects.models import Project, ProjectCounter, ProjectMember
from almlight.modules.workflow.models import WorkflowEvent

FORMAT = "almlight-project-archive"
FORMAT_VERSION = 2
READABLE_VERSIONS = (1, 2)


def export_archive(db: Session, project: Project) -> dict[str, Any]:
    users = {u.id: u.username for u in db.execute(select(User)).scalars()}
    items = db.execute(
        select(Item).where(Item.project_id == project.id, Item.deleted_at.is_(None)).order_by(Item.type_key, Item.seq)
    ).scalars().all()
    ids = {i.id for i in items}
    key_of = {i.id: i.key for i in items}
    versions: dict[uuid.UUID, list[ItemVersion]] = {i: [] for i in ids}
    for v in db.execute(
        select(ItemVersion).where(ItemVersion.item_id.in_(ids)).order_by(ItemVersion.version_no)
    ).scalars():
        versions[v.item_id].append(v)
    events: dict[uuid.UUID, list[WorkflowEvent]] = {i: [] for i in ids}
    for e in db.execute(
        select(WorkflowEvent).where(WorkflowEvent.item_id.in_(ids)).order_by(WorkflowEvent.created_at)
    ).scalars():
        events[e.item_id].append(e)
    links = db.execute(
        select(Link).where(Link.project_id == project.id, Link.deleted_at.is_(None))
    ).scalars().all()
    baselines = []
    for b in db.execute(select(Baseline).where(Baseline.project_id == project.id)).scalars():
        entries = db.execute(select(BaselineItem).where(BaselineItem.baseline_id == b.id)).scalars().all()
        blinks = db.execute(select(BaselineLink).where(BaselineLink.baseline_id == b.id)).scalars().all()
        baselines.append({
            "name": b.name, "description": b.description, "revision_rule": b.revision_rule,
            "scope": key_of.get(b.scope_root_id) if b.scope_root_id else None,
            "created_at": b.created_at, "created_by": users.get(b.created_by),
            "items": [{"key": key_of.get(e.item_id), "version_no": e.version_no, "state": e.state}
                      for e in entries if e.item_id in key_of],
            "links": [{"type": bl.type_key, "source": key_of.get(bl.source_id), "target": key_of.get(bl.target_id),
                       "position": bl.position, "attributes": bl.attributes, "applicability": bl.applicability}
                      for bl in blinks if bl.source_id in key_of and bl.target_id in key_of],
        })

    def version_dict(v: ItemVersion) -> dict[str, Any]:
        return {"version_no": v.version_no, "revision": v.revision, "iteration": v.iteration, "kind": v.kind,
                "title": v.title, "description": v.description, "fields": v.fields,
                "applicability": v.applicability, "attachments": v.attachments, "state": v.state,
                "change_note": v.change_note, "change_order": key_of.get(v.change_order_id),
                "created_by": users.get(v.created_by), "created_at": v.created_at}

    data = {
        "format": FORMAT,
        "format_version": FORMAT_VERSION,
        "project": {"key": project.key, "name": project.name, "description": project.description,
                    "template_key": project.template_key, "config": project.config},
        "items": [{
            "key": i.key, "type": i.type_key, "state": i.state, "owner": users.get(i.owner_id),
            "released_version_no": next((v.version_no for v in versions[i.id] if v.id == i.released_version_id),
                                        None),
            "versions": [version_dict(v) for v in versions[i.id]],
            "workflow": [{"transition": e.transition_key, "from": e.from_state, "to": e.to_state, "via": e.via,
                          "actor": users.get(e.actor_id), "comment": e.comment, "version_no": e.version_no,
                          "signed": e.signed, "at": e.created_at} for e in events[i.id]],
        } for i in items],
        "links": [{"type": lk.type_key, "source": key_of[lk.source_id], "target": key_of[lk.target_id],
                   "position": lk.position, "attributes": lk.attributes, "applicability": lk.applicability,
                   "suspect": lk.suspect, "suspect_reason": lk.suspect_reason}
                  for lk in links if lk.source_id in key_of and lk.target_id in key_of],
        "baselines": baselines,
        "blobs": sorted({a["sha256"] for i in items for v in versions[i.id] for a in v.attachments}),
        "images": _images(db, project, {sha for i in items for v in versions[i.id]
                                        for sha in image_shas(v.description)}),
    }
    return jsonable(data)


def _images(db: Session, project: Project, shas: set[str]) -> list[dict[str, Any]]:
    if not shas:
        return []
    rows = db.execute(select(InlineImage).where(InlineImage.project_id == project.id,
                                                InlineImage.sha256.in_(shas))).scalars()
    return [{"sha256": r.sha256, "filename": r.filename, "content_type": r.content_type, "size": r.size,
             "width": r.width, "height": r.height} for r in sorted(rows, key=lambda r: r.sha256)]


def import_archive(db: Session, actor: User, data: dict[str, Any], *, new_key: str, new_name: str | None = None
                   ) -> Project:
    if data.get("format") != FORMAT or data.get("format_version") not in READABLE_VERSIONS:
        raise ValidationFailed("Not a project archive of this application (format/version mismatch)")
    legacy = data.get("format_version") == 1

    def text(value: str | None) -> str:
        value = value or ""
        return markdown_to_html(value) if legacy and value and not looks_like_html(value) else value
    new_key = new_key.strip().upper()
    if db.execute(select(Project.id).where(Project.key == new_key)).scalar():
        raise Conflict(f"Project key '{new_key}' is already in use")
    src = data["project"]
    template = parse_config(src["config"])  # validates the configuration
    project = Project(key=new_key, name=new_name or src["name"], description=src.get("description"),
                      template_key=src.get("template_key", template.key), config=src["config"],
                      created_by=actor.id)
    db.add(project)
    db.flush()
    db.add(ProjectMember(project_id=project.id, user_id=actor.id, role="manager"))
    users = {u.username: u.id for u in db.execute(select(User)).scalars()}
    id_of: dict[str, uuid.UUID] = {}
    counters: dict[str, int] = {}
    for raw in data.get("items", []):
        versions = raw.get("versions") or []
        if not versions:
            continue
        head = versions[-1]
        prefix, _, seq = raw["key"].rpartition("-")
        item = Item(project_id=project.id, type_key=raw["type"], key=raw["key"], seq=int(seq),
                    title=head["title"], description=text(head.get("description")), fields=head.get("fields", {}),
                    applicability=head.get("applicability"), attachments=head.get("attachments", []),
                    state=raw.get("state"), revision=head["revision"], iteration=head["iteration"],
                    version_no=head["version_no"], owner_id=users.get(raw.get("owner")), created_by=actor.id,
                    updated_by=actor.id)
        db.add(item)
        db.flush()
        id_of[raw["key"]] = item.id
        counters[prefix] = max(counters.get(prefix, 0), int(seq))
        for v in versions:
            iv = ItemVersion(item_id=item.id, version_no=v["version_no"], revision=v["revision"],
                             iteration=v["iteration"], kind=v.get("kind", "import"), title=v["title"],
                             description=text(v.get("description")), fields=v.get("fields", {}),
                             applicability=v.get("applicability"), attachments=v.get("attachments", []),
                             state=v.get("state"), change_note=v.get("change_note"),
                             created_by=users.get(v.get("created_by")))
            db.add(iv)
            db.flush()
            if v["version_no"] == head["version_no"]:
                item.head_version_id = iv.id
            if v["version_no"] == raw.get("released_version_no"):
                item.released_version_id = iv.id
        for e in raw.get("workflow", []):
            db.add(WorkflowEvent(item_id=item.id, transition_key=e.get("transition"), from_state=e.get("from"),
                                 to_state=e["to"], via=e.get("via", "transition"), actor_id=users.get(e.get("actor")),
                                 comment=e.get("comment"), version_no=e.get("version_no", 1),
                                 signed=bool(e.get("signed"))))
    for prefix, last in counters.items():
        db.add(ProjectCounter(project_id=project.id, prefix=prefix, next_value=last + 1))
    for img in data.get("images", []):
        if storage.exists(img["sha256"]) and db.get(Blob, img["sha256"]) is not None:
            db.add(InlineImage(project_id=project.id, sha256=img["sha256"], filename=img.get("filename", "image"),
                               content_type=img.get("content_type", "image/png"), size=img.get("size", 0),
                               width=img.get("width"), height=img.get("height"), uploaded_by=actor.id))
    for lk in data.get("links", []):
        if lk["source"] in id_of and lk["target"] in id_of:
            db.add(Link(project_id=project.id, type_key=lk["type"], source_id=id_of[lk["source"]],
                        target_id=id_of[lk["target"]], position=lk.get("position"),
                        attributes=lk.get("attributes") or {}, applicability=lk.get("applicability"),
                        suspect=bool(lk.get("suspect")), suspect_reason=lk.get("suspect_reason"),
                        created_by=actor.id))
    db.flush()
    versions_by_item = {
        (v.item_id, v.version_no): v
        for v in db.execute(select(ItemVersion).where(ItemVersion.item_id.in_(id_of.values()))).scalars()
    }
    for b in data.get("baselines", []):
        baseline = Baseline(project_id=project.id, name=b["name"], description=b.get("description"),
                            revision_rule=b.get("revision_rule", "latest"),
                            scope_root_id=id_of.get(b.get("scope")) if b.get("scope") else None,
                            created_by=actor.id)
        db.add(baseline)
        db.flush()
        n = 0
        for e in b.get("items", []):
            iid = id_of.get(e["key"])
            v = versions_by_item.get((iid, e["version_no"])) if iid else None
            if v is None:
                continue
            db.add(BaselineItem(baseline_id=baseline.id, item_id=iid, version_id=v.id, version_no=v.version_no,
                                revision=v.revision, iteration=v.iteration, state=e.get("state")))
            n += 1
        m = 0
        for bl in b.get("links", []):
            if bl["source"] in id_of and bl["target"] in id_of:
                db.add(BaselineLink(baseline_id=baseline.id, link_id=uuid.uuid4(), type_key=bl["type"],
                                    source_id=id_of[bl["source"]], target_id=id_of[bl["target"]],
                                    position=bl.get("position"), attributes=bl.get("attributes") or {},
                                    applicability=bl.get("applicability")))
                m += 1
        baseline.item_count, baseline.link_count = n, m
    db.flush()
    audit.record(db, actor=actor, action="project.imported", entity_type="project", entity_id=project.id,
                 project_id=project.id, summary=f"Imported project {new_key} from archive of {src['key']}",
                 details={"items": len(id_of), "links": len(data.get("links", [])),
                          "baselines": len(data.get("baselines", []))})
    return project
