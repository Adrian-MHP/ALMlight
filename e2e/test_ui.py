"""End-to-end flows through the browser UI (demo data: users alex / rita / max, password demo1234)."""

import re
import uuid

from playwright.sync_api import Page, expect

from conftest import ADMIN_PASSWORD, choose, login, logout, shot

DEMO_PW = "demo1234"


def test_login_failure_and_projects(page: Page):
    page.goto("/")
    expect(page).to_have_url(re.compile(r"/login"))
    page.get_by_test_id("login-username").fill("alex")
    page.get_by_test_id("login-password").fill("wrong-password")
    page.get_by_test_id("login-submit").click()
    expect(page.get_by_text("Invalid username or password")).to_be_visible()
    login(page, "alex", DEMO_PW)
    expect(page.get_by_test_id("project-card-DEMO")).to_be_visible()
    shot(page, "01-projects")


def test_dashboard_and_navigation(page: Page):
    login(page, "alex", DEMO_PW)
    page.get_by_test_id("project-card-DEMO").click()
    expect(page.get_by_text("Requirement coverage")).to_be_visible()
    expect(page.get_by_text("Open changes")).to_be_visible()
    shot(page, "02-dashboard")
    for nav, marker in [("items", "items-table"), ("traceability", "coverage-table")]:
        page.get_by_test_id(f"nav-{nav}").click()
        expect(page.get_by_test_id(marker)).to_be_visible()
    shot(page, "03-traceability")


def test_items_search_and_filter(page: Page):
    login(page, "alex", DEMO_PW)
    page.goto("/p/DEMO/items")
    page.get_by_test_id("items-search").fill("HART")
    expect(page.get_by_test_id("items-table").get_by_text("Provide HART communication")).to_be_visible()
    page.get_by_test_id("items-search").fill("")
    choose(page, "items-type-filter", "System Requirement")
    expect(page.get_by_role("heading", name="System Requirement")).to_be_visible()
    shot(page, "04-items")


def test_create_edit_history(page: Page):
    login(page, "alex", DEMO_PW)
    page.goto("/p/DEMO/items")
    page.get_by_test_id("new-item").click()
    choose(page, "item-type", "System Requirement")
    title = f"Report diagnostics {uuid.uuid4().hex[:6]}"
    page.get_by_test_id("item-title").fill(title)
    page.get_by_test_id("item-description").fill("The device shall report **diagnostic** states.")
    page.get_by_test_id("item-save").click()
    expect(page.get_by_test_id("item-title-heading")).to_have_text(title)
    expect(page.get_by_test_id("item-version")).to_have_text("A.1")
    page.get_by_test_id("edit-item").click()
    page.get_by_test_id("item-title").fill(title + " (NAMUR NE 107)")
    page.get_by_test_id("item-save").click()
    expect(page.get_by_test_id("item-version")).to_have_text("A.2")
    page.get_by_test_id("tab-history").click()
    expect(page.get_by_test_id("versions-table").get_by_text("A.1")).to_be_visible()
    page.get_by_role("radio", name="compare from").last.check()
    expect(page.get_by_test_id("diff-panel")).to_contain_text("NAMUR")
    shot(page, "05-history-diff")


def test_review_and_signed_approval(page: Page):
    """alex submits a requirement; rita approves it with an e-signature from her inbox."""
    login(page, "alex", DEMO_PW)
    page.goto("/p/DEMO/items/SYS-4")
    page.get_by_test_id("transition-submit").click()
    expect(page.get_by_text("In Review").first).to_be_visible()
    expect(page.get_by_test_id("edit-item")).to_be_disabled()  # frozen
    page.get_by_test_id("transition-approve").click()
    expect(page.get_by_test_id("approval-SYS-4")).to_be_visible()
    expect(page.get_by_test_id("transition-approve")).to_be_disabled()  # pending
    shot(page, "06-approval-requested")
    logout(page)
    login(page, "rita", DEMO_PW)
    page.goto("/approvals")
    card = page.get_by_test_id("approval-SYS-4")
    card.get_by_test_id("vote-approve").click()
    page.get_by_test_id("prompt-password").fill("wrong")
    page.get_by_test_id("prompt-confirm").click()
    expect(page.get_by_text("Electronic signature failed")).to_be_visible()
    page.get_by_test_id("prompt-password").fill(DEMO_PW)
    page.get_by_test_id("prompt-confirm").click()
    expect(page.get_by_test_id("approval-SYS-4")).to_have_count(0)
    page.goto("/p/DEMO/items/SYS-4")
    expect(page.get_by_text("Approved").first).to_be_visible()
    expect(page.get_by_test_id("revise")).to_be_visible()
    shot(page, "07-approved")


def test_links_suspect_and_impact(page: Page):
    login(page, "alex", DEMO_PW)
    page.goto("/p/DEMO/items/MRQ-1?tab=links")
    expect(page.get_by_test_id("link-satisfies-SE-5")).to_be_visible()
    page.get_by_test_id("tab-impact").click()
    expect(page.get_by_test_id("impact-table")).to_be_visible()
    shot(page, "08-impact")
    # SE-5 satisfies MRQ-1; MRQ-1 was edited in the demo -> the link is suspect, confirm it on the element.
    page.goto("/p/DEMO/traceability?tab=suspects")
    expect(page.get_by_test_id("suspects-table")).to_be_visible()
    shot(page, "09-suspects")
    page.goto("/p/DEMO/items/SE-5?tab=links")
    row = page.get_by_test_id("link-satisfies-MRQ-1")
    row.get_by_test_id("confirm-link").click()
    expect(row.get_by_text("suspect")).to_have_count(0)


def test_document_view_and_add(page: Page):
    login(page, "alex", DEMO_PW)
    page.goto("/p/DEMO/documents")
    page.get_by_test_id("doc-SPEC-2").click()
    expect(page.get_by_test_id("document").get_by_text("1 Measurement")).to_be_visible()
    shot(page, "10-document")
    page.get_by_test_id("doc-add").click()
    page.get_by_test_id("doc-add-new").click()
    choose(page, "item-type", "System Requirement")
    page.get_by_test_id("item-title").fill("Provide a local display")
    page.get_by_test_id("item-save").click()
    expect(page.get_by_test_id("document").get_by_text("Provide a local display")).to_be_visible()


def test_structure_and_variants(page: Page):
    login(page, "alex", DEMO_PW)
    page.goto("/p/DEMO/structure")
    expect(page.get_by_test_id("tree-SE-1")).to_be_visible()
    expect(page.get_by_test_id("tree-SE-8")).to_be_visible()  # HART modem in the 150% view
    choose(page, "structure-variant", "VAR-3")  # IO-Link variant
    expect(page.get_by_test_id("tree-SE-8")).to_have_count(0)
    shot(page, "11-structure")
    page.goto("/p/DEMO/variants")
    page.get_by_test_id("load-VAR-2").click()
    expect(page.get_by_test_id("config-valid")).to_be_visible()
    page.get_by_test_id("feature-OUT_IOLINK").click()
    expect(page.get_by_test_id("config-errors")).to_contain_text("excludes")
    shot(page, "12-variants")


def test_baseline_compare(page: Page):
    login(page, "rita", DEMO_PW)
    page.goto("/p/DEMO/baselines")
    page.get_by_test_id("baseline-Concept baseline").click()
    expect(page.get_by_test_id("compare-result")).to_be_visible()
    page.get_by_test_id("new-baseline").click()
    name = f"Review {uuid.uuid4().hex[:4]}"
    page.get_by_test_id("baseline-name").fill(name)
    page.get_by_test_id("baseline-create").click()
    expect(page.get_by_test_id(f"baseline-{name}")).to_be_visible()
    shot(page, "13-baselines")


def test_verification_views(page: Page):
    login(page, "alex", DEMO_PW)
    page.goto("/p/DEMO/items/TR-1?tab=records")
    expect(page.get_by_test_id("records-table")).to_be_visible()
    page.goto("/p/DEMO/verification")
    page.get_by_test_id("tab-maturity").click()
    expect(page.get_by_test_id("maturity-table")).to_be_visible()
    shot(page, "14-maturity")


def test_settings_model_and_io(page: Page):
    login(page, "max", DEMO_PW)
    page.goto("/p/DEMO/settings")
    page.get_by_test_id("tab-model").click()
    expect(page.get_by_role("heading", name="Item types")).to_be_visible()
    shot(page, "15-model")
    page.get_by_test_id("tab-io").click()
    expect(page.get_by_text("Import from CSV / Excel")).to_be_visible()


def test_changes_board(page: Page):
    login(page, "max", DEMO_PW)
    page.goto("/p/DEMO/changes")
    expect(page.get_by_test_id("col-in_analysis").get_by_text("Extend measuring range")).to_be_visible()
    shot(page, "16-changes")


def test_permissions_in_ui(page: Page):
    """A viewer cannot create or edit; an outsider cannot see the project."""
    login(page, "admin", ADMIN_PASSWORD)
    name = f"v{uuid.uuid4().hex[:6]}"
    resp = page.request.post("/api/v1/users", data={"username": name, "display_name": "Viewer", "password": "password-123"})
    assert resp.ok
    user_id = resp.json()["id"]
    assert page.request.put("/api/v1/projects/DEMO/members", data={"user_id": user_id, "role": "viewer"}).ok
    outsider = f"o{uuid.uuid4().hex[:6]}"
    assert page.request.post("/api/v1/users", data={"username": outsider, "display_name": "Out", "password": "password-123"}).ok
    logout(page)
    login(page, name, "password-123")
    page.goto("/p/DEMO/items")
    expect(page.get_by_test_id("items-table")).to_be_visible()
    expect(page.get_by_test_id("new-item")).to_have_count(0)
    page.goto("/p/DEMO/items/SYS-1")
    expect(page.get_by_test_id("item-title-heading")).to_be_visible()
    expect(page.get_by_test_id("edit-item")).to_have_count(0)
    logout(page)
    login(page, outsider, "password-123")
    page.goto("/p/DEMO")
    expect(page.get_by_text("not found or not accessible")).to_be_visible()


def test_admin_audit_chain(page: Page):
    login(page, "admin", ADMIN_PASSWORD)
    page.goto("/admin")
    page.get_by_test_id("verify-chain").click()
    expect(page.get_by_text("Chain intact")).to_be_visible()


def test_branch_and_merge_document(page: Page):
    login(page, "alex", DEMO_PW)
    page.goto("/p/DEMO/documents/SPEC-2")
    page.get_by_test_id("doc-more").click()
    page.get_by_test_id("create-branch").click()
    page.get_by_test_id("branch-name").fill("Customer variant")
    page.get_by_test_id("branch-create").click()
    expect(page.get_by_test_id("branch-banner")).to_be_visible()
    branch_doc = page.url.rstrip("/").split("/")[-1]
    tree = page.request.get(f"/api/v1/projects/DEMO/items/{branch_doc}/tree").json()
    heading_copy = tree["children"][0]  # copy of H-1 "Measurement" (headings have no lifecycle)
    assert heading_copy["title"] == "Measurement"
    resp = page.request.patch(f"/api/v1/projects/DEMO/items/{heading_copy['key']}", data={"title": "Measurement and accuracy"})
    assert resp.ok, resp.text()
    page.reload()
    page.get_by_test_id("open-merge").click()
    expect(page.get_by_test_id(f"merge-row-{heading_copy['key']}")).to_contain_text("changed in branch")
    shot(page, "17-merge")
    page.get_by_test_id("merge-to-source").click()
    expect(page.get_by_text("Branch and source are in sync")).to_be_visible()
    assert page.request.get("/api/v1/projects/DEMO/items/H-1").json()["title"] == "Measurement and accuracy"


def test_reports_view_and_build(page: Page):
    login(page, "max", DEMO_PW)
    page.goto("/p/DEMO/reports")
    page.get_by_test_id("report-Project KPI overview").click()
    expect(page.get_by_test_id("report-heading")).to_have_text("Project KPI overview")
    expect(page.get_by_test_id("kpi-value").first).to_be_visible()
    expect(page.get_by_test_id("widget-reuse")).to_contain_text("Measuring cell")
    expect(page.get_by_test_id("widget-lead")).to_contain_text("Change Order")
    page.wait_for_timeout(800)  # let charts finish their entry animation for the screenshot
    shot(page, "18-report-kpis")
    # Build a new report from scratch.
    page.goto("/p/DEMO/reports")
    page.get_by_test_id("new-report").click()
    choose(page, "report-template", "Blank report")
    page.get_by_test_id("report-title").fill("Draft requirements")
    page.get_by_test_id("report-create").click()
    page.get_by_test_id("add-widget").click()
    page.get_by_test_id("add-chart").click()
    page.get_by_test_id("widget-title").fill("Requirements by state")
    page.get_by_test_id("widget-types").click()
    page.get_by_role("option", name="System Requirement").click()
    page.keyboard.press("Escape")
    expect(page.get_by_test_id("widget-preview").locator(".recharts-wrapper")).to_be_visible()
    shot(page, "19-widget-editor")
    page.get_by_test_id("widget-save").click()
    page.get_by_test_id("report-save").click()
    expect(page.get_by_test_id("report-heading")).to_have_text("Draft requirements")
    expect(page.get_by_text("Requirements by state")).to_be_visible()


def test_document_word_pdf_export(page: Page):
    login(page, "alex", DEMO_PW)
    page.goto("/p/DEMO/documents/SPEC-2")
    page.get_by_test_id("doc-export").click()
    page.get_by_test_id("export-docx").click()
    with page.expect_download() as dl:
        page.get_by_test_id("export-download").click()
    assert dl.value.suggested_filename.startswith("SPEC-2") and dl.value.suggested_filename.endswith(".docx")
    page.get_by_test_id("doc-export").click()
    page.get_by_test_id("export-pdf").click()
    page.get_by_text("From a baseline").click()
    choose(page, "export-baseline", "Concept baseline")
    with page.expect_download() as dl:
        page.get_by_test_id("export-download").click()
    path = dl.value.path()
    assert open(path, "rb").read(4) == b"%PDF"


REQIF = """<?xml version="1.0" encoding="UTF-8"?>
<REQ-IF xmlns="http://www.omg.org/spec/ReqIF/20110401/reqif.xsd" xmlns:xhtml="http://www.w3.org/1999/xhtml">
  <THE-HEADER><REQ-IF-HEADER IDENTIFIER="h"><TITLE>OEM requirements</TITLE></REQ-IF-HEADER></THE-HEADER>
  <CORE-CONTENT><REQ-IF-CONTENT>
    <DATATYPES><DATATYPE-DEFINITION-XHTML IDENTIFIER="x" LONG-NAME="XHTML"/><DATATYPE-DEFINITION-STRING IDENTIFIER="s" LONG-NAME="S" MAX-LENGTH="99"/></DATATYPES>
    <SPEC-TYPES>
      <SPEC-OBJECT-TYPE IDENTIFIER="t" LONG-NAME="OEM Requirement"><SPEC-ATTRIBUTES>
        <ATTRIBUTE-DEFINITION-STRING IDENTIFIER="a-name" LONG-NAME="ReqIF.Name"><TYPE><DATATYPE-DEFINITION-STRING-REF>s</DATATYPE-DEFINITION-STRING-REF></TYPE></ATTRIBUTE-DEFINITION-STRING>
        <ATTRIBUTE-DEFINITION-XHTML IDENTIFIER="a-text" LONG-NAME="ReqIF.Text"><TYPE><DATATYPE-DEFINITION-XHTML-REF>x</DATATYPE-DEFINITION-XHTML-REF></TYPE></ATTRIBUTE-DEFINITION-XHTML>
      </SPEC-ATTRIBUTES></SPEC-OBJECT-TYPE>
      <SPECIFICATION-TYPE IDENTIFIER="st" LONG-NAME="Spec"/>
    </SPEC-TYPES>
    <SPEC-OBJECTS>
      <SPEC-OBJECT IDENTIFIER="oem-1"><TYPE><SPEC-OBJECT-TYPE-REF>t</SPEC-OBJECT-TYPE-REF></TYPE><VALUES>
        <ATTRIBUTE-VALUE-STRING THE-VALUE="Withstand 2x overpressure"><DEFINITION><ATTRIBUTE-DEFINITION-STRING-REF>a-name</ATTRIBUTE-DEFINITION-STRING-REF></DEFINITION></ATTRIBUTE-VALUE-STRING>
        <ATTRIBUTE-VALUE-XHTML><DEFINITION><ATTRIBUTE-DEFINITION-XHTML-REF>a-text</ATTRIBUTE-DEFINITION-XHTML-REF></DEFINITION><THE-VALUE><xhtml:div><xhtml:p>The device shall withstand twice the upper range value.</xhtml:p></xhtml:div></THE-VALUE></ATTRIBUTE-VALUE-XHTML>
      </VALUES></SPEC-OBJECT>
    </SPEC-OBJECTS>
    <SPECIFICATIONS><SPECIFICATION IDENTIFIER="sp" LONG-NAME="OEM specification"><TYPE><SPECIFICATION-TYPE-REF>st</SPECIFICATION-TYPE-REF></TYPE>
      <CHILDREN><SPEC-HIERARCHY IDENTIFIER="h1"><OBJECT><SPEC-OBJECT-REF>oem-1</SPEC-OBJECT-REF></OBJECT></SPEC-HIERARCHY></CHILDREN></SPECIFICATION></SPECIFICATIONS>
  </REQ-IF-CONTENT></CORE-CONTENT>
</REQ-IF>"""


def test_reqif_import_wizard(page: Page, tmp_path):
    login(page, "alex", DEMO_PW)
    page.goto("/p/DEMO/settings")
    page.get_by_test_id("tab-io").click()
    f = tmp_path / "oem.reqif"
    f.write_text(REQIF)
    page.get_by_test_id("reqif-file").click()
    page.locator("input[type=file]").last.set_input_files(str(f))
    page.get_by_test_id("reqif-analyse").click()
    expect(page.get_by_test_id("reqif-types")).to_contain_text("OEM Requirement")
    choose(page, "reqif-map-OEM Requirement", "Stakeholder Requirement")
    page.get_by_test_id("reqif-analyse").click()
    expect(page.get_by_text("created: 2")).to_be_visible()
    shot(page, "20-reqif")
    page.get_by_test_id("reqif-apply").click()
    expect(page.get_by_text("Imported", exact=True)).to_be_visible()
    found = page.request.get("/api/v1/projects/DEMO/items?q=overpressure").json()
    assert found["total"] == 1 and found["items"][0]["type_key"] == "stakeholder_requirement"
