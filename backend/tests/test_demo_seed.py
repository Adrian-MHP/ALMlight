from sqlalchemy import select


def test_demo_seed_is_consistent_and_idempotent(db, admin):
    from almlight.modules.projects.models import Project
    from almlight.seed.demo import seed_demo

    seed_demo(db)
    seed_demo(db)  # second run is a no-op
    assert db.execute(select(Project.key)).scalars().all() == ["DEMO"]
    stats = admin.get("/projects/DEMO/stats")
    assert stats["total_items"] > 50 and stats["open_changes"] == 2  # the open CR + the defect from the failed test
    model = admin.get("/projects/DEMO/variants/feature-model")
    assert all(v["errors"] == [] for v in model["variants"]) and model["unknown_codes"] == []
    cov = admin.get("/projects/DEMO/coverage?type=system_requirement")
    assert cov["total"] == 8 and cov["allocated_pct"] == 88  # the NAMUR requirement is not allocated yet
    assert admin.get("/admin/audit/verify")["ok"] is True
    assert len(admin.get("/projects/DEMO/baselines")) == 3  # concept, document review, collection
    hart = admin.get("/projects/DEMO/variants/VAR-2/resolve")
    titles = {i["title"] for i in hart["included"]}
    assert "Provide HART communication" in titles and "Provide an IO-Link interface" not in titles


def test_demo_kpis_and_reports(db, admin):
    from almlight.seed.demo import seed_demo

    seed_demo(db)
    reports = admin.get("/projects/DEMO/reports")
    assert {r["title"] for r in reports} == {"Project KPI overview", "Requirements status"}
    kpi = next(r for r in reports if r["title"] == "Project KPI overview")
    data = admin.get(f"/projects/DEMO/reports/{kpi['id']}/data")
    assert all(d["ok"] for d in data.values()), data
    reuse = admin.get("/projects/DEMO/kpis/reuse")
    cell = next(r for r in reuse["rows"] if r["title"] == "Measuring cell")
    assert cell["products"] == 2
    lead = admin.get("/projects/DEMO/kpis/change-lead-time")
    assert lead["types"]["change_order"]["lead_days"]["avg"] == 17.0
    assert lead["end_to_end"]["avg"] == 31.0


def test_demo_backbone_content(db, admin, app):
    from conftest import login

    from almlight.seed.demo import seed_demo

    seed_demo(db)
    risks = admin.get("/projects/DEMO/risks")
    assert risks["summary"]["total"] == 4 and risks["summary"]["high_unmitigated"] == 1
    plans = admin.get("/projects/DEMO/plans")
    assert [r["title"] for r in plans["releases"]][:1] == ["Release 1.0 — pilot customers"]
    product = admin.get("/projects/DEMO/items?q=Smart%20pressure%20transmitter")["items"][0]["key"]
    rows = admin.get(f"/projects/DEMO/items/{product}/bom")["rows"]
    assert {r["title"] for r in rows if r["find_number"] == "50"} == {"Cable gland M16", "Cable gland M20 (EMC)"}
    oring = next(r for r in rows if r["title"] == "O-ring 12x2 FKM")
    assert oring["total_quantity"] == 2
    run = admin.get("/projects/DEMO/items?type=test_run")["items"][0]["key"]
    records = admin.get(f"/projects/DEMO/test-runs/{run}/records")
    temp = next(r for r in records if r["title"] == "Temperature cycle test")
    assert temp["step_results"][2]["result"] == "failed" and temp["defect"]
    housing = admin.get("/projects/DEMO/items?q=Housing&type=system_element")["items"][0]["key"]
    files = {a["filename"]: a for a in admin.get(f"/projects/DEMO/items/{housing}")["attachments"]}
    assert files["housing.step"]["revision"] == 2 and files["housing.step"]["checked_out_by"]["username"] == "alex"
    assert admin.get(f"/projects/DEMO/items/{housing}/attachments/{files['housing-drawing.png']['id']}").content[:4] \
        == b"\x89PNG"
    rita = login(app, "rita", "demo1234")
    notes = rita.get("/notifications")["items"]
    assert any(n["kind"] == "mention" for n in notes)
    mention = next(n for n in notes if n["kind"] == "mention")
    assert mention["item_key"].startswith("SYS-")  # the commented requirement, not the document
    assert rita.get("/projects/DEMO/queries")[0]["name"] == "Unverified system requirements"
