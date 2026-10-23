"""Customer Word templates for document export.

A template is an ordinary Word file (.docx or .dotx) in the customer's corporate design: page setup, styles,
headers/footers with logo, a cover page. Placeholders anywhere in the body, tables, headers, footers and text
boxes are filled at export:

    {{title}} {{key}} {{version}} {{state}} {{project}} {{project_name}} {{source}} {{variant}} {{date}}
    {{author}} {{product}}

A paragraph holding only ``{{toc}}`` becomes a table of contents, one holding only ``{{content}}`` receives the
document (introduction and items); without it the content is appended at the end. Styles the export needs and the
template lacks (headings, lists, tables) are copied in from the standard layout, so a minimal template works; a
template that defines them gets its own look.
"""

from __future__ import annotations

import copy
import io
import re
import zipfile
from typing import Any

PLACEHOLDER = re.compile(r"\{\{\s*([a-z_]+)\s*\}\}")
KNOWN = ("title", "key", "version", "state", "project", "project_name", "source", "variant", "date", "author",
         "product", "toc", "content")
MAX_TEMPLATE = 10 * 1024 * 1024
MAX_UNPACKED = 80 * 1024 * 1024
DOCX_MAIN = "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
DOTX_MAIN = "application/vnd.openxmlformats-officedocument.wordprocessingml.template.main+xml"
NEEDED_STYLES = (["Title"] + [f"Heading {n}" for n in range(1, 10)]
                 + ["List Bullet", "List Bullet 2", "List Bullet 3", "List Number", "List Number 2", "List Number 3",
                    "List Continue", "List Continue 2", "List Continue 3", "Table Grid", "Light List Accent 1",
                    "Light Grid Accent 1"])


class TemplateError(ValueError):
    pass


def normalize(content: bytes) -> bytes:
    """Check an uploaded template and return it as a .docx (a .dotx gets the document content type)."""
    if len(content) > MAX_TEMPLATE:
        raise TemplateError("The template is larger than 10 MB")
    try:
        zf = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile:
        raise TemplateError("Not a Word file (.docx or .dotx)") from None
    if sum(i.file_size for i in zf.infolist()) > MAX_UNPACKED:
        raise TemplateError("The template unpacks to more than 80 MB")
    names = set(zf.namelist())
    if "[Content_Types].xml" not in names or "word/document.xml" not in names:
        raise TemplateError("Not a Word file (.docx or .dotx)")
    if "word/vbaProject.bin" in names:
        raise TemplateError("Templates with macros (.docm/.dotm) are not accepted")
    types = zf.read("[Content_Types].xml").decode("utf-8")
    if DOTX_MAIN in types:
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dst:
            for info in zf.infolist():
                data = zf.read(info.filename)
                if info.filename == "[Content_Types].xml":
                    data = types.replace(DOTX_MAIN, DOCX_MAIN).encode("utf-8")
                dst.writestr(info, data)
        content = out.getvalue()
    elif DOCX_MAIN not in types:
        raise TemplateError("Not a Word document or template")
    try:
        open_template(content)
    except Exception as exc:  # noqa: BLE001 — anything python-docx cannot read is rejected
        raise TemplateError(f"Word cannot be read: {exc}") from None
    return content


def open_template(content: bytes) -> Any:
    from docx import Document

    return Document(io.BytesIO(content))


def _parts(doc: Any) -> list[Any]:
    """Body plus every header/footer actually defined in the template (linked ones are not created)."""
    out = [doc.element.body]
    for section in doc.sections:
        for hf in (section.header, section.first_page_header, section.even_page_header, section.footer,
                   section.first_page_footer, section.even_page_footer):
            if not hf.is_linked_to_previous:
                out.append(hf._element)
    return out


def _text(p: Any) -> str:
    from docx.oxml.ns import qn

    return "".join(t.text or "" for t in p.iter(qn("w:t")))


def inspect(content: bytes) -> dict[str, Any]:
    """Which placeholders a template uses (shown when it is uploaded)."""
    from docx.oxml.ns import qn

    doc = open_template(content)
    found: list[str] = []
    for part in _parts(doc):
        for p in part.iter(qn("w:p")):
            for m in PLACEHOLDER.finditer(_text(p)):
                if m.group(1) not in found:
                    found.append(m.group(1))
    return {"placeholders": found, "unknown": [f for f in found if f not in KNOWN],
            "has_content": "content" in found, "has_toc": "toc" in found}


def fill(doc: Any, values: dict[str, str]) -> None:
    """Replace known placeholders, also when Word split them over several runs (formatting of the first run wins)."""
    from docx.oxml.ns import qn

    space = "{http://www.w3.org/XML/1998/namespace}space"
    for part in _parts(doc):
        for p in part.iter(qn("w:p")):
            ts = list(p.iter(qn("w:t")))
            full = "".join(t.text or "" for t in ts)
            if "{{" not in full:
                continue
            for m in reversed([m for m in PLACEHOLDER.finditer(full) if m.group(1) in values]):
                start, end = m.span()
                pos, first = 0, True
                for t in ts:
                    txt = t.text or ""
                    a, b = pos, pos + len(txt)
                    pos = b
                    if b <= start or a >= end:
                        continue
                    lo, hi = max(start, a) - a, min(end, b) - a
                    t.text = txt[:lo] + (values[m.group(1)] if first else "") + txt[hi:]
                    t.set(space, "preserve")
                    first = False


def marker(doc: Any, name: str) -> Any | None:
    """The top-level body paragraph that holds only ``{{name}}``."""
    from docx.oxml.ns import qn

    for el in doc.element.body.iterchildren(qn("w:p")):
        m = PLACEHOLDER.fullmatch(_text(el).strip())
        if m and m.group(1) == name:
            return el
    return None


def toc_field(paragraph_el: Any) -> None:
    """Turn a paragraph into a table-of-contents field (Word fills it when the document opens)."""
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    for child in list(paragraph_el):
        if child.tag != qn("w:pPr"):
            paragraph_el.remove(child)
    fld = OxmlElement("w:fldSimple")
    fld.set(qn("w:instr"), 'TOC \\o "1-3" \\h \\z \\u')
    run = OxmlElement("w:r")
    t = OxmlElement("w:t")
    t.text = "Right-click and choose “Update field” to refresh the table of contents."
    run.append(t)
    fld.append(run)
    paragraph_el.append(fld)


def move_before(doc: Any, start: int, anchor: Any) -> None:
    """Move the body blocks appended since ``start`` (body length before) in front of ``anchor``, drop the anchor."""
    body = doc.element.body
    children = list(body)
    tail = children[-1] if children and children[-1].tag.endswith("}sectPr") else None
    new = children[start - (1 if tail is not None else 0):len(children) - (1 if tail is not None else 0)]
    for el in new:
        body.remove(el)
        anchor.addprevious(el)
    anchor.getparent().remove(anchor)


def ensure_styles(doc: Any, names: list[str] | tuple[str, ...] = NEEDED_STYLES) -> list[str]:
    """Copy styles the template lacks from the standard layout (with their list numbering). Returns the names."""
    from docx import Document
    from docx.oxml.ns import qn

    have = {s.name for s in doc.styles}
    missing = [n for n in names if n not in have]
    if not missing:
        return []
    src = Document()
    src_by_name = {s.name: s for s in src.styles}
    src_name_of_id = {s.style_id: s.name for s in src.styles}
    added: list[str] = []

    def target_id(name: str) -> str | None:
        return next((s.style_id for s in doc.styles if s.name == name), None)

    def add(name: str) -> None:
        if name in have or name not in src_by_name:
            return
        el = copy.deepcopy(src_by_name[name].element)
        based = el.find(qn("w:basedOn"))
        if based is not None:
            base_name = src_name_of_id.get(based.get(qn("w:val")))
            if base_name and base_name not in have:
                add(base_name)
            tid = target_id(base_name) if base_name else None
            if tid:
                based.set(qn("w:val"), tid)
            else:
                el.remove(based)
        for tag in ("w:link", "w:next"):  # linked character styles / follow-on styles may not exist here
            node = el.find(qn(tag))
            if node is not None:
                el.remove(node)
        num_id = el.find(f"{qn('w:pPr')}/{qn('w:numPr')}/{qn('w:numId')}")
        if num_id is not None:
            new_id = _copy_numbering(src, doc, num_id.get(qn("w:val")))
            if new_id is None:
                num_id.getparent().getparent().remove(num_id.getparent())
            else:
                num_id.set(qn("w:val"), str(new_id))
        sid = el.get(qn("w:styleId"))
        if sid and any(s.style_id == sid for s in doc.styles):  # same id, other name: keep both
            el.set(qn("w:styleId"), f"{sid}Ariadne")
        doc.styles.element.append(el)
        have.add(name)
        added.append(name)

    for n in missing:
        add(n)
    return added


def _copy_numbering(src: Any, dst: Any, num_id: str) -> int | None:
    from docx.oxml.ns import qn

    s_numbering = src.part.numbering_part.element
    num = next((n for n in s_numbering.findall(qn("w:num")) if n.get(qn("w:numId")) == num_id), None)
    if num is None:
        return None
    abs_id = num.find(qn("w:abstractNumId")).get(qn("w:val"))
    abstract = next((a for a in s_numbering.findall(qn("w:abstractNum"))
                     if a.get(qn("w:abstractNumId")) == abs_id), None)
    if abstract is None:
        return None
    d_numbering = dst.part.numbering_part.element
    abs_ids = [int(a.get(qn("w:abstractNumId"))) for a in d_numbering.findall(qn("w:abstractNum"))]
    num_ids = [int(n.get(qn("w:numId"))) for n in d_numbering.findall(qn("w:num"))]
    new_abs, new_num = max(abs_ids, default=-1) + 1, max(num_ids, default=0) + 1
    a = copy.deepcopy(abstract)
    a.set(qn("w:abstractNumId"), str(new_abs))
    nsid = a.find(qn("w:nsid"))
    if nsid is not None:
        nsid.set(qn("w:val"), f"{(0x2A1D0000 + new_abs) & 0xFFFFFFFF:08X}")
    first_num = d_numbering.find(qn("w:num"))
    if first_num is not None:
        first_num.addprevious(a)  # schema: all abstractNum before the num elements
    else:
        d_numbering.append(a)
    n = copy.deepcopy(num)
    n.set(qn("w:numId"), str(new_num))
    for override in n.findall(qn("w:lvlOverride")):
        n.remove(override)
    n.find(qn("w:abstractNumId")).set(qn("w:val"), str(new_abs))
    d_numbering.append(n)
    return new_num


def sample_template(product: str) -> bytes:
    """A starting point for customers: cover page, header/footer, table of contents and content marker."""
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Pt, RGBColor

    doc = Document()
    brand = RGBColor(0x0E, 0x6E, 0x76)
    doc.styles["Normal"].font.name = "Calibri"
    doc.styles["Normal"].font.size = Pt(10.5)
    for n, size in ((1, 15), (2, 13), (3, 11.5)):
        st = doc.styles[f"Heading {n}"]
        st.font.color.rgb = brand
        st.font.size = Pt(size)
    section = doc.sections[0]
    section.different_first_page_header_footer = True
    hp = section.header.paragraphs[0]
    hp.text = "{{project_name}} — {{title}}"
    hp.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    fp = section.footer.paragraphs[0]
    fp.text = "{{key}} · Version {{version}} · {{state}} · {{date}} · Page "
    fld = OxmlElement("w:fldSimple")
    fld.set(qn("w:instr"), "PAGE")
    r = OxmlElement("w:r")
    t = OxmlElement("w:t")
    t.text = "1"
    r.append(t)
    fld.append(r)
    fp._p.append(fld)
    fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    cover = doc.add_paragraph()
    cover.paragraph_format.space_before = Pt(120)
    run = cover.add_run("{{title}}")
    run.bold, run.font.size, run.font.color.rgb = True, Pt(28), brand
    sub = doc.add_paragraph()
    sub.add_run("{{key}} · Version {{version}} · {{state}}").font.size = Pt(14)
    table = doc.add_table(rows=0, cols=2)
    table.style = doc.styles["Light List Accent 1"]
    for label, value in (("Project", "{{project}} — {{project_name}}"), ("Content", "{{source}}"),
                         ("Variant", "{{variant}}"), ("Exported", "{{date}} by {{author}}")):
        cells = table.add_row().cells
        cells[0].text, cells[1].text = label, value
    note = doc.add_paragraph()
    nr = note.add_run(f"Template for {product} document export — replace this page with your corporate cover. "
                      "Placeholders in double braces are filled when exporting.")
    nr.italic, nr.font.size = True, Pt(9)
    doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)
    doc.add_paragraph("Contents", style="Heading 1")
    doc.add_paragraph("{{toc}}")
    doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)
    doc.add_paragraph("{{content}}")
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()
