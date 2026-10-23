"""Document management: file check-out/check-in, file revisions with history, release blocking, inline preview."""

import io

from conftest import new_item

PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00"
       b"\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82")


def _upload(api, url, name, content, ctype):
    return api.post(f"{url}/attachments", files={"file": (name, io.BytesIO(content), ctype)}, expect=201)


def test_checkout_checkin_revisions_and_history(team, project):
    c, r, m, v = team["contributor"], team["reviewer"], team["manager"], team["viewer"]
    item = new_item(c, project, "system_element", "Housing")
    url = f"/projects/{project}/items/{item['key']}"
    att = _upload(c, url, "housing.step", b"ISO-10303-21; rev 1", "application/step")["attachments"][0]
    assert att["revision"] == 1 and att["checked_out_by"] is None
    a = f"{url}/attachments/{att['id']}"

    out = c.post(f"{a}/checkout", {"note": "adding mounting holes"})["attachments"][0]
    assert out["checked_out_by"]["username"] == "carla" and out["checkout_note"] == "adding mounting holes"
    assert c.post(f"{a}/checkout", {})["attachments"][0]["checked_out_by"]["username"] == "carla"  # idempotent
    assert [x["filename"] for x in c.get("/checkouts/mine")] == ["housing.step"]
    # nobody else may replace or remove it — not even a manager — and only holder or manager may cancel
    blocked = m.post(f"{a}/revisions", files={"file": ("housing.step", io.BytesIO(b"other"), "application/step")},
                     expect=409)
    assert "checked out by" in blocked["error"]["message"]
    m.delete(a, expect=409)
    r.delete(f"{a}/checkout", expect=403)
    v.post(f"{a}/checkout", {}, expect=403)

    before = c.get(url)["version"]
    checked_in = c.post(f"{a}/revisions", files={"file": ("housing-v2.step", io.BytesIO(b"ISO-10303-21; rev 2"),
                                                          "application/step")}, data={"comment": "holes added"})
    new = checked_in["attachments"][0]
    assert new["id"] == att["id"] and new["revision"] == 2 and new["filename"] == "housing-v2.step"
    assert new["checked_out_by"] is None and new["comment"] == "holes added"
    assert checked_in["version"] != before and c.get("/checkouts/mine") == []
    c.post(f"{a}/revisions", files={"file": ("x.step", io.BytesIO(b"ISO-10303-21; rev 2"), "application/step")},
           expect=422)  # identical content without a check-out is no new revision

    history = c.get(f"{a}/history")
    assert [h["revision"] for h in history] == [2, 1]
    assert history[0]["uploaded_by"]["username"] == "carla" and history[1]["filename"] == "housing.step"
    old = c.get(f"{a}?version={history[1]['version_no']}")
    assert old.content == b"ISO-10303-21; rev 1"
    assert c.get(a).content == b"ISO-10303-21; rev 2"

    # a manager can break a forgotten check-out (audited as forced)
    c.post(f"{a}/checkout", {})
    m.delete(f"{a}/checkout")
    assert c.get(url)["attachments"][0]["checked_out_by"] is None
    forced = m.get(f"/projects/{project}/audit?action=file.checkout_cancelled")[0]
    assert forced["details"]["forced"] is True and "held by" in forced["summary"]
    # checking in an unchanged file just ends the holder's check-out
    c.post(f"{a}/checkout", {})
    same = c.post(f"{a}/revisions", files={"file": ("housing-v2.step", io.BytesIO(b"ISO-10303-21; rev 2"),
                                                    "application/step")})
    assert same["attachments"][0]["revision"] == 2 and same["attachments"][0]["checked_out_by"] is None
    # removing an own checked-out file ends the check-out too
    c.post(f"{a}/checkout", {})
    assert c.delete(a)["attachments"] == [] and c.get("/checkouts/mine") == []


def test_checked_out_files_block_freezing(team, project):
    c = team["contributor"]
    req = new_item(c, project, "system_requirement", "Seal against IP67")
    url = f"/projects/{project}/items/{req['key']}"
    att = _upload(c, url, "ip67-test-report.docx", b"PK report", "application/vnd.openxmlformats")["attachments"][0]
    c.post(f"{url}/attachments/{att['id']}/checkout", {})
    options = {t["key"]: t for t in c.get(f"{url}/transitions")}
    assert options["submit"]["allowed"] is False
    assert any("ip67-test-report.docx is checked out by" in b for b in options["submit"]["blocked_by"])
    res = c.post(f"{url}/transitions/submit", {}, expect=409)
    assert "checked out" in str(res)
    c.delete(f"{url}/attachments/{att['id']}/checkout")
    assert c.post(f"{url}/transitions/submit", {})["status"] == "done"
    # a frozen item's files cannot be checked out
    locked = c.post(f"{url}/attachments/{att['id']}/checkout", {}, expect=423)
    assert locked["error"]["code"] == "locked" and "frozen" in locked["error"]["message"]


def test_inline_preview_only_for_safe_types(team, project):
    c = team["contributor"]
    item = new_item(c, project, "system_element", "Label")
    url = f"/projects/{project}/items/{item['key']}"
    png = _upload(c, url, "label.png", PNG, "image/png")["attachments"][0]
    shown = c.get(f"{url}/attachments/{png['id']}?inline=true")
    assert shown.headers["content-disposition"].startswith("inline")
    assert "sandbox" in shown.headers["content-security-policy"]
    svg = _upload(c, url, "logo.svg", b"<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>",
                  "image/svg+xml")["attachments"][-1]
    forced = c.get(f"{url}/attachments/{svg['id']}?inline=true")
    assert forced.headers["content-disposition"].startswith("attachment")  # scripts in SVG never render inline
