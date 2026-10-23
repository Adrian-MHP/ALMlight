"""Engineering-backbone features in the browser: notifications, watching and mentions, saved views and export,
step-wise test execution with defects, risks (FMEA), release plans, bill of materials, where-used and SSO."""

import csv
import io
import re
import time
import uuid
import zipfile

from playwright.sync_api import Browser, Page, expect

from conftest import BASE_URL, choose, login, shot

DEMO_PW = "demo1234"


def other_user(browser: Browser, username: str) -> Page:
    page = browser.new_context(base_url=BASE_URL, viewport={"width": 1440, "height": 900}).new_page()
    login(page, username, DEMO_PW)
    return page


def new_requirement(page: Page, title: str) -> str:
    resp = page.request.post("/api/v1/projects/DEMO/items", data={"type": "system_requirement", "title": title})
    assert resp.ok, resp.text()
    return resp.json()["key"]


def unread(page: Page) -> int:
    return page.request.get("/api/v1/notifications").json()["unread"]


def eventually(check, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while not check():
        assert time.monotonic() < deadline, "condition not met in time"
        time.sleep(0.2)


def test_notification_center_watch_and_mention(page: Page, browser: Browser):
    login(page, "rita", DEMO_PW)
    # The demo has an unread @mention for rita: it opens the commented item and is marked read.
    before = unread(page)
    assert before > 0
    expect(page.get_by_test_id("notifications")).to_be_visible()
    page.get_by_test_id("notifications").click()
    center = page.get_by_test_id("notification-center")
    expect(center.get_by_test_id("note-mention").first).to_contain_text("Commented on SYS-8")
    shot(page, "40-notification-center")
    center.get_by_test_id("note-mention").first.click()
    expect(page).to_have_url(re.compile(r"/p/DEMO/items/SYS-8"))
    eventually(lambda: unread(page) == before - 1)

    # rita watches a new requirement; alex changes it; the bell updates live without a reload.
    alex = other_user(browser, "alex")
    key = new_requirement(alex, f"Watched requirement {uuid.uuid4().hex[:4]}")
    page.goto(f"/p/DEMO/items/{key}")
    page.get_by_test_id("watch-toggle").click()
    expect(page.get_by_test_id("watch-toggle")).to_contain_text("Watching")
    count = unread(page)
    assert alex.request.patch(f"/api/v1/projects/DEMO/items/{key}", data={"title": "Watched requirement (changed)"}).ok
    expect(page.get_by_test_id("notifications").locator("xpath=..")).to_contain_text(str(count + 1))
    page.get_by_test_id("notifications").click()
    expect(page.get_by_test_id("notification-center").get_by_test_id("note-watch").first).to_contain_text(key)
    page.keyboard.press("Escape")

    # alex mentions rita in a comment, picking her from the @ suggestions: rita gets a toast at once.
    alex.goto(f"/p/DEMO/items/{key}?tab=comments")
    body = alex.get_by_test_id("comment-body")
    body.click()
    body.press_sequentially("Could you check the range, @ri")
    expect(alex.get_by_test_id("mention-list")).to_be_visible()
    alex.get_by_test_id("mention-rita").click()
    expect(body).to_have_value("Could you check the range, @rita ")
    alex.get_by_test_id("comment-add").click()
    expect(page.get_by_text("alex mentioned you")).to_be_visible()
    shot(page, "41-mention-toast")
    page.get_by_test_id("notifications").click()
    expect(page.get_by_test_id("notification-center").get_by_test_id("note-mention").first).to_contain_text(key)
    page.get_by_test_id("notifications-read-all").click()
    expect(page.get_by_test_id("notifications-read-all")).to_be_disabled()
    eventually(lambda: unread(page) == 0)

    # Unwatching stops further notifications.
    page.keyboard.press("Escape")
    page.get_by_test_id("watch-toggle").click()
    expect(page.get_by_test_id("watch-toggle")).not_to_contain_text("Watching")
    assert alex.request.patch(f"/api/v1/projects/DEMO/items/{key}", data={"title": "Changed again"}).ok
    page.wait_for_timeout(800)
    assert unread(page) == 0
    alex.context.close()


def test_saved_view_with_traceability_gap_and_export(page: Page):
    login(page, "alex", DEMO_PW)
    page.goto("/p/DEMO/items?type=system_requirement")
    expect(page.get_by_test_id("items-table")).to_be_visible()
    expected = page.request.get("/api/v1/projects/DEMO/items?type=system_requirement&link_type=verifies&link_dir=in"
                                "&link_exists=false&limit=200").json()["items"]
    gap_keys = {i["key"] for i in expected}
    assert gap_keys and "SYS-1" not in gap_keys  # SYS-1 is verified by TC-1 in the demo
    choose(page, "items-gap-filter", "Not verified by a test")
    rows = page.get_by_test_id("items-table").locator("tbody tr")
    expect(rows).to_have_count(len(gap_keys))
    assert set(page.get_by_test_id("items-table").locator("tbody tr td:first-child").all_inner_texts()) == gap_keys

    # Export delivers exactly this view.
    page.get_by_test_id("items-export").click()
    with page.expect_download() as dl:
        page.get_by_test_id("export-csv").click()
    data = open(dl.value.path(), encoding="utf-8-sig").read()
    exported = {r[0] for r in list(csv.reader(io.StringIO(data)))[1:]}
    assert exported == gap_keys

    name = f"Gaps {uuid.uuid4().hex[:4]}"
    page.get_by_test_id("views-menu").click()
    page.get_by_test_id("save-view").click()
    page.get_by_test_id("view-name").fill(name)
    page.get_by_test_id("view-save").click()
    expect(page.get_by_text("View saved")).to_be_visible()

    # A fresh list (all items) — applying the view restores type and gap filter.
    page.goto("/p/DEMO/items")
    expect(page.get_by_test_id("items-gap-filter")).to_have_value("")
    page.get_by_test_id("views-menu").click()
    expect(page.get_by_test_id(f"view-{name}")).to_contain_text(str(len(gap_keys)))
    page.get_by_test_id(f"view-{name}").click()
    expect(page).to_have_url(re.compile(r"type=system_requirement"))
    expect(page.get_by_test_id("items-gap-filter")).to_have_value("Not verified by a test")
    expect(rows).to_have_count(len(gap_keys))
    shot(page, "42-saved-view")
    page.get_by_test_id("views-menu").click()
    page.get_by_test_id(f"view-delete-{name}").click()
    expect(page.get_by_text("View deleted")).to_be_visible()
    # The demo's shared view belongs to someone else: alex can use it but not delete it.
    page.get_by_test_id("views-menu").click()
    expect(page.get_by_test_id("view-Unverified system requirements")).to_be_visible()
    expect(page.get_by_test_id("view-delete-Unverified system requirements")).to_have_count(0)


def test_step_wise_test_execution_raises_defect(page: Page):
    login(page, "alex", DEMO_PW)
    run = page.request.post("/api/v1/projects/DEMO/items", data={"type": "test_run", "title": f"E2E run {uuid.uuid4().hex[:4]}"}).json()["key"]
    assert page.request.post(f"/api/v1/projects/DEMO/test-runs/{run}/records", data={"test_cases": ["TC-5"]}).ok
    page.goto(f"/p/DEMO/items/{run}?tab=records")
    page.get_by_test_id("execute-TC-5").click()
    drawer = page.get_by_test_id("execute-drawer")
    expect(drawer.locator("[data-testid^=exec-step-]")).to_have_count(3)
    drawer.get_by_test_id("exec-step-1").get_by_text("Pass", exact=True).click()
    drawer.get_by_test_id("exec-step-2").get_by_text("Pass", exact=True).click()
    drawer.get_by_test_id("exec-step-2").get_by_placeholder("Observed outcome").fill("0.12 %")
    drawer.get_by_test_id("execute-save").click()
    expect(page.get_by_text("Saved — not_run")).to_be_visible()  # a step without a result leaves the case open
    drawer.get_by_test_id("exec-step-3").get_by_text("Fail", exact=True).click()
    drawer.get_by_test_id("exec-step-3").get_by_placeholder("Observed outcome").fill("0.6 % at -40 degC")
    shot(page, "43-test-execution")
    drawer.get_by_test_id("defect-step-3").click()  # stores the results, then raises the defect
    expect(page.get_by_text(re.compile(r"Defect PR-\d+ created"))).to_be_visible()
    expect(drawer.get_by_text(re.compile(r"Defect PR-\d+"))).to_be_visible()
    expect(drawer.get_by_text("Current result: failed")).to_be_visible()
    defect = drawer.get_by_text(re.compile(r"Defect PR-\d+")).inner_text().split()[-1]
    detail = page.request.get(f"/api/v1/projects/DEMO/items/{defect}").json()
    assert "Step 3" in detail["description"] and "0.6 % at -40 degC" in detail["description"]
    page.keyboard.press("Escape")
    expect(page.get_by_test_id("record-TC-5")).to_contain_text(defect)
    expect(page.get_by_test_id("record-TC-5")).to_contain_text("1 failed")


def test_risk_register_matrix_and_live_rpn(page: Page):
    login(page, "alex", DEMO_PW)
    page.goto("/p/DEMO/risks")
    expect(page.get_by_test_id("risk-register")).to_be_visible()
    total = int(page.get_by_test_id("risk-kpi-Risks").inner_text().split()[-1])
    assert total >= 4
    # Clicking a matrix cell filters the register to the risks rated there.
    page.get_by_test_id("risk-cell-9-5").click()
    expect(page.get_by_test_id("risk-register").locator("tbody tr")).to_have_count(1)
    expect(page.get_by_test_id("risk-RSK-1")).to_be_visible()
    page.get_by_text(re.compile(r"Show all \(filtered")).click()
    page.get_by_test_id("risk-view").get_by_text("After mitigation").click()
    expect(page.get_by_test_id("risk-matrix")).to_be_visible()

    # New risk: RPN and risk level are calculated while typing (same rules as the server).
    page.get_by_test_id("new-risk").click()
    page.get_by_test_id("item-title").fill("Connector corrosion in salt spray")
    page.get_by_test_id("field-severity").fill("7")
    page.get_by_test_id("field-occurrence").fill("4")
    page.get_by_test_id("field-detection").fill("6")
    expect(page.get_by_test_id("field-rpn")).to_have_value("168")
    expect(page.get_by_test_id("field-risk_level")).to_have_value("Medium")
    page.get_by_test_id("field-detection").fill("8")
    expect(page.get_by_test_id("field-rpn")).to_have_value("224")
    expect(page.get_by_test_id("field-risk_level")).to_have_value("High")
    shot(page, "44-risk-form")
    page.get_by_test_id("item-save").click()
    expect(page).to_have_url(re.compile(r"/p/DEMO/items/RSK-\d+"))
    expect(page.get_by_test_id("value-rpn")).to_have_text("224")
    page.goto("/p/DEMO/risks")
    expect(page.get_by_test_id("risk-kpi-Risks")).to_contain_text(str(total + 1))
    new = page.get_by_test_id("risk-register").locator("tr", has_text="Connector corrosion")
    expect(new).to_contain_text("224")
    expect(new).to_contain_text("none")  # high risk without mitigation is flagged
    shot(page, "45-risks")


def test_release_plan_timeline_burnup_and_planning(page: Page):
    login(page, "alex", DEMO_PW)
    key = new_requirement(page, f"Planned requirement {uuid.uuid4().hex[:4]}")
    page.goto("/p/DEMO/plans")
    expect(page.get_by_test_id("plan-timeline")).to_contain_text("REL-1")
    expect(page.get_by_test_id("release-status-REL-1")).to_have_text(re.compile("on track|at risk|overdue"))
    page.get_by_test_id("release-REL-1").click()
    expect(page).to_have_url(re.compile(r"release=REL-1"))
    detail = page.get_by_test_id("plan-detail")
    expect(detail.get_by_test_id("plan-items")).to_contain_text("SYS-1")
    before = detail.get_by_test_id("plan-items").locator("tbody tr").count()
    expect(page.get_by_test_id("release-REL-1")).to_contain_text(f"of {before} done")
    page.get_by_test_id("plan-item").click()
    page.get_by_test_id("plan-item").fill(key)
    page.get_by_role("option", name=re.compile(key)).click()
    page.get_by_test_id("plan-add").click()
    expect(page.get_by_text("Planned into the release")).to_be_visible()
    expect(detail.get_by_test_id("plan-items")).to_contain_text(key)
    expect(page.get_by_test_id("release-REL-1")).to_contain_text(f"of {before + 1} done")
    shot(page, "46-plans")
    # The item list filters by release.
    page.goto("/p/DEMO/items")
    choose(page, "items-release-filter", "REL-1")
    expect(page.get_by_test_id("items-table")).to_contain_text(key)


def test_bom_effectivity_quantity_and_export(page: Page):
    login(page, "alex", DEMO_PW)
    page.goto("/p/DEMO/structure?view=bom")
    bom = page.get_by_test_id("bom-table")
    expect(bom.get_by_test_id("bom-SE-14")).to_be_visible()
    expect(bom.get_by_test_id("bom-SE-15")).to_be_visible()
    # Effectivity: the M16 gland until end of 2026, the M20 gland from 2027.
    page.get_by_test_id("bom-effective").fill("2026-11-15")
    expect(bom.get_by_test_id("bom-SE-15")).to_have_count(0)
    expect(bom.get_by_test_id("bom-SE-14")).to_be_visible()
    page.get_by_test_id("bom-effective").fill("2027-02-01")
    expect(bom.get_by_test_id("bom-SE-14")).to_have_count(0)
    expect(bom.get_by_test_id("bom-SE-15")).to_be_visible()
    page.get_by_test_id("bom-effective").fill("")
    expect(bom.get_by_test_id("bom-SE-14")).to_be_visible()

    # Quantity of the O-ring in the sensor unit: 2 -> 4, total rolls up.
    expect(bom.get_by_test_id("bom-total-SE-13")).to_have_text("2")
    bom.get_by_test_id("bom-edit-SE-13").click()
    page.get_by_test_id("bom-qty").fill("4")
    page.get_by_test_id("bom-save").click()
    expect(page.get_by_text("Updated SE-13 in the BOM")).to_be_visible()
    expect(bom.get_by_test_id("bom-total-SE-13")).to_have_text("4")
    shot(page, "47-bom")

    page.get_by_test_id("bom-export").click()
    with page.expect_download() as dl:
        page.get_by_role("menuitem", name="CSV").click()
    rows = list(csv.reader(io.StringIO(open(dl.value.path(), encoding="utf-8-sig").read())))
    header = rows[0]
    oring = next(r for r in rows[1:] if "SE-13" in r)
    assert oring[header.index("total_quantity")] in ("4", "4.0"), (header, oring)


def test_where_used_paths(page: Page):
    login(page, "alex", DEMO_PW)
    page.goto("/p/DEMO/items/SE-5?tab=where-used")
    where = page.get_by_test_id("where-used")
    expect(where).to_contain_text("Used in 2 parent")
    expect(where).to_contain_text("SE-11")
    expect(where).to_contain_text("SE-1")
    expect(where).to_contain_text("SE-2")


def test_single_sign_on_is_hidden_unless_configured(page: Page):
    page.goto("/login")
    expect(page.get_by_test_id("login-username")).to_be_visible()
    expect(page.get_by_test_id("login-sso")).to_have_count(0)
    assert page.request.get("/api/v1/auth/oidc/config").json()["enabled"] is False
    assert page.request.get("/api/v1/auth/oidc/login", max_redirects=0).status == 404
    # e-mail digests are off on a server without SMTP: the account page says so
    login(page, "alex", DEMO_PW)
    page.goto("/account")
    expect(page.get_by_test_id("email-notifications")).to_be_disabled()


def test_files_check_out_check_in_history_and_preview(page: Page, browser: Browser):
    login(page, "alex", DEMO_PW)
    housing = page.request.get("/api/v1/projects/DEMO/items?q=Housing&type=system_element").json()["items"][0]["key"]
    # the demo CAD model is checked out by alex: listed on his home page, release is blocked
    page.goto("/")
    expect(page.get_by_test_id("home-checkouts")).to_contain_text("housing.step")
    blocked = {t["key"]: t for t in page.request.get(f"/api/v1/projects/DEMO/items/{housing}/transitions").json()}
    assert any("housing.step is checked out by Alex Engineer" in b for b in blocked["freeze"]["blocked_by"])
    page.goto(f"/p/DEMO/items/{housing}?tab=files")
    row = page.get_by_test_id("file-housing.step")
    expect(row.get_by_test_id("file-status")).to_contain_text("Checked out by you")
    expect(row.get_by_test_id("file-rev")).to_have_text("2")
    shot(page, "48-files")

    # rita sees who holds it and cannot change the file
    rita = other_user(browser, "rita")
    rita.goto(f"/p/DEMO/items/{housing}?tab=files")
    rrow = rita.get_by_test_id("file-housing.step")
    expect(rrow.get_by_test_id("file-status")).to_contain_text("Alex Engineer")
    rrow.get_by_test_id("file-menu").click()
    expect(rita.get_by_test_id("file-history")).to_be_visible()
    expect(rita.get_by_test_id("file-checkin")).to_have_count(0)
    expect(rita.get_by_test_id("file-remove")).to_have_count(0)
    expect(rita.get_by_test_id("file-cancel-checkout")).to_have_count(0)
    rita.context.close()

    # alex checks in revision 3 with a comment; the check-out ends
    row.get_by_test_id("file-checkin-input").set_input_files(files=[{
        "name": "housing.step", "mimeType": "application/step",
        "buffer": b"ISO-10303-21;\nHEADER;\nFILE_DESCRIPTION(('Housing rev 3: M20 thread'),'2;1');\nENDSEC;\nEND-ISO-10303-21;\n"}])
    page.get_by_test_id("file-checkin-comment").fill("M20 thread for the EMC gland")
    page.get_by_test_id("file-checkin-confirm").click()
    expect(page.get_by_text("Checked in housing.step")).to_be_visible()
    expect(row.get_by_test_id("file-rev")).to_have_text("3")
    expect(row.get_by_test_id("file-status")).to_have_text("Available")
    row.get_by_test_id("file-menu").click()
    page.get_by_test_id("file-history").click()
    history = page.get_by_test_id("file-history-table")
    expect(history.locator("tbody tr")).to_have_count(3)
    expect(history).to_contain_text("M20 thread for the EMC gland")
    page.keyboard.press("Escape")
    # freezing is possible again
    after = {t["key"]: t for t in page.request.get(f"/api/v1/projects/DEMO/items/{housing}/transitions").json()}
    assert not any("checked out" in b for b in after["freeze"]["blocked_by"])
    # the drawing previews in the browser
    page.get_by_test_id("file-housing-drawing.png").get_by_test_id("file-preview-open").click()
    img = page.get_by_test_id("file-preview")
    expect(img).to_be_visible()
    page.wait_for_function("el => el.complete && el.naturalWidth > 0", arg=img.element_handle())
    # check out again and cancel
    page.keyboard.press("Escape")
    row.get_by_test_id("file-menu").click()
    page.get_by_test_id("file-checkout").click()
    expect(row.get_by_test_id("file-status")).to_contain_text("Checked out by you")
    row.get_by_test_id("file-menu").click()
    page.get_by_test_id("file-cancel-checkout").click()
    expect(row.get_by_test_id("file-status")).to_have_text("Available")


def test_word_template_upload_and_export(page: Page, tmp_path):
    login(page, "max", DEMO_PW)
    sample = page.request.get("/api/v1/projects/DEMO/doc-templates/sample.docx")
    assert sample.ok
    path = tmp_path / "corporate.docx"
    path.write_bytes(sample.body())
    page.goto("/p/DEMO/settings")
    page.get_by_test_id("tab-io").click()
    card = page.get_by_test_id("word-templates")
    card.get_by_test_id("template-name").fill("Corporate specification")
    card.get_by_test_id("template-file").click()
    page.locator("input[type=file]").last.set_input_files(str(path))
    card.get_by_test_id("template-upload").click()
    expect(page.get_by_text("Template “Corporate specification” uploaded")).to_be_visible()
    expect(card.get_by_test_id("template-Corporate specification")).to_contain_text("content marker")
    shot(page, "49-word-templates")

    page.goto("/p/DEMO/documents/SPEC-2")
    page.get_by_test_id("doc-export").click()
    page.get_by_test_id("export-docx").click()
    choose(page, "export-template", "Corporate specification")
    with page.expect_download() as dl:
        page.get_by_test_id("export-download").click()
    with zipfile.ZipFile(dl.value.path()) as z:
        document = z.read("word/document.xml").decode("utf-8")
        headers = " ".join(z.read(n).decode("utf-8") for n in z.namelist() if n.startswith("word/header"))
    assert "{{" not in document and "Smart Sensor Platform" in headers
    assert 'TOC \\o' in document and "SYS-" in document
