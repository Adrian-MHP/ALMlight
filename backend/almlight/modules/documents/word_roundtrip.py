"""Word round trip: export a document for external review in Word, import their edits and comments.

Export (see ``io.document_export.render_docx(roundtrip=...)``) wraps every item's title and text in a Word
*content control* tagged ``alm:<item id>:<version no>:<title|desc>``; ``edit`` mode lets reviewers change the text
inside the controls, ``comments`` mode protects the document so only comments are possible.

Import reads the controls back, converts the Word content to rich text with the *same* reader that is applied to
the exported version (so untouched text never shows up as a change; formatting, lists, tables, links and images
survive), and applies a 3-way rule against the exported version: changes are applied when the item did not change
in the meantime (or changed in another field); otherwise they are reported as conflicts. Frozen items are
reported, not changed. Word comments — including replies and their resolved state — become document comments on
the item they were made on.
"""

from __future__ import annotations

import hashlib
import io
import re
import uuid
import zipfile
from typing import Any

from lxml import etree
from sqlalchemy import select
from sqlalchemy.orm import Session

from almlight.core.db import utcnow
from almlight.core.errors import DomainError, ValidationFailed
from almlight.modules.audit import service as audit
from almlight.modules.identity.models import User
from almlight.modules.items import service as items_svc
from almlight.modules.items.lifecycle import is_frozen
from almlight.modules.items.models import Comment, Item, ItemVersion
from almlight.modules.projects.models import Project

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
W14 = "http://schemas.microsoft.com/office/word/2010/wordml"
W15 = "http://schemas.microsoft.com/office/word/2012/wordml"
NS = {"w": W, "w14": W14, "w15": W15}
TAG_RE = re.compile(r"^alm:([0-9a-f-]{36}):(\d+):(title|desc)$")
_PARSER = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False, remove_blank_text=False)


def identifier(project_key: str, doc_key: str) -> str:
    return f"almlight:{project_key}:{doc_key}"


def _q(tag: str) -> str:
    p, local = tag.split(":")
    return f"{{{NS[p]}}}{local}"


def _on(el: etree._Element | None) -> bool:
    if el is None:
        return False
    return el.get(_q("w:val"), "true").lower() not in ("0", "false", "none")


# --- Word -> rich text --------------------------------------------------------------------------


def roundtrip_html(html: str) -> str:
    """What the exported text looks like after Word: render with the export pipeline, read back."""
    from almlight.modules.io.rich_render import docx_roundtrip_html

    return docx_roundtrip_html(html or "")


def _text(el: etree._Element) -> str:
    return "".join(t.text or "" for t in el.iter(_q("w:t")))


# --- import --------------------------------------------------------------------------------------


def _read(content: bytes) -> dict[str, etree._Element | None]:
    try:
        z = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile:
        raise ValidationFailed("Not a Word (.docx) file") from None
    names = set(z.namelist())
    if "word/document.xml" not in names:
        raise ValidationFailed("Not a Word (.docx) file")

    def parse(name: str) -> etree._Element | None:
        if name not in names:
            return None
        try:
            return etree.fromstring(z.read(name), _PARSER)
        except etree.XMLSyntaxError as exc:
            raise ValidationFailed(f"Corrupt Word file ({name}): {exc}") from None

    rels: dict[str, tuple[str, str]] = {}
    rel_xml = parse("word/_rels/document.xml.rels")
    if rel_xml is not None:
        for r in rel_xml:
            rels[r.get("Id")] = (r.get("Type"), r.get("Target"))

    def media(rid: str) -> bytes | None:
        rel = rels.get(rid)
        if rel is None or not rel[0].endswith("/image"):
            return None
        target = rel[1].lstrip("/")
        name = target if target.startswith("word/") else f"word/{target}"
        return z.read(name) if name in names else None

    return {"document": parse("word/document.xml"), "comments": parse("word/comments.xml"),
            "comments_ext": parse("word/commentsExtended.xml"), "core": parse("docProps/core.xml"),
            "styles": parse("word/styles.xml"), "numbering": parse("word/numbering.xml"), "rels": rels,
            "media": media}


def _context(parts: dict[str, Any]) -> Any:
    from almlight.modules.io.rich_render import DocxContext

    style_names: dict[str, str] = {}
    if parts["styles"] is not None:
        for st in parts["styles"].iter(_q("w:style")):
            name = st.find(_q("w:name"))
            style_names[st.get(_q("w:styleId"))] = name.get(_q("w:val")) if name is not None else st.get(
                _q("w:styleId"))
    return DocxContext(style_names, parts["numbering"], parts["rels"], parts["media"])


def import_docx(db: Session, project: Project, actor: User, doc_item: Item, filename: str, content: bytes, *,
                dry_run: bool = True) -> dict[str, Any]:
    parts = _read(content)
    core = parts["core"]
    ident = None
    if core is not None:
        el = core.find("{http://purl.org/dc/elements/1.1/}identifier")
        ident = el.text if el is not None else None
    if ident != identifier(project.key, doc_item.key):
        raise ValidationFailed(f"This Word file was not exported from {doc_item.key} for round trip"
                               f"{f' (it belongs to {ident})' if ident else ''}")
    document = parts["document"]
    assert document is not None
    from almlight.core.errors import DomainError as _DomainError
    from almlight.modules.images import service as images_svc
    from almlight.modules.io.rich_render import DocxReader

    def store(data: bytes, name: str) -> str | None:
        try:
            return images_svc.image_url(images_svc.store_image(db, project, actor, data, name).sha256)
        except _DomainError:
            return None

    reader = DocxReader(_context(parts), store)
    results: list[dict[str, Any]] = []
    summary = {"updated": 0, "unchanged": 0, "conflicts": 0, "frozen": 0, "missing": 0, "comments": 0}
    savepoint = db.begin_nested()  # images found in the file are stored inside it (dry run: rolled back)
    try:
        controls: dict[tuple[uuid.UUID, str], dict[str, Any]] = {}
        for sdt in document.iter(_q("w:sdt")):
            tag_el = sdt.find(f"{_q('w:sdtPr')}/{_q('w:tag')}")
            m = TAG_RE.match(tag_el.get(_q("w:val"), "")) if tag_el is not None else None
            if not m:
                continue
            item_id, base_no, part = uuid.UUID(m.group(1)), int(m.group(2)), m.group(3)
            content_el = sdt.find(_q("w:sdtContent"))
            value = (_text(content_el).strip() if part == "title"
                     else _blocks_html(reader, list(content_el) if content_el is not None else []))
            controls[(item_id, part)] = {"base": base_no, "value": value}
        by_item: dict[uuid.UUID, dict[str, dict[str, Any]]] = {}
        for (item_id, part), c in controls.items():
            by_item.setdefault(item_id, {})[part] = c
        for item_id, item_parts in by_item.items():
            item = db.get(Item, item_id)
            base_no = next(iter(item_parts.values()))["base"]
            if item is None or item.project_id != project.id or item.deleted_at is not None:
                summary["missing"] += 1
                results.append({"item_id": str(item_id), "status": "missing"})
                continue
            base = db.execute(select(ItemVersion).where(ItemVersion.item_id == item.id,
                                                        ItemVersion.version_no == base_no)).scalar_one_or_none()
            if base is None:
                summary["missing"] += 1
                results.append({"key": item.key, "status": "missing"})
                continue
            change: dict[str, str] = {}
            conflicts: list[str] = []
            diffs: list[dict[str, Any]] = []
            if "title" in item_parts:
                new = re.sub(r"\s+", " ", item_parts["title"]["value"]).strip()
                if new and new != re.sub(r"\s+", " ", base.title).strip():
                    diffs.append({"field": "title", "old": base.title, "new": new})
                    if item.title != base.title:
                        conflicts.append("title")
                    else:
                        change["title"] = new
            if "desc" in item_parts:
                new = item_parts["desc"]["value"]
                if new != roundtrip_html(base.description):
                    diffs.append({"field": "description", "old": base.description, "new": new})
                    if item.description != base.description:
                        conflicts.append("description")
                    else:
                        change["description"] = new
            if not diffs:
                summary["unchanged"] += 1
                continue
            entry = {"key": item.key, "title": item.title, "base_version": f"{base.revision}.{base.iteration}",
                     "current_version": item.version_label, "changes": diffs}
            if conflicts:
                summary["conflicts"] += 1
                results.append({**entry, "status": "conflict", "conflicts": conflicts})
                continue
            if is_frozen(project, item):
                summary["frozen"] += 1
                results.append({**entry, "status": "frozen"})
                continue
            try:
                items_svc.update_item(db, project, actor, item, items_svc.ContentChange(
                    title=change.get("title"), description=change.get("description")),
                    change_note=f"Word round trip ({filename})")
                summary["updated"] += 1
                results.append({**entry, "status": "updated", "new_version": item.version_label})
            except DomainError as exc:
                summary["conflicts"] += 1
                results.append({**entry, "status": "error", "error": exc.message})

        comments = _import_comments(db, project, actor, doc_item, parts)
        summary["comments"] = len(comments)
        applied = not dry_run
        if applied:
            audit.record(db, actor=actor, action="document.word_imported", entity_type="item", entity_id=doc_item.id,
                         project_id=project.id,
                         summary=f"Word round trip into {doc_item.key}: {summary['updated']} updated, "
                                 f"{summary['comments']} comments, {summary['conflicts']} conflicts",
                         details={"file": filename, "summary": summary}, related_ids=[doc_item.id])
            savepoint.commit()
        else:
            savepoint.rollback()
    except Exception:
        savepoint.rollback()
        raise
    order = {"conflict": 0, "error": 0, "frozen": 1, "updated": 2, "missing": 3}
    results.sort(key=lambda r: (order.get(r["status"], 9), r.get("key", "")))
    return {"dry_run": dry_run, "applied": applied, "summary": summary, "items": results,
            "comments": comments[:200]}


def _blocks_html(reader: Any, elements: list[etree._Element]) -> str:
    from almlight.core.richtext import canonical, to_html

    return canonical(to_html(reader.blocks(elements)), lambda src, attrs: src)


def _import_comments(db: Session, project: Project, actor: User, doc_item: Item,
                     parts: dict[str, etree._Element | None]) -> list[dict[str, Any]]:
    comments_xml = parts["comments"]
    if comments_xml is None:
        return []
    document = parts["document"]
    # Which item does each comment belong to? The content control it sits in, else the one before it.
    anchor: dict[str, uuid.UUID] = {}
    current = doc_item.id
    for el in document.iter():
        if el.tag == _q("w:sdt"):
            tag_el = el.find(f"{_q('w:sdtPr')}/{_q('w:tag')}")
            m = TAG_RE.match(tag_el.get(_q("w:val"), "")) if tag_el is not None else None
            if m:
                current = uuid.UUID(m.group(1))
        elif el.tag in (_q("w:commentRangeStart"), _q("w:commentReference")):
            cid = el.get(_q("w:id"))
            if cid is not None and cid not in anchor:
                anchor[cid] = current
    ext: dict[str, dict[str, str | None]] = {}
    if parts["comments_ext"] is not None:
        for ce in parts["comments_ext"].iter(_q("w15:commentEx")):
            ext[ce.get(_q("w15:paraId"))] = {"parent": ce.get(_q("w15:paraIdParent")), "done": ce.get(_q("w15:done"))}
    raw = []
    para_to_cid: dict[str, str] = {}
    for c in comments_xml.iter(_q("w:comment")):
        cid = c.get(_q("w:id"))
        paras = c.findall(_q("w:p"))
        text = "\n".join(_text(p) for p in paras).strip()
        para_id = paras[-1].get(_q("w14:paraId")) if paras else None
        if para_id:
            para_to_cid[para_id] = cid
        raw.append({"id": cid, "author": c.get(_q("w:author")) or "Reviewer", "date": c.get(_q("w:date")) or "",
                    "text": text, "para": para_id})
    created: dict[str, Comment] = {}
    out = []
    for r in raw:
        if not r["text"]:
            continue
        info = ext.get(r["para"] or "", {})
        parent_cid = para_to_cid.get(info.get("parent") or "") if info else None
        item_id = anchor.get(r["id"]) or (anchor.get(parent_cid) if parent_cid else None) or doc_item.id
        item = db.get(Item, item_id)
        if item is None or item.project_id != project.id:
            item = doc_item
        ref = "word:" + hashlib.sha1(f"{r['author']}|{r['date']}|{r['text']}".encode()).hexdigest()[:20]
        if db.execute(select(Comment.id).where(Comment.item_id == item.id, Comment.external_ref == ref)).scalar():
            continue
        parent = created.get(parent_cid) if parent_cid else None
        com = Comment(item_id=item.id, document_id=doc_item.id, parent_id=parent.id if parent else None,
                      author_id=actor.id, external_author=r["author"], external_ref=ref, source="word",
                      body=r["text"][:20_000],
                      resolved_at=utcnow() if (info or {}).get("done") == "1" else None,
                      resolved_by=actor.id if (info or {}).get("done") == "1" else None)
        db.add(com)
        db.flush()
        created[r["id"]] = com
        out.append({"item": item.key, "author": r["author"], "text": r["text"][:300], "reply": parent is not None})
    return out
