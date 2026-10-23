"""Sparx Systems Enterprise Architect.

Import from EA 16+ project files (``.qea``/``.qeax`` — SQLite) or from EA's XMI 2.1 export: elements (requirements,
blocks, components, activities, interfaces, use cases, test cases, …) with notes, alias, status, version, stereotype
and tagged values, the package hierarchy, and connectors (satisfy, deriveReqt, verify, trace, refine, realisation,
aggregation/composition, dependency). Elements are identified by their EA GUID.

Export in EA's XMI 2.1 structure (UML part plus the "Enterprise Architect" extension with element types, notes,
stereotypes, tagged values and connectors), and write-back into a copy of a ``.qea`` model: elements known by GUID
are updated, new ones are created in a chosen package (rows cloned from existing ones, so every EA column keeps a
valid value), connectors are added between elements of the model.
"""

from __future__ import annotations

import contextlib
import os
import re
import sqlite3
import tempfile
import time
import uuid
from datetime import UTC, datetime
from typing import Any
from xml.sax.saxutils import quoteattr

from lxml import etree
from sqlalchemy import select
from sqlalchemy.orm import Session

from almlight.core import richtext
from almlight.core.config import get_settings
from almlight.core.errors import ValidationFailed
from almlight.modules.connectors.base import ExtModel, ExtObject, ExtRelation, Suggestion
from almlight.modules.integrations.models import ExternalRef
from almlight.modules.items.models import Item
from almlight.modules.links.models import Link
from almlight.modules.projects.models import Project

SYSTEM = "ea"
NS = uuid.UUID("6f0c2b1e-0a6c-4d1b-9a43-3c3e5bba0e11")  # deterministic EA GUIDs for elements exported from Ariadne
SKIP_TYPES = {"package", "text", "note", "boundary", "diagramframe", "constraint", "artifact", "gui element"}


def guid_for(item_id: uuid.UUID) -> str:
    return "{" + str(uuid.uuid5(NS, str(item_id))).upper() + "}"


def _guid_from_xmi(xid: str) -> str:
    hexes = r"_([0-9A-Fa-f]{8})_([0-9A-Fa-f]{4})_([0-9A-Fa-f]{4})_([0-9A-Fa-f]{4})_([0-9A-Fa-f]{12})"
    m = re.fullmatch(r"EA(?:ID|PK)" + hexes, xid)
    return "{" + "-".join(m.groups()).upper() + "}" if m else xid


def _xmi_id(guid: str, prefix: str = "EAID") -> str:
    return f"{prefix}_" + guid.strip("{}").replace("-", "_").upper()


def kind_of(obj_type: str, stereotype: str | None) -> str:
    st = (stereotype or "").split("::")[-1].strip()
    return f"{obj_type}«{st}»" if st else obj_type


def suggestion(project: Project, model: ExtModel) -> Suggestion:
    """Mapping defaults from EA element types/stereotypes and connector types/stereotypes."""
    has = lambda key: project.model.item_type(key) is not None  # noqa: E731
    s = Suggestion()
    for kind in {o.kind for o in model.objects}:
        k = kind.lower()
        if "requirement" in k:
            choice = "stakeholder_requirement" if "stakeholder" in k or "business" in k else "system_requirement"
        elif "testcase" in k.replace(" ", "") or "«test" in k:
            choice = "test_case"
        elif any(w in k for w in ("block", "component", "part", "node", "device", "subsystem")) or k == "class":
            choice = "system_element"
        elif any(w in k for w in ("activity", "action", "function")):
            choice = "function"
        elif "interface" in k or k.startswith("port"):
            choice = "interface"
        elif "usecase" in k.replace(" ", ""):
            choice = "stakeholder_requirement"
        elif "issue" in k or "defect" in k or "bug" in k:
            choice = "problem_report"
        elif "change" in k:
            choice = "change_request"
        elif "hazard" in k:
            choice = "hazard"
        elif "risk" in k:
            choice = "risk"
        elif "feature" in k:
            choice = "feature"
        else:
            choice = None
        s.types[kind] = choice if choice and has(choice) else None
    for kind in {r.kind for r in model.relations}:
        k = kind.lower()
        if "satisfy" in k:
            s.relations[kind] = "satisfies"
        elif "derive" in k:
            s.relations[kind] = "derives_from"
        elif "verify" in k:
            s.relations[kind] = "verifies"
        elif "aggregation" in k or "composition" in k:
            s.relations[kind] = "contains:reverse"
        elif "realisation" in k or "realization" in k:
            s.relations[kind] = "realizes"
        elif any(w in k for w in ("trace", "refine", "dependency", "abstraction")):
            s.relations[kind] = "relates_to"
        else:
            s.relations[kind] = None
    return s


# --- parsing --------------------------------------------------------------------------------------------------


def parse(filename: str, content: bytes) -> ExtModel:
    low = filename.lower()
    if content[:16] == b"SQLite format 3\x00":
        return parse_qea(filename, content)
    if low.endswith((".eap", ".eapx", ".feap")):
        raise ValidationFailed("This EA file format needs Microsoft Access or Firebird. In EA, save the model as .qea "
                               "(File → Save Project As) or export the package as XMI 2.1")
    head = content[:2000].lstrip()
    if head.startswith(b"<?xml") or b"<xmi:XMI" in head or b"XMI" in head[:500]:
        return parse_xmi(filename, content)
    raise ValidationFailed("Upload an Enterprise Architect model (.qea / .qeax) or an XMI 2.1 export (.xmi / .xml)")


SQLITE_SECONDS = 120
SQLITE_MAX_ROWS = 1_000_000


def _open_sqlite(path: str, read_only: bool) -> sqlite3.Connection:
    """Uploaded model files are untrusted: no trusted schema, a time limit and, when writing, a size limit."""
    con = sqlite3.connect(f"file:{path}?mode=ro" if read_only else path, uri=read_only)
    con.row_factory = sqlite3.Row
    deadline = time.monotonic() + SQLITE_SECONDS
    con.set_progress_handler(lambda: int(time.monotonic() > deadline), 10_000)
    con.execute("PRAGMA trusted_schema = OFF")
    if not read_only:
        pages = int(con.execute("PRAGMA page_count").fetchone()[0])
        con.execute(f"PRAGMA max_page_count = {pages * 2 + 25_000}")
    return con


def _q(name: str) -> str:
    """Quote a column name read from the uploaded file."""
    return '"' + name.replace('"', '""') + '"'


def _sqlite_failed(exc: sqlite3.Error) -> ValidationFailed:
    if "interrupted" in str(exc):
        return ValidationFailed("The model file takes too long to process")
    return ValidationFailed(f"The model file cannot be processed: {exc}")


def _rows(con: sqlite3.Connection, sql: str, *args: Any) -> list[sqlite3.Row]:
    """Rows of an optional table (missing tables or columns give no rows)."""
    try:
        rows = con.execute(sql, args).fetchmany(SQLITE_MAX_ROWS + 1)
    except sqlite3.Error as exc:
        if "interrupted" in str(exc):
            raise _sqlite_failed(exc) from None
        return []
    if len(rows) > SQLITE_MAX_ROWS:
        raise ValidationFailed("The model file is too large")
    return rows


def _notes(raw: str | None) -> tuple[str, bool]:
    """EA notes use a small HTML subset (<b>, <i>, <u>, <font>, <ol>/<ul>/<li>, <a>) and newlines."""
    text = (raw or "").replace("\r\n", "\n")
    if re.search(r"</?(b|i|u|font|ol|ul|li|a)\b", text, re.I):
        html = re.sub(r"</?font[^>]*>", "", text, flags=re.I)
        html = "".join(f"<p>{line}</p>" if line.strip() and not re.match(r"\s*</?(ol|ul|li)", line) else line
                       for line in html.split("\n"))
        return html, True
    return text, False


def parse_qea(filename: str, content: bytes) -> ExtModel:
    tmp_dir = get_settings().data_dir / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    fd, path = tempfile.mkstemp(suffix=".qea", dir=tmp_dir)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(content)
        con = _open_sqlite(path, read_only=True)
        if not _rows(con, "SELECT name FROM sqlite_master WHERE type='table' AND name='t_object'"):
            raise ValidationFailed("This SQLite file is not an Enterprise Architect model (no t_object table)")
        return _read_model(con, filename)
    except sqlite3.Error as exc:
        raise _sqlite_failed(exc) from None
    finally:
        with contextlib.suppress(Exception):
            con.close()  # type: ignore[possibly-undefined]
        os.unlink(path)


def _read_model(con: sqlite3.Connection, filename: str) -> ExtModel:
    model = ExtModel(system=SYSTEM, source=filename)
    pkgs = {r["Package_ID"]: r for r in _rows(con, "SELECT Package_ID, Name, Parent_ID, ea_guid FROM t_package")}

    def pkg_path(pid: int) -> list[str]:
        out, seen = [], set()
        while pid in pkgs and pid not in seen and pkgs[pid]["Parent_ID"]:
            seen.add(pid)
            out.append(pkgs[pid]["Name"])
            pid = pkgs[pid]["Parent_ID"]
        return list(reversed(out))

    for pid, r in pkgs.items():
        model.packages.append({"id": r["ea_guid"], "name": r["Name"], "path": " / ".join(pkg_path(pid)) or r["Name"]})
    tags: dict[int, dict[str, str]] = {}
    for r in _rows(con, "SELECT Object_ID, Property, Value, Notes FROM t_objectproperties"):
        value = r["Notes"] if (r["Value"] or "") == "<memo>" else r["Value"]
        tags.setdefault(r["Object_ID"], {})[r["Property"]] = value or ""
    cols = {c[1] for c in con.execute("PRAGMA table_info(t_object)").fetchall()}
    extra = [c for c in ("Status", "Version", "Author", "Phase", "Complexity", "Alias") if c in cols]
    ids: dict[int, str] = {}
    for r in _rows(con, f"SELECT Object_ID, Object_Type, Name, Note, Package_ID, Stereotype, ea_guid, "
                        f"{', '.join(extra) or 'NULL'} FROM t_object"):
        if (r["Object_Type"] or "").lower() in SKIP_TYPES:
            continue
        ids[r["Object_ID"]] = r["ea_guid"]
        fields = {c.lower() if c != "Complexity" else "difficulty": r[c] for c in extra if r[c] not in (None, "")}
        fields.update(tags.get(r["Object_ID"], {}))
        text, html = _notes(r["Note"])
        model.objects.append(ExtObject(ext_id=r["ea_guid"], kind=kind_of(r["Object_Type"], r["Stereotype"]),
                                       name=r["Name"] or r["ea_guid"], text=text, html=html, fields=fields,
                                       parent=pkgs[r["Package_ID"]]["ea_guid"] if r["Package_ID"] in pkgs else None,
                                       path=pkg_path(r["Package_ID"])))
    for r in _rows(con, "SELECT Connector_ID, Connector_Type, Stereotype, SubType, Start_Object_ID, End_Object_ID, "
                        "ea_guid FROM t_connector"):
        if r["Start_Object_ID"] not in ids or r["End_Object_ID"] not in ids:
            continue
        ctype = "Composition" if r["Connector_Type"] == "Aggregation" and (r["SubType"] or "") == "Strong" \
            else r["Connector_Type"]
        model.relations.append(ExtRelation(kind=kind_of(ctype, r["Stereotype"]), source=ids[r["Start_Object_ID"]],
                                           target=ids[r["End_Object_ID"]], ext_id=r["ea_guid"]))
    return model


XMI_NS = "http://schema.omg.org/spec/XMI/2.1"
XMI_NS_ALT = ("http://www.omg.org/spec/XMI/20131001", "http://www.omg.org/XMI", "http://schema.omg.org/spec/XMI/2.1")


def parse_xmi(filename: str, content: bytes) -> ExtModel:
    parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False, remove_comments=True)
    try:
        root = etree.fromstring(content, parser)
    except etree.XMLSyntaxError as exc:
        raise ValidationFailed(f"Not a valid XMI file: {exc}") from None
    xmi = next((ns for ns in XMI_NS_ALT if root.nsmap and ns in root.nsmap.values()), XMI_NS)
    a_id, a_type, a_idref = f"{{{xmi}}}id", f"{{{xmi}}}type", f"{{{xmi}}}idref"
    model = ExtModel(system=SYSTEM, source=filename)
    packages: dict[str, tuple[str, str | None]] = {}   # xmi id -> (name, parent id)
    elements: dict[str, dict[str, Any]] = {}

    def walk(node: Any, parent_pkg: str | None) -> None:
        for child in node:
            if not isinstance(child.tag, str) or etree.QName(child).localname != "packagedElement":
                continue
            xtype = (child.get(a_type) or "").split(":")[-1]
            xid = child.get(a_id)
            if not xid:
                continue
            if xtype in ("Package", "Model"):
                packages[xid] = (child.get("name") or "", parent_pkg)
                walk(child, xid)
            elif xtype in ("Abstraction", "Dependency", "Realization", "Usage", "Association", "InformationFlow"):
                elements[xid] = {"relation": True, "type": xtype, "client": child.get("client"),
                                 "supplier": child.get("supplier")}
            else:
                body = " ".join(c.text or "" for c in child.iter() if isinstance(c.tag, str)
                                and etree.QName(c).localname == "body")
                elements[xid] = {"type": xtype, "name": child.get("name") or "", "notes": body, "package": parent_pkg}
                walk(child, parent_pkg)

    model_el = next((c for c in root if isinstance(c.tag, str) and etree.QName(c).localname == "Model"), root)
    walk(model_el, None)
    ext = next((c for c in root.iter() if isinstance(c.tag, str) and etree.QName(c).localname == "Extension"
                and c.get("extender") == "Enterprise Architect"), None)
    connectors: list[dict[str, Any]] = []
    if ext is not None:
        for el in ext.iter():
            if not isinstance(el.tag, str):
                continue
            name = etree.QName(el).localname
            if name == "element" and el.get(a_idref) in elements:
                info = elements[el.get(a_idref)]
                info["type"] = (el.get(a_type) or info["type"]).split(":")[-1]
                for sub in el:
                    if not isinstance(sub.tag, str):
                        continue
                    sn = etree.QName(sub).localname
                    if sn == "properties":
                        info["notes"] = sub.get("documentation") or info.get("notes", "")
                        info["stereotype"] = sub.get("stereotype")
                        for k in ("alias", "status"):
                            if sub.get(k):
                                info.setdefault("fields", {})[k] = sub.get(k)
                    elif sn == "project":
                        for k in ("version", "author", "phase", "status"):
                            if sub.get(k):
                                info.setdefault("fields", {})[k] = sub.get(k)
                    elif sn == "tags":
                        for tag in sub:
                            if isinstance(tag.tag, str) and tag.get("name"):
                                info.setdefault("fields", {})[tag.get("name")] = tag.get("value") or ""
            elif name == "connector":
                c: dict[str, Any] = {"id": el.get(a_idref)}
                for sub in el:
                    if not isinstance(sub.tag, str):
                        continue
                    sn = etree.QName(sub).localname
                    if sn in ("source", "target"):
                        c[sn] = sub.get(a_idref)
                    elif sn == "properties":
                        c["type"], c["stereotype"] = sub.get("ea_type"), sub.get("stereotype")
                        c["subtype"] = sub.get("subtype")
                connectors.append(c)
    # SysML stereotype applications (<SysML:Requirement base_Class=".." id=".." text="..">)
    for el in root:
        if isinstance(el.tag, str) and (base := next((v for k, v in el.attrib.items() if k.startswith("base_")), None)):
            info = elements.get(base)
            if info is not None and not info.get("relation"):
                info.setdefault("stereotype", etree.QName(el).localname[:1].lower() + etree.QName(el).localname[1:])
                if el.get("text") and not info.get("notes"):
                    info["notes"] = el.get("text")
                if el.get("id"):
                    info.setdefault("fields", {})["id"] = el.get("id")

    def path(pid: str | None) -> list[str]:
        out, seen = [], set()
        while pid in packages and pid not in seen:
            seen.add(pid)
            name, parent = packages[pid]
            if parent is not None:
                out.append(name)
            pid = parent
        return list(reversed(out))

    for xid, (name, _parent) in packages.items():
        model.packages.append({"id": _guid_from_xmi(xid), "name": name, "path": " / ".join(path(xid)) or name})
    for xid, info in elements.items():
        if info.get("relation") or info["type"].lower() in SKIP_TYPES:
            continue
        text, html = _notes(info.get("notes"))
        model.objects.append(ExtObject(ext_id=_guid_from_xmi(xid), kind=kind_of(info["type"], info.get("stereotype")),
                                       name=info["name"] or xid, text=text, html=html, fields=info.get("fields", {}),
                                       parent=_guid_from_xmi(info["package"]) if info.get("package") else None,
                                       path=path(info.get("package"))))
    known = {o.ext_id for o in model.objects}
    seen_rel = set()
    for c in connectors:
        if c.get("source") and c.get("target"):
            ctype = "Composition" if c.get("type") == "Aggregation" and c.get("subtype") == "Strong" else c.get("type")
            rel = ExtRelation(kind=kind_of(ctype or "Dependency", c.get("stereotype")),
                              source=_guid_from_xmi(c["source"]), target=_guid_from_xmi(c["target"]),
                              ext_id=_guid_from_xmi(c["id"]) if c.get("id") else None)
            if rel.source in known and rel.target in known:
                model.relations.append(rel)
                seen_rel.add(c.get("id"))
    for xid, info in elements.items():  # plain UML relationships without EA extension
        if info.get("relation") and xid not in seen_rel and info.get("client") and info.get("supplier"):
            src, tgt = _guid_from_xmi(info["client"]), _guid_from_xmi(info["supplier"])
            if src in known and tgt in known:
                model.relations.append(ExtRelation(kind=info["type"], source=src, target=tgt,
                                                   ext_id=_guid_from_xmi(xid)))
    return model


# --- export ---------------------------------------------------------------------------------------------------

# Ariadne item type -> (EA element type, UML type in the model part, stereotype)
TYPE_OUT = {
    "stakeholder_requirement": ("Requirement", "Class", ""), "system_requirement": ("Requirement", "Class", ""),
    "element_requirement": ("Requirement", "Class", ""), "system_element": ("Class", "Class", "block"),
    "function": ("Activity", "Activity", ""), "interface": ("Interface", "Interface", ""),
    "test_case": ("Class", "Class", "testCase"), "risk": ("Issue", "Class", ""), "hazard": ("Issue", "Class", "hazard"),
    "feature": ("Feature", "Class", ""), "problem_report": ("Issue", "Class", ""),
    "change_request": ("Change", "Class", ""),
}
# Ariadne link type -> (EA connector type, UML type, stereotype, reverse)
LINK_OUT = {
    "satisfies": ("Abstraction", "Abstraction", "satisfy", False),
    "derives_from": ("Abstraction", "Abstraction", "deriveReqt", False),
    "verifies": ("Abstraction", "Abstraction", "verify", False), "realizes": ("Realisation", "Realization", "", False),
    "relates_to": ("Dependency", "Dependency", "trace", False), "contains": ("Aggregation", "Association", "", True),
}
STATUS = {"released": "Approved", "review": "Proposed", "draft": "Proposed", "obsolete": "Obsolete",
          "open": "Proposed", "in_progress": "Implemented", "closed": "Validated"}


def _ea_guids(db: Session, project: Project, items: list[Item]) -> dict[uuid.UUID, str]:
    refs = dict(db.execute(select(ExternalRef.item_id, ExternalRef.external_id).where(
        ExternalRef.project_id == project.id, ExternalRef.system == SYSTEM, ExternalRef.kind == "element",
        ExternalRef.item_id.in_([i.id for i in items]))).all()) if items else {}
    return {i.id: refs.get(i.id) or guid_for(i.id) for i in items}


def _status(project: Project, item: Item) -> str:
    wf = project.model.workflow_for(item.type_key)
    st = wf.state(item.state) if wf else None
    return STATUS.get(st.category if st else "", "Proposed")


def _links(db: Session, items: list[Item]) -> list[Link]:
    ids = [i.id for i in items]
    if not ids:
        return []
    return db.execute(select(Link).where(Link.source_id.in_(ids), Link.target_id.in_(ids),
                                         Link.deleted_at.is_(None))).scalars().all()


def export_xmi(db: Session, project: Project, items: list[Item]) -> bytes:
    items = [i for i in items if i.type_key in TYPE_OUT]
    guids = _ea_guids(db, project, items)
    root_guid = "{" + str(uuid.uuid5(NS, f"package:{project.id}")).upper() + "}"
    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
    by_type: dict[str, list[Item]] = {}
    for it in items:
        by_type.setdefault(it.type_key, []).append(it)
    pkg_of = {t: "{" + str(uuid.uuid5(NS, f"package:{project.id}:{t}")).upper() + "}" for t in by_type}
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<xmi:XMI xmi:version="2.1" xmlns:uml="http://schema.omg.org/spec/UML/2.1" '
           'xmlns:xmi="http://schema.omg.org/spec/XMI/2.1">',
           '<xmi:Documentation exporter="Enterprise Architect" exporterVersion="6.5" exporterID="1628"/>',
           '<uml:Model xmi:type="uml:Model" name="EA_Model" visibility="public">',
           f'<packagedElement xmi:type="uml:Package" xmi:id="{_xmi_id(root_guid, "EAPK")}" '
           f'name={quoteattr(f"Ariadne {project.key}")} visibility="public">']
    for t, its in by_type.items():
        label = project.model.item_type(t).label  # type: ignore[union-attr]
        out.append(f'<packagedElement xmi:type="uml:Package" xmi:id="{_xmi_id(pkg_of[t], "EAPK")}" '
                   f'name={quoteattr(label)} visibility="public">')
        for it in its:
            out.append(f'<packagedElement xmi:type="uml:{TYPE_OUT[t][1]}" xmi:id="{_xmi_id(guids[it.id])}" '
                       f'name={quoteattr(it.title)} visibility="public"/>')
        out.append("</packagedElement>")
    links = [lk for lk in _links(db, items) if lk.type_key in LINK_OUT]
    item_by_id = {i.id: i for i in items}
    conn_ids = {lk.id: "{" + str(uuid.uuid5(NS, f"link:{lk.id}")).upper() + "}" for lk in links}
    for lk in links:
        _, uml, _, reverse = LINK_OUT[lk.type_key]
        src, tgt = (lk.target_id, lk.source_id) if reverse else (lk.source_id, lk.target_id)
        if uml != "Association":
            out.append(f'<packagedElement xmi:type="uml:{uml}" xmi:id="{_xmi_id(conn_ids[lk.id])}" visibility="public" '
                       f'client="{_xmi_id(guids[src])}" supplier="{_xmi_id(guids[tgt])}"/>')
    out += ["</packagedElement>", "</uml:Model>", '<xmi:Extension extender="Enterprise Architect" extenderID="6.5">',
            "<elements>"]
    for t, its in by_type.items():
        ea_type, _, stereo = TYPE_OUT[t]
        for it in its:
            xid = _xmi_id(guids[it.id])
            notes = richtext.to_text(it.description or "")
            out.append(f'<element xmi:idref="{xid}" xmi:type="uml:{ea_type}" name={quoteattr(it.title)} '
                       'scope="public">')
            out.append(f'<model package="{_xmi_id(pkg_of[t], "EAPK")}" tpos="0" ea_eleType="element"/>')
            out.append(f'<properties documentation={quoteattr(notes)} isSpecification="false" sType="{ea_type}" '
                       f'nType="0" scope="public" stereotype="{stereo}" alias={quoteattr(it.key)} '
                       f'status="{_status(project, it)}"/>')
            out.append(f'<project author="Ariadne" version="{it.version_label}" phase="1.0" created="{now}" '
                       f'modified="{now}" complexity="1" status="{_status(project, it)}"/>')
            out.append("<tags>")
            tags = {"Ariadne key": it.key, "Ariadne state": it.state or ""}
            for f in project.model.item_type(t).fields:  # type: ignore[union-attr]
                v = it.fields.get(f.key)
                if v not in (None, "", []) and f.type not in ("text", "steps"):
                    tags[f.label] = ", ".join(map(str, v)) if isinstance(v, list) else str(v)
            for k, v in tags.items():
                tid = _xmi_id("{" + str(uuid.uuid5(NS, f"tag:{it.id}:{k}")).upper() + "}")
                out.append(f'<tag xmi:id="{tid}" name={quoteattr(k)} value={quoteattr(v)} modelElement="{xid}"/>')
            out.append("</tags></element>")
    out.append("</elements><connectors>")
    for lk in links:
        ea_type, _, stereo, reverse = LINK_OUT[lk.type_key]
        src, tgt = (lk.target_id, lk.source_id) if reverse else (lk.source_id, lk.target_id)
        out.append(f'<connector xmi:idref="{_xmi_id(conn_ids[lk.id])}">'
                   f'<source xmi:idref="{_xmi_id(guids[src])}"><model type="{TYPE_OUT[item_by_id[src].type_key][0]}" '
                   f'name={quoteattr(item_by_id[src].title)}/></source>'
                   f'<target xmi:idref="{_xmi_id(guids[tgt])}"><model type="{TYPE_OUT[item_by_id[tgt].type_key][0]}" '
                   f'name={quoteattr(item_by_id[tgt].title)}/></target>'
                   f'<properties ea_type="{ea_type}" stereotype="{stereo}" direction="Source -&gt; Destination"'
                   f'{" subtype=" + chr(34) + "Strong" + chr(34) if ea_type == "Aggregation" else ""}/></connector>')
    out += ["</connectors>", "</xmi:Extension>", "</xmi:XMI>"]
    return "\n".join(out).encode("utf-8")


def writeback_qea(db: Session, project: Project, content: bytes, items: list[Item],
                  package_guid: str) -> tuple[bytes, dict[str, int]]:
    """Update and add elements (and connectors) in a copy of the uploaded EA model; returns the new file."""
    if content[:16] != b"SQLite format 3\x00":
        raise ValidationFailed("Write-back needs an EA 16+ model file (.qea / .qeax)")
    items = [i for i in items if i.type_key in TYPE_OUT]
    tmp_dir = get_settings().data_dir / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    fd, path = tempfile.mkstemp(suffix=".qea", dir=tmp_dir)
    counts = {"updated": 0, "created": 0, "connectors": 0}
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(content)
        con = _open_sqlite(path, read_only=False)
        if not _rows(con, "SELECT name FROM sqlite_master WHERE type='table' AND name='t_object'"):
            raise ValidationFailed("This SQLite file is not an Enterprise Architect model (no t_object table)")
        pkg = con.execute("SELECT Package_ID FROM t_package WHERE ea_guid = ?", (package_guid,)).fetchone()
        if pkg is None:
            raise ValidationFailed("The target package does not exist in this model")
        guids = _ea_guids(db, project, items)
        now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
        cols = [c[1] for c in con.execute("PRAGMA table_info(t_object)").fetchall()]
        object_id: dict[uuid.UUID, int] = {}
        for it in items:
            ea_type, _, stereo = TYPE_OUT[it.type_key]
            notes = richtext.to_text(it.description or "")
            row = con.execute("SELECT Object_ID FROM t_object WHERE ea_guid = ?", (guids[it.id],)).fetchone()
            values = {"Name": it.title, "Note": notes, "Alias": it.key, "Version": it.version_label,
                      "Status": _status(project, it), "ModifiedDate": now}
            if row is not None:
                sets = ", ".join(f"{_q(k)} = ?" for k in values if k in cols)
                con.execute(f"UPDATE t_object SET {sets} WHERE Object_ID = ?",
                            [v for k, v in values.items() if k in cols] + [row["Object_ID"]])
                object_id[it.id] = row["Object_ID"]
                counts["updated"] += 1
                continue
            template = con.execute("SELECT * FROM t_object WHERE Object_Type = ? LIMIT 1", (ea_type,)).fetchone() or \
                con.execute("SELECT * FROM t_object WHERE Object_Type NOT IN ('Package', 'Text', 'Note') "
                            "LIMIT 1").fetchone()
            new = dict(template) if template is not None else {}
            new.update({"Object_Type": ea_type, "Package_ID": pkg["Package_ID"], "Stereotype": stereo or None,
                        "ea_guid": guids[it.id], "Author": "Ariadne", "CreatedDate": now, "ParentID": 0, "TPos": 0,
                        "Classifier": 0, "Classifier_guid": None, "PDATA1": None, "PDATA2": None, "PDATA3": None,
                        "PDATA4": None, "PDATA5": None, "Diagram_ID": 0, **values})
            new.pop("Object_ID", None)
            keys = [k for k in new if k in cols]
            marks = ", ".join("?" for _ in keys)
            cur = con.execute(f"INSERT INTO t_object ({', '.join(map(_q, keys))}) VALUES ({marks})",
                              [new[k] for k in keys])
            object_id[it.id] = cur.lastrowid  # type: ignore[assignment]
            con.execute("INSERT INTO t_objectproperties (Object_ID, Property, Value, ea_guid) VALUES (?, ?, ?, ?)",
                        (cur.lastrowid, "Ariadne key", it.key, "{" + str(uuid.uuid4()).upper() + "}"))
            counts["created"] += 1
        ccols = [c[1] for c in con.execute("PRAGMA table_info(t_connector)").fetchall()]
        template = con.execute("SELECT * FROM t_connector LIMIT 1").fetchone()
        for lk in _links(db, items):
            if lk.type_key not in LINK_OUT or lk.source_id not in object_id or lk.target_id not in object_id:
                continue
            ea_type, _, stereo, reverse = LINK_OUT[lk.type_key]
            src, tgt = (lk.target_id, lk.source_id) if reverse else (lk.source_id, lk.target_id)
            exists = con.execute("SELECT 1 FROM t_connector WHERE Start_Object_ID = ? AND End_Object_ID = ? AND "
                                 "Connector_Type = ?", (object_id[src], object_id[tgt], ea_type)).fetchone()
            if exists:
                continue
            new = dict(template) if template is not None else {}
            new.update({"Connector_Type": ea_type, "Stereotype": stereo or None, "Start_Object_ID": object_id[src],
                        "End_Object_ID": object_id[tgt], "Direction": "Source -> Destination", "Name": None,
                        "SubType": "Strong" if ea_type == "Aggregation" else None,
                        "ea_guid": "{" + str(uuid.uuid5(NS, f"link:{lk.id}")).upper() + "}"})
            new.pop("Connector_ID", None)
            keys = [k for k in new if k in ccols]
            marks = ", ".join("?" for _ in keys)
            con.execute(f"INSERT INTO t_connector ({', '.join(map(_q, keys))}) VALUES ({marks})",
                        [new[k] for k in keys])
            counts["connectors"] += 1
        con.commit()
        con.close()
        with open(path, "rb") as fh:
            return fh.read(), counts
    except sqlite3.Error as exc:
        raise _sqlite_failed(exc) from None
    finally:
        with contextlib.suppress(Exception):
            con.close()  # type: ignore[possibly-undefined]
        os.unlink(path)


def own_id(item_id: uuid.UUID) -> str:
    return guid_for(item_id)
