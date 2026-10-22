"""Live-document features in the browser: time travel, compare, item versions, comments, Word round trip, collections."""

import io

from docx import Document
from docx.oxml.ns import qn
from playwright.sync_api import Page, expect

from conftest import choose, login, shot

DEMO_PW = "demo1234"


def test_time_travel_and_compare(page: Page):
    login(page, "alex", DEMO_PW)
    page.goto("/p/DEMO/documents/SPEC-2")
    expect(page.get_by_test_id("document")).to_contain_text("COM3")
    page.get_by_test_id("doc-history").click()
    expect(page.get_by_test_id("history-drawer")).to_be_visible()
    page.wait_for_timeout(500)  # drawer animation
    shot(page, "21-history")
    page.get_by_test_id("open-baseline-System spec — review 1").click()
    expect(page.get_by_test_id("history-banner")).to_be_visible()
    doc = page.get_by_test_id("document")
    expect(doc).to_contain_text("COM2")
    expect(doc).not_to_contain_text("NAMUR")
    shot(page, "22-baseline-view")
    page.get_by_test_id("compare-with-live").click()
    view = page.get_by_test_id("compare-view")
    expect(view).to_contain_text("changed")
    expect(view.locator(".rich-diff-new ins", has_text="COM3").first).to_be_visible()  # word-level rich-text diff
    expect(view.locator(".rich-diff-old del", has_text="COM2").first).to_be_visible()
    expect(view).to_contain_text("NAMUR")
    shot(page, "23-compare")
    page.goto("/p/DEMO/documents/SPEC-2")
    page.get_by_test_id("doc-filter").fill("IO-Link")
    expect(page.get_by_test_id("filter-count")).to_be_visible()


def test_item_version_view(page: Page):
    login(page, "alex", DEMO_PW)
    page.goto("/p/DEMO/items/SYS-5?tab=history")
    page.get_by_test_id("open-version-1").click()
    expect(page.get_by_test_id("version-banner")).to_be_visible()
    expect(page.get_by_text("COM2")).to_be_visible()
    page.get_by_test_id("version-current").click()
    expect(page.get_by_test_id("version-banner")).to_have_count(0)


def test_document_comment_threads(page: Page):
    login(page, "rita", DEMO_PW)
    page.goto("/p/DEMO/documents/SPEC-2")
    page.get_by_test_id("comments-SYS-2").click()
    expect(page.get_by_text("Is 0.1 % achievable")).to_be_visible()
    expect(page.get_by_text("firmware compensation")).to_be_visible()
    page.wait_for_timeout(500)
    shot(page, "24-comments")
    page.get_by_test_id("reply").click()
    page.get_by_test_id("reply-body").fill("Thanks — resolved.")
    page.get_by_test_id("reply-send").click()
    expect(page.get_by_text("Thanks — resolved.")).to_be_visible()
    page.get_by_test_id("resolve-thread").click()
    expect(page.get_by_text("Show resolved")).to_be_visible()


def test_word_round_trip_ui(page: Page, tmp_path):
    login(page, "alex", DEMO_PW)
    page.goto("/p/DEMO/documents/SPEC-2")
    page.get_by_test_id("doc-export").click()
    page.get_by_test_id("export-review").click()
    with page.expect_download() as dl:
        page.get_by_test_id("roundtrip-download").click()
    doc = Document(dl.value.path())
    # The external reviewer changes the text of the IO-Link requirement (SYS-5, draft).
    sys5 = page.request.get("/api/v1/projects/DEMO/items/SYS-5").json()["id"]
    for sdt in doc.element.body.iter(qn("w:sdt")):
        tag = sdt.find(f"{qn('w:sdtPr')}/{qn('w:tag')}").get(qn("w:val"))
        if tag.startswith(f"alm:{sys5}:") and tag.endswith(":desc"):
            ts = list(sdt.iter(qn("w:t")))
            ts[0].text = "The transmitter shall act as an IO-Link device (COM3) with Smart Sensor Profile 2."
            for t in ts[1:]:
                t.text = ""
    edited = tmp_path / "review.docx"
    doc.save(str(edited))
    page.get_by_test_id("doc-export").click()
    page.get_by_test_id("import-review").click()
    page.get_by_test_id("word-file").click()
    page.locator("input[type=file]").last.set_input_files(str(edited))
    page.get_by_test_id("word-check").click()
    expect(page.get_by_test_id("word-result")).to_contain_text("updated: 1")
    shot(page, "25-word-import")
    page.get_by_test_id("word-apply").click()
    expect(page.get_by_test_id("word-result")).to_contain_text("Applied")
    assert "Smart Sensor Profile 2" in page.request.get("/api/v1/projects/DEMO/items/SYS-5").json()["description"]


def test_collections_ui(page: Page):
    login(page, "rita", DEMO_PW)
    page.goto("/p/DEMO/baselines")
    page.get_by_test_id("tab-collections").click()
    page.get_by_test_id("collection-Release 1.0 (pilot customers)").click()
    detail = page.get_by_test_id("collection-detail")
    expect(detail).to_contain_text("SPEC-1")
    expect(detail).to_contain_text("System spec — review 1")
    shot(page, "26-collections")
    page.get_by_test_id("collection-close").click()
    expect(page.get_by_test_id("collection-Release 1.0 (pilot customers)")).to_contain_text("closed")


def test_recycle_bin_ui(page: Page):
    login(page, "max", DEMO_PW)
    created = page.request.post("/api/v1/projects/DEMO/items", data={"type": "system_requirement", "title": "Temporary requirement",
                                                                       "parent": "H-3"}).json()
    assert page.request.delete(f"/api/v1/projects/DEMO/items/{created['key']}").ok
    page.goto("/p/DEMO/settings")
    page.get_by_test_id("tab-recycle").click()
    page.get_by_test_id(f"restore-{created['key']}").click()
    expect(page.get_by_text("The recycle bin is empty")).to_be_visible()
    page.goto("/p/DEMO/documents/SPEC-2")
    expect(page.get_by_test_id("document")).to_contain_text("Temporary requirement")
