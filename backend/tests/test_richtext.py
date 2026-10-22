"""Rich text: canonical HTML, sanitising, conversions, embedded images and the rich round trips (Word, ReqIF,
spreadsheet, archive)."""

import base64
import io
import json
import zipfile

import pytest
from conftest import new_item
from docx import Document
from docx.oxml.ns import qn
from PIL import Image

from almlight.core import richtext as rt


def png(color=(14, 110, 118), size=(120, 60)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    return buf.getvalue()


# --- the model ------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("html", [
    '<p>Hello <strong><em>world</em></strong> and <a target="_blank" rel="x" href="https://x.org">link</a></p>',
    '<ul><li><p>a</p></li><li><p>b</p><ol start="1"><li><p>c</p></li></ol></li></ul>',
    '<table style="min-width:50px"><colgroup><col></colgroup><tbody><tr><th colspan="1"><p>H</p></th>'
    '<td colspan="2"><p>x</p></td></tr></tbody></table>',
    '<pre><code class="language-js">a &lt; b\nc</code></pre><p style="text-align: center">mid</p>',
    'text <b>bold</b><div>block</div>tail',
    '<p><span data-type="item-ref" data-key="SYS-1">SYS-1</span> ref</p>',
])
def test_canonical_is_idempotent(html):
    c = rt.canonical(html)
    assert c and rt.canonical(c) == c


def test_canonical_normalises_editor_output():
    tiptap = ('<p>A <em><strong>b</strong></em></p><ul><li><p>x</p></li></ul>'
              '<table style="min-width: 25px"><colgroup><col style="min-width: 25px"></colgroup><tbody><tr>'
              '<th colspan="1" rowspan="1"><p>H</p></th></tr></tbody></table>')
    markdown = rt.markdown_to_html("A ***b***\n\n- x\n\n| H |\n|---|")
    assert rt.canonical(tiptap) == markdown  # same content, same bytes — whatever produced it


def test_sanitising_removes_active_content():
    evil = ('<p onclick="x()">Hi<script>alert(1)</script><img src="javascript:alert(1)" onerror="x">'
            '<a href="javascript:alert(2)">bad</a><a href="https://ok.org" onmouseover="y">ok</a>'
            '<iframe src="https://evil"></iframe><img src="https://tracker.example/pixel.png"></p>'
            '<style>p{color:red}</style><svg><script>1</script></svg><object data="x"></object>')
    out = rt.canonical(evil)
    for bad in ("script", "onclick", "onerror", "onmouseover", "javascript:", "iframe", "style>", "svg", "object",
                "tracker"):
        assert bad not in out
    assert out == '<p>Hibad<a href="https://ok.org">ok</a></p>'


def test_markdown_and_plain_text_inputs():
    assert rt.normalize_input("**x** y") == "<p><strong>x</strong> y</p>"
    assert rt.normalize_input("line1\nline2\n\n- a\n- b") == "<p>line1 line2</p><ul><li><p>a</p></li><li><p>b</p></li></ul>"
    assert rt.plain_to_html("a < b\nc") == "<p>a &lt; b<br>c</p>"
    assert rt.normalize_input("") == "" and rt.normalize_input("<p> </p>") == ""


def test_text_markdown_and_diff_outputs():
    sha = "b" * 64
    html = rt.canonical(f'<h2>Head</h2><p>See <strong>bold</strong>, <a href="https://x.org">link</a> and '
                        f'<span data-type="item-ref" data-key="SYS-1">SYS-1</span>.</p><ul><li><p>a</p></li></ul>'
                        f'<img src="/api/v1/images/{sha}" alt="chart"><table><tbody><tr><th><p>H</p></th></tr>'
                        f'<tr><td><p>1</p></td></tr></tbody></table>')
    assert rt.to_text(html) == "Head\n\nSee bold, link and SYS-1.\n\n- a\n\n[image: chart]\n\nH\n1"
    assert rt.markdown_to_html(rt.to_markdown(html)) == html  # spreadsheet round trip is lossless
    diff = rt.html_diff("<p>The quick fox</p>", "<p>The <strong>slow</strong> fox</p>")
    assert "<ins><strong>slow</strong></ins>" in diff and "<del>quick</del>" in diff
    assert rt.content_hash("T", html) != rt.content_hash("T", html + "<p>x</p>")


# --- API ------------------------------------------------------------------------------------------------------


def test_item_texts_are_rich_and_images_are_stored(team, project, anon, make_user):
    c = team["contributor"]
    p = f"/projects/{project}"
    data_uri = "data:image/png;base64," + base64.b64encode(png()).decode()
    item = new_item(c, project, "system_requirement", "With picture",
                    description=f'<p>Look: <img src="{data_uri}" alt="sketch"></p><script>x</script>')
    assert "<script" not in item["description"] and "data:" not in item["description"]
    src = item["description"].split('src="')[1].split('"')[0]
    assert src.startswith("/api/v1/images/") and item["description"].startswith("<p>Look:</p><img ")
    path = src.removeprefix("/api/v1")  # the test client adds the API prefix
    img = c.get(path)
    assert img.headers["content-type"] == "image/png" and "immutable" in img.headers["cache-control"]
    assert anon.get(path, expect=401)
    outsider, _ = make_user()  # not a member of the project
    outsider.get(path, expect=404)
    team["viewer"].get(path)  # members (any role) can see images

    # Upload endpoint: images only, contributors only.
    up = c.post(f"{p}/images", files={"file": ("chart.png", io.BytesIO(png((200, 30, 30))), "image/png")}, expect=201)
    assert up["url"].startswith("/api/v1/images/") and up["width"] == 120
    svg = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
    c.post(f"{p}/images", files={"file": ("x.svg", io.BytesIO(svg), "image/svg+xml")}, expect=415)
    c.post(f"{p}/images", files={"file": ("x.png", io.BytesIO(b"not an image"), "image/png")}, expect=415)
    team["viewer"].post(f"{p}/images", files={"file": ("v.png", io.BytesIO(png()), "image/png")}, expect=403)

    # Unchanged rich text does not create a version; a real change shows as an HTML diff.
    same = c.patch(f"{p}/items/{item['key']}", {"description": item["description"]})
    assert same["version"] == item["version"]
    changed = c.patch(f"{p}/items/{item['key']}", {"description": item["description"] + "<p>More <em>text</em></p>"})
    assert changed["version"] == "A.2" and changed["content_hash"] != item["content_hash"]
    diff = c.get(f"{p}/items/{item['key']}/diff?from=1&to=2")["changes"][0]
    assert diff["field"] == "description" and "<ins>" in diff["html_diff"]


def test_rich_word_export_and_round_trip(team, project):
    c = team["contributor"]
    p = f"/projects/{project}"
    spec = new_item(c, project, "specification", "Rich spec")
    up = c.post(f"{p}/images", files={"file": ("plot.png", io.BytesIO(png()), "image/png")}, expect=201)
    rich = (f'<p>Range <strong>0-10 bar</strong> with <a href="https://example.org/ds">data sheet</a>.</p>'
            f'<ul><li><p>gauge</p></li><li><p>absolute</p></li></ul><img src="{up["url"]}" alt="plot">'
            f'<table><tbody><tr><th><p>Range</p></th><th><p>Accuracy</p></th></tr>'
            f'<tr><td><p>10 bar</p></td><td><p>0.1 %</p></td></tr></tbody></table>')
    r1 = new_item(c, project, "system_requirement", "Measure pressure", parent=spec["key"], description=rich)
    r2 = new_item(c, project, "system_requirement", "Plain", parent=spec["key"], description="Simple text.")

    pdf = c.get(f"{p}/items/{spec['key']}/export.pdf").content
    assert pdf.startswith(b"%PDF") and b"/Image" in pdf
    plain_docx = c.get(f"{p}/items/{spec['key']}/export.docx").content
    assert any(n.startswith("word/media/") for n in zipfile.ZipFile(io.BytesIO(plain_docx)).namelist())

    exported = c.get(f"{p}/items/{spec['key']}/export.docx?roundtrip=edit").content

    def upload(content, dry_run=True):
        return c.post(f"{p}/items/{spec['key']}/import-docx",
                      files={"file": ("review.docx", io.BytesIO(content), "application/x")},
                      data={"dry_run": str(dry_run).lower()})

    untouched = upload(exported)
    assert untouched["summary"]["updated"] == 0 and untouched["summary"]["unchanged"] == 2  # images, tables, links

    # The reviewer makes a word in r2 bold; r1 (with image and table) stays untouched.
    doc = Document(io.BytesIO(exported))
    for sdt in doc.element.body.iter(qn("w:sdt")):
        tag = sdt.find(f"{qn('w:sdtPr')}/{qn('w:tag')}").get(qn("w:val"))
        if tag.startswith(f"alm:{r2['id']}:") and tag.endswith(":desc"):
            run = next(sdt.iter(qn("w:r")))
            rpr = run.find(qn("w:rPr"))
            if rpr is None:
                rpr = run.makeelement(qn("w:rPr"), {})
                run.insert(0, rpr)
            rpr.append(rpr.makeelement(qn("w:b"), {}))
    buf = io.BytesIO()
    doc.save(buf)
    res = upload(buf.getvalue(), dry_run=False)
    assert res["summary"]["updated"] == 1, res
    assert c.get(f"{p}/items/{r2['key']}")["description"] == "<p><strong>Simple text.</strong></p>"
    assert c.get(f"{p}/items/{r1['key']}")["description"] == rt.canonical(rich)


def test_reqif_round_trip_with_images(team, project, admin):
    c = team["contributor"]
    p = f"/projects/{project}"
    spec = new_item(c, project, "specification", "Exchange spec")
    up = c.post(f"{p}/images", files={"file": ("dim.png", io.BytesIO(png((5, 5, 200))), "image/png")}, expect=201)
    rich = (f'<p>Mount with <strong>M20</strong> thread.</p><ol><li><p>clean</p></li><li><p>mount</p></li></ol>'
            f'<img src="{up["url"]}" alt="drawing">')
    new_item(c, project, "system_requirement", "Mechanical interface", parent=spec["key"], description=rich)
    plain = new_item(c, project, "specification", "No pictures")
    assert c.get(f"{p}/items/{plain['key']}/reqif").headers["content-type"].startswith("application/xml")

    pkg = c.get(f"{p}/items/{spec['key']}/reqif")
    assert pkg.headers["content-disposition"].endswith('.reqifz"')
    z = zipfile.ZipFile(io.BytesIO(pkg.content))
    names = z.namelist()
    assert any(n.endswith(".reqif") for n in names) and any(n.startswith("images/") for n in names)
    xml = z.read(next(n for n in names if n.endswith(".reqif"))).decode()
    assert "<xhtml:strong>M20</xhtml:strong>" in xml and "xhtml:object" in xml

    admin.post("/projects", {"key": "SUPP", "name": "Supplier", "template": "systems_engineering"})
    res = admin.post("/projects/SUPP/import-reqif",
                     files={"file": ("in.reqifz", io.BytesIO(pkg.content), "application/zip")},
                     data={"dry_run": "false"})
    assert res["applied"] is True and res["summary"]["created"] >= 2, res
    items = admin.get("/projects/SUPP/items?type=system_requirement")["items"]
    detail = admin.get(f"/projects/SUPP/items/{items[0]['key']}")
    assert detail["description"] == rt.canonical(rich)  # formatting and image identical
    # A user who only belongs to the supplier project can see the imported image.
    from conftest import login

    sam = admin.post("/users", {"username": "sam", "display_name": "Sam", "password": "password-123"})
    admin.put("/projects/SUPP/members", {"user_id": sam["id"], "role": "viewer"})
    login(admin.c.app, "sam", "password-123").get(up["url"].removeprefix("/api/v1"))


def test_spreadsheet_round_trip_keeps_formatting(team, project):
    c = team["contributor"]
    p = f"/projects/{project}"
    rich = "<p>Use <strong>stainless</strong> steel.</p><ul><li><p>316L</p></li></ul>"
    item = new_item(c, project, "system_requirement", "Material", description=rich)
    csv_bytes = c.get(f"{p}/export.csv").content
    assert b"**stainless**" in csv_bytes
    res = c.post(f"{p}/import", files={"file": ("items.csv", io.BytesIO(csv_bytes), "text/csv")},
                 data={"dry_run": "false"})
    assert all(r["action"] in ("unchanged", "created") for r in res["results"]), res
    assert c.get(f"{p}/items/{item['key']}")["version"] == "A.1"
    edited = csv_bytes.decode("utf-8-sig").replace("**stainless**", "**stainless** or *titanium*")
    c.post(f"{p}/import", files={"file": ("items.csv", io.BytesIO(edited.encode()), "text/csv")},
           data={"dry_run": "false"})
    after = c.get(f"{p}/items/{item['key']}")
    assert after["version"] == "A.2" and "<em>titanium</em>" in after["description"] and "<li>" in after["description"]


def test_archive_carries_images(team, project, admin):
    c = team["contributor"]
    up = c.post(f"/projects/{project}/images", files={"file": ("a.png", io.BytesIO(png()), "image/png")}, expect=201)
    new_item(c, project, "system_requirement", "Pictured", description=f'<img src="{up["url"]}" alt="x">')
    archive = admin.get(f"/projects/{project}/archive")
    data = archive if isinstance(archive, dict) else json.loads(archive.content)
    assert data["format_version"] == 2 and data["images"][0]["sha256"] == up["sha256"]
