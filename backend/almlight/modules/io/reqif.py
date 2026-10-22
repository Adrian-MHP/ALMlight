"""ReqIF 1.2 export (OMG Requirements Interchange Format).

Exports a specification (its structural sub-tree) or all requirement-category items of a
project as SPEC-OBJECTs with typed attributes, SPEC-RELATIONs for links between exported
items and a SPECIFICATION hierarchy. Descriptions are exported as XHTML paragraphs.
This is the format DOORS, Polarion, codebeamer and most OEM supplier portals exchange.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from xml.etree import ElementTree as ET

from sqlalchemy import select
from sqlalchemy.orm import Session

from almlight import __version__
from almlight.modules.items.models import Item
from almlight.modules.links import service as links_svc
from almlight.modules.links.models import Link
from almlight.modules.projects.models import Project

NS = "http://www.omg.org/spec/ReqIF/20110401/reqif.xsd"
XHTML = "http://www.w3.org/1999/xhtml"
ET.register_namespace("", NS)
ET.register_namespace("xhtml", XHTML)


def _q(tag: str) -> str:
    return f"{{{NS}}}{tag}"


def _id(*parts: object) -> str:
    return "_" + uuid.uuid5(uuid.NAMESPACE_URL, "almlight:" + ":".join(map(str, parts))).hex


def _sub(parent: ET.Element, tag: str, **attrs: str) -> ET.Element:
    return ET.SubElement(parent, _q(tag), {k.replace("_", "-").upper(): v for k, v in attrs.items()})


def _string_value(values: ET.Element, definition_id: str, value: str) -> None:
    av = _sub(values, "ATTRIBUTE-VALUE-STRING", the_value=value)
    _sub(_sub(av, "DEFINITION"), "ATTRIBUTE-DEFINITION-STRING-REF").text = definition_id


def export_reqif(db: Session, project: Project, root: Item | None = None) -> bytes:
    model = project.model
    now = datetime.now(UTC).isoformat()
    structural = model.structural_link_types()
    if root is not None:
        ids = links_svc.descendant_ids(db, root.id, structural)
        items = db.execute(select(Item).where(Item.id.in_(ids))).scalars().all() if ids else []
    else:
        req_types = [t.key for t in model.item_types if t.category == "requirement"]
        items = db.execute(
            select(Item).where(Item.project_id == project.id, Item.type_key.in_(req_types), Item.deleted_at.is_(None))
            .order_by(Item.type_key, Item.seq)
        ).scalars().all()
    by_id = {i.id: i for i in items}
    used_types = [t for t in model.item_types if any(i.type_key == t.key for i in items)]

    reqif = ET.Element(_q("REQ-IF"))
    header = _sub(_sub(reqif, "THE-HEADER"), "REQ-IF-HEADER", identifier=_id(project.key, "header", now))
    for tag, text in (("CREATION-TIME", now), ("REQ-IF-TOOL-ID", f"ALMlight {__version__}"),
                      ("REQ-IF-VERSION", "1.0"), ("SOURCE-TOOL-ID", "ALMlight"),
                      ("TITLE", f"{project.key} — {root.title if root else project.name}")):
        _sub(header, tag).text = text
    content = _sub(_sub(reqif, "CORE-CONTENT"), "REQ-IF-CONTENT")

    datatypes = _sub(content, "DATATYPES")
    dt_string = _id("dt", "string")
    dt_xhtml = _id("dt", "xhtml")
    _sub(datatypes, "DATATYPE-DEFINITION-STRING", identifier=dt_string, long_name="String", max_length="32000",
         last_change=now)
    _sub(datatypes, "DATATYPE-DEFINITION-XHTML", identifier=dt_xhtml, long_name="XHTML", last_change=now)
    enum_dt: dict[tuple[str, str], tuple[str, dict[str, str]]] = {}
    for t in used_types:
        for f in t.fields:
            if f.type == "enum":
                dt_id = _id("dt", t.key, f.key)
                el = _sub(datatypes, "DATATYPE-DEFINITION-ENUMERATION", identifier=dt_id,
                          long_name=f"{t.label}.{f.label}", last_change=now)
                values = _sub(el, "SPECIFIED-VALUES")
                value_ids = {}
                for n, opt in enumerate(f.options):
                    vid = _id("ev", t.key, f.key, opt.key)
                    value_ids[opt.key] = vid
                    ev = _sub(values, "ENUM-VALUE", identifier=vid, long_name=opt.label, last_change=now)
                    _sub(_sub(ev, "PROPERTIES"), "EMBEDDED-VALUE", key=str(n), other_content=opt.key)
                enum_dt[(t.key, f.key)] = (dt_id, value_ids)

    spec_types = _sub(content, "SPEC-TYPES")
    attr_ids: dict[tuple[str, str], str] = {}
    for t in used_types:
        st = _sub(spec_types, "SPEC-OBJECT-TYPE", identifier=_id("st", t.key), long_name=t.label, last_change=now)
        defs = _sub(st, "SPEC-ATTRIBUTES")
        for akey, label, kind in [("_key", "ID", "string"), ("_title", "Title", "string"),
                                  ("_description", "Description", "xhtml"), ("_state", "Status", "string"),
                                  ("_version", "Version", "string")] + [
                                      (f.key, f.label, "enum" if (t.key, f.key) in enum_dt else "string")
                                      for f in t.fields]:
            aid = _id("ad", t.key, akey)
            attr_ids[(t.key, akey)] = aid
            tag = {"string": "ATTRIBUTE-DEFINITION-STRING", "xhtml": "ATTRIBUTE-DEFINITION-XHTML",
                   "enum": "ATTRIBUTE-DEFINITION-ENUMERATION"}[kind]
            extra = {"multi_valued": "false"} if kind == "enum" else {}
            ad = _sub(defs, tag, identifier=aid, long_name=label, last_change=now, **extra)
            ref_tag = {"string": "DATATYPE-DEFINITION-STRING-REF", "xhtml": "DATATYPE-DEFINITION-XHTML-REF",
                       "enum": "DATATYPE-DEFINITION-ENUMERATION-REF"}[kind]
            ref = (dt_string if kind == "string" else dt_xhtml if kind == "xhtml" else enum_dt[(t.key, akey)][0])
            _sub(_sub(ad, "TYPE"), ref_tag).text = ref
    link_rows = db.execute(
        select(Link).where(Link.source_id.in_(by_id), Link.target_id.in_(by_id), Link.deleted_at.is_(None),
                           Link.type_key.not_in(structural))
    ).scalars().all() if by_id else []
    for lt_key in sorted({lk.type_key for lk in link_rows}):
        lt = model.link_type(lt_key)
        _sub(spec_types, "SPEC-RELATION-TYPE", identifier=_id("rt", lt_key), long_name=lt.label if lt else lt_key,
             last_change=now)
    spec_type_id = _id("spt", "specification")
    _sub(spec_types, "SPECIFICATION-TYPE", identifier=spec_type_id, long_name="Specification", last_change=now)

    objects = _sub(content, "SPEC-OBJECTS")
    for it in items:
        so = _sub(objects, "SPEC-OBJECT", identifier=_id("so", it.id), long_name=it.key,
                  last_change=it.updated_at.isoformat())
        _sub(_sub(so, "TYPE"), "SPEC-OBJECT-TYPE-REF").text = _id("st", it.type_key)
        values = _sub(so, "VALUES")
        for akey, value in (("_key", it.key), ("_title", it.title), ("_state", it.state or ""),
                            ("_version", it.version_label)):
            _string_value(values, attr_ids[(it.type_key, akey)], value)
        xv = _sub(values, "ATTRIBUTE-VALUE-XHTML")
        _sub(_sub(xv, "DEFINITION"), "ATTRIBUTE-DEFINITION-XHTML-REF").text = attr_ids[(it.type_key, "_description")]
        div = ET.SubElement(_sub(xv, "THE-VALUE"), f"{{{XHTML}}}div")
        for para in (it.description or "").split("\n\n"):
            if para.strip():
                ET.SubElement(div, f"{{{XHTML}}}p").text = para.strip()
        t = model.item_type(it.type_key)
        for f in t.fields if t else []:
            v = it.fields.get(f.key)
            if v is None:
                continue
            if (it.type_key, f.key) in enum_dt:
                ev = _sub(values, "ATTRIBUTE-VALUE-ENUMERATION")
                _sub(_sub(ev, "DEFINITION"), "ATTRIBUTE-DEFINITION-ENUMERATION-REF").text = attr_ids[(it.type_key,
                                                                                                      f.key)]
                vid = enum_dt[(it.type_key, f.key)][1].get(str(v))
                if vid:
                    _sub(_sub(ev, "VALUES"), "ENUM-VALUE-REF").text = vid
            else:
                _string_value(values, attr_ids[(it.type_key, f.key)],
                              ", ".join(map(str, v)) if isinstance(v, list) else str(v))

    relations = _sub(content, "SPEC-RELATIONS")
    for lk in link_rows:
        rel = _sub(relations, "SPEC-RELATION", identifier=_id("rel", lk.id), last_change=lk.created_at.isoformat())
        _sub(_sub(rel, "TYPE"), "SPEC-RELATION-TYPE-REF").text = _id("rt", lk.type_key)
        _sub(_sub(rel, "SOURCE"), "SPEC-OBJECT-REF").text = _id("so", lk.source_id)
        _sub(_sub(rel, "TARGET"), "SPEC-OBJECT-REF").text = _id("so", lk.target_id)

    specs = _sub(content, "SPECIFICATIONS")
    spec = _sub(specs, "SPECIFICATION", identifier=_id("spec", root.id if root else project.id),
                long_name=root.title if root else project.name, last_change=now)
    _sub(_sub(spec, "TYPE"), "SPECIFICATION-TYPE-REF").text = spec_type_id
    children_el = _sub(spec, "CHILDREN")

    def add_children(parent_el: ET.Element, parent_id: uuid.UUID, seen: set[uuid.UUID]) -> None:
        for link, child in links_svc.children(db, by_id.get(parent_id) or root, structural):
            if child.id not in by_id or child.id in seen:
                continue
            h = _sub(parent_el, "SPEC-HIERARCHY", identifier=_id("sh", link.id), last_change=now)
            _sub(_sub(h, "OBJECT"), "SPEC-OBJECT-REF").text = _id("so", child.id)
            sub = _sub(h, "CHILDREN")
            add_children(sub, child.id, seen | {child.id})
            if not len(sub):
                h.remove(sub)

    if root is not None:
        add_children(children_el, root.id, {root.id})
    else:
        for it in items:
            h = _sub(children_el, "SPEC-HIERARCHY", identifier=_id("sh", it.id), last_change=now)
            _sub(_sub(h, "OBJECT"), "SPEC-OBJECT-REF").text = _id("so", it.id)
    return ET.tostring(reqif, encoding="utf-8", xml_declaration=True)
