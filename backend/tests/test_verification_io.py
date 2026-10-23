import io
import json
from xml.etree import ElementTree as ET

from conftest import approve, new_item
from openpyxl import load_workbook

JUNIT = b"""<?xml version="1.0" encoding="UTF-8"?>
<testsuites>
  <testsuite name="sensor" tests="3">
    <testcase classname="sensor.range" name="test_full_scale" time="0.12"/>
    <testcase classname="sensor.output" name="test_TC-2_current_loop" time="0.30">
      <failure message="expected 20.0 mA, got 19.2 mA">assert ...</failure>
    </testcase>
    <testcase classname="sensor.other" name="test_unmapped" time="0.01"/>
  </testsuite>
</testsuites>"""


def _verified_setup(c, project):
    req = new_item(c, project, "system_requirement", "Measure 0-10 bar")
    tc1 = new_item(c, project, "test_case", "Full-scale test", fields={"automation_id": "sensor.range.test_full_scale"})
    tc2 = new_item(c, project, "test_case", "Current loop test")
    for tc in (tc1, tc2):
        c.post(f"/projects/{project}/links", {"type": "verifies", "source": tc["key"], "target": req["key"]})
    return req, tc1, tc2


def test_manual_test_run_and_status(team, project):
    c = team["contributor"]
    p = f"/projects/{project}"
    req, tc1, tc2 = _verified_setup(c, project)
    assert c.get(f"{p}/items/{req['key']}/verification")["status"] == "not_run"
    run = new_item(c, project, "test_run", "Lab run 1")
    records = c.post(f"{p}/test-runs/{run['key']}/records", {"test_cases": [tc1["key"], tc2["key"]]})
    assert [r["result"] for r in records] == ["not_run", "not_run"]
    c.post(f"{p}/test-runs/{run['key']}/records", {"test_cases": [req["key"]]}, expect=422)
    c.post(f"{p}/items/{run['key']}/transitions/start", {})
    blocked = c.post(f"{p}/items/{run['key']}/transitions/complete", {}, expect=409)
    assert "not executed" in blocked["error"]["details"]["blocked_by"][0]
    c.patch(f"{p}/test-runs/{run['key']}/records/{records[0]['id']}", {"result": "great"}, expect=422)
    for rec in records:
        c.patch(f"{p}/test-runs/{run['key']}/records/{rec['id']}", {"result": "passed", "duration_ms": 5})
    c.post(f"{p}/items/{run['key']}/transitions/complete", {})
    assert c.get(f"{p}/items/{req['key']}/verification")["status"] == "passed"
    # Completed runs are frozen.
    c.patch(f"{p}/test-runs/{run['key']}/records/{records[0]['id']}", {"result": "failed"}, expect=423)
    # Changing the requirement makes the verifies links suspect -> re-test needed.
    c.patch(f"{p}/items/{req['key']}", {"title": "Measure 0-16 bar"})
    assert c.get(f"{p}/items/{req['key']}/verification")["status"] == "retest"
    cov = c.get(f"{p}/coverage?type=system_requirement")
    assert cov["total"] == 1 and cov["with_tests_pct"] == 100 and cov["verified_pct"] == 0


def test_junit_import(team, project):
    c = team["contributor"]
    p = f"/projects/{project}"
    req, tc1, tc2 = _verified_setup(c, project)
    res = c.post(f"{p}/test-runs/import-junit", files={"file": ("results.xml", io.BytesIO(JUNIT), "text/xml")},
                 data={"build": "1.4.2", "environment": "CI"})
    assert res["matched"] == 2 and res["unmatched"] == ["sensor.other.test_unmapped"]
    assert res["summary"] == {"passed": 1, "failed": 1} and res["state"] == "completed"
    records = c.get(f"{p}/test-runs/{res['run']}/records")
    failed = next(r for r in records if r["test_case"] == tc2["key"])
    assert failed["result"] == "failed" and "19.2" in failed["comment"]
    assert c.get(f"{p}/items/{req['key']}/verification")["status"] == "failed"
    c.post(f"{p}/test-runs/import-junit", files={"file": ("x.xml", io.BytesIO(b"<not-xml"), "text/xml")},
           expect=422)
    c.post(f"{p}/test-runs/import-junit", files={"file": ("x.xml", io.BytesIO(b"<testsuite/>"), "text/xml")},
           expect=422)


def test_maturity_view(team, project):
    c, r = team["contributor"], team["reviewer"]
    p = f"/projects/{project}"
    stk = new_item(c, project, "stakeholder_requirement", "Monitor pressure")
    req, tc1, tc2 = _verified_setup(c, project)
    c.post(f"{p}/links", {"type": "derives_from", "source": req["key"], "target": stk["key"]})
    el = new_item(c, project, "system_element", "Sensor unit", fields={"level": "subsystem"})
    c.post(f"{p}/links", {"type": "satisfies", "source": el["key"], "target": req["key"]})
    row = c.get(f"{p}/maturity")[0]
    # Allocated but not yet released requirements -> partially specified.
    assert (row["specified"], row["realised"], row["verified"]) == ("partial", "none", "none")
    c.post(f"{p}/items/{req['key']}/transitions/submit", {})
    approve(req["key"], project, c, r)
    run = new_item(c, project, "test_run", "Run")
    recs = c.post(f"{p}/test-runs/{run['key']}/records", {"test_cases": [tc1["key"], tc2["key"]]})
    for rec in recs:
        c.patch(f"{p}/test-runs/{run['key']}/records/{rec['id']}", {"result": "passed"})
    row = c.get(f"{p}/maturity")[0]
    assert (row["specified"], row["verified"], row["validated"]) == ("done", "done", "none")


def test_csv_round_trip(team, project):
    c = team["contributor"]
    p = f"/projects/{project}"
    csv_text = (
        "key,type,title,description,parent,priority,derives_from\n"
        "NEW-1,stakeholder_requirement,Monitor pressure,Customer need,,must,\n"
        ",system_requirement,Measure 0-10 bar,,,should,NEW-1\n"
    )
    dry = c.post(f"{p}/import", files={"file": ("reqs.csv", io.BytesIO(csv_text.encode()), "text/csv")},
                 data={"dry_run": "true"})
    assert dry["summary"] == {"created": 2, "links": 1} and dry["applied"] is False
    assert c.get(f"{p}/items")["total"] == 0
    real = c.post(f"{p}/import", files={"file": ("reqs.csv", io.BytesIO(csv_text.encode()), "text/csv")},
                  data={"dry_run": "false"})
    assert real["applied"] is True
    items = c.get(f"{p}/items")["items"]
    sys_req = next(i for i in items if i["type_key"] == "system_requirement")
    links = c.get(f"{p}/items/{sys_req['key']}/links")
    assert links[0]["type"] == "derives_from" and links[0]["other"]["title"] == "Monitor pressure"
    exported = c.get(f"{p}/export.csv").content.decode("utf-8-sig")
    header = exported.splitlines()[0].split(",")
    assert header[:3] == ["key", "type", "title"] and "derives_from" in header
    # Update by key; errors roll back the whole import.
    upd = f"key,title,priority\n{sys_req['key']},Measure 0-16 bar,must\nXYZ-9,,\n"
    res = c.post(f"{p}/import", files={"file": ("u.csv", io.BytesIO(upd.encode()), "text/csv")},
                 data={"dry_run": "false"})
    assert res["applied"] is False and res["summary"]["error"] == 1
    assert c.get(f"{p}/items/{sys_req['key']}")["title"] == "Measure 0-10 bar"


def test_xlsx_export(team, project):
    c = team["contributor"]
    new_item(c, project, "system_requirement", "R1")
    wb = load_workbook(io.BytesIO(c.get(f"/projects/{project}/export.xlsx").content))
    rows = list(wb.active.values)
    assert rows[0][0] == "key" and rows[1][2] == "R1"


def test_reqif_export(team, project):
    c = team["contributor"]
    spec = new_item(c, project, "specification", "System spec")
    a = new_item(c, project, "system_requirement", "Measure pressure", parent=spec["key"],
                 description="Para 1\n\nPara 2")
    b = new_item(c, project, "system_requirement", "Output current", parent=spec["key"])
    stk = new_item(c, project, "stakeholder_requirement", "Need")
    c.post(f"/projects/{project}/links", {"type": "derives_from", "source": a["key"], "target": b["key"]})
    c.post(f"/projects/{project}/links", {"type": "derives_from", "source": b["key"], "target": stk["key"]})
    xml = c.get(f"/projects/{project}/items/{spec['key']}/reqif").content
    ns = {"r": "http://www.omg.org/spec/ReqIF/20110401/reqif.xsd"}
    root = ET.fromstring(xml)
    assert len(root.findall(".//r:SPEC-OBJECT", ns)) == 2
    assert len(root.findall(".//r:SPEC-RELATION", ns)) == 1  # the link leaving the spec is not exported
    assert len(root.findall(".//r:SPEC-HIERARCHY", ns)) == 2
    whole = ET.fromstring(c.get(f"/projects/{project}/reqif").content)
    assert len(whole.findall(".//r:SPEC-OBJECT", ns)) == 3


def test_archive_round_trip(team, project, admin):
    c, r = team["contributor"], team["reviewer"]
    p = f"/projects/{project}"
    a = new_item(c, project, "system_requirement", "A")
    b = new_item(c, project, "stakeholder_requirement", "B")
    c.patch(f"{p}/items/{a['key']}", {"title": "A2"})
    c.post(f"{p}/links", {"type": "derives_from", "source": a["key"], "target": b["key"]})
    r.post(f"{p}/baselines", {"name": "BL1"})
    c.get(f"{p}/archive", expect=403)
    archive = admin.get(f"{p}/archive")
    assert archive["format"] == "almlight-project-archive" and len(archive["items"]) == 2
    raw = json.dumps(archive).encode()
    res = admin.post("/projects/import-archive", files={"file": ("a.json", io.BytesIO(raw), "application/json")},
                     data={"key": "PXCOPY"})
    assert res["key"] == "PXCOPY"
    copied = admin.get(f"/projects/PXCOPY/items/{a['key']}")
    assert copied["title"] == "A2" and copied["version"] == "A.2"
    assert len(admin.get(f"/projects/PXCOPY/items/{a['key']}/versions")) == 2
    assert admin.get(f"/projects/PXCOPY/items/{a['key']}/links")[0]["other"]["key"] == b["key"]
    assert admin.get("/projects/PXCOPY/baselines")[0]["item_count"] == 2
    new = new_item(admin, "PXCOPY", "system_requirement", "next")
    assert new["key"] == "SYS-2"
    admin.post("/projects/import-archive", files={"file": ("a.json", io.BytesIO(raw), "application/json")},
               data={"key": "PXCOPY"}, expect=409)
