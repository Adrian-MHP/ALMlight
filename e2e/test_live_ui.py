"""Rich text, live co-editing, presence and the workspace shell in the browser."""

import re
import struct
import uuid
import zlib

from playwright.sync_api import Browser, Page, expect

from conftest import ADMIN_PASSWORD, BASE_URL, login, logout, shot

DEMO_PW = "demo1234"


def png_bytes(w: int = 48, h: int = 24, rgb: tuple = (14, 110, 118)) -> bytes:
    raw = b"".join(b"\x00" + bytes(rgb) * w for _ in range(h))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def paste_html(page: Page, selector: str, html: str) -> None:
    page.eval_on_selector(selector, """(el, html) => {
        const dt = new DataTransfer();
        dt.setData('text/html', html);
        dt.setData('text/plain', html.replace(/<[^>]+>/g, ' '));
        el.dispatchEvent(new ClipboardEvent('paste', { clipboardData: dt, bubbles: true, cancelable: true }));
    }""", html)


def new_context_page(browser: Browser) -> Page:
    ctx = browser.new_context(base_url=BASE_URL, viewport={"width": 1440, "height": 900})
    return ctx.new_page()


def test_home_and_app_launcher(page: Page):
    login(page, "alex", DEMO_PW)
    expect(page.get_by_test_id("product-name")).to_have_text("Ariadne")
    expect(page.get_by_test_id("home-greeting")).to_contain_text("Alex")
    expect(page.get_by_test_id("tile-projects")).to_contain_text("1")
    expect(page.get_by_test_id("live-indicator")).to_have_class(re.compile("is-on"))
    shot(page, "30-home")
    page.get_by_test_id("app-launcher").click()
    expect(page.get_by_test_id("app-tile-documents")).to_be_visible()
    page.wait_for_timeout(400)  # popover transition
    shot(page, "31-launcher")
    page.get_by_test_id("app-tile-documents").click()
    expect(page).to_have_url(re.compile(r"/p/DEMO/documents$"))
    page.get_by_test_id("nav-collapse").click()  # icon rail
    expect(page.get_by_test_id("nav-items")).not_to_contain_text("Items")
    page.get_by_test_id("nav-collapse").click()
    expect(page.get_by_test_id("nav-items")).to_contain_text("Items")


def test_rich_text_with_image_table_and_reference(page: Page):
    login(page, "alex", DEMO_PW)
    page.goto("/p/DEMO/items/SYS-7")
    page.get_by_test_id("edit-text").click()
    expect(page.get_by_test_id("live-status")).to_contain_text("Live")
    body = '[data-testid="live-editor-body"] .ProseMirror'
    page.locator(body).click()
    page.keyboard.press("Control+End")
    page.keyboard.press("Enter")
    page.keyboard.type("Applies to ")
    page.keyboard.press("Control+b")
    page.keyboard.type("all SIL variants")
    page.keyboard.press("Control+b")
    page.keyboard.type(", see #SYS-6")
    expect(page.get_by_test_id("item-suggest")).to_be_visible()
    page.get_by_test_id("suggest-SYS-6").click()
    expect(page.locator(f"{body} span[data-type='item-ref']")).to_have_text("SYS-6")
    paste_html(page, body, "<table><tr><th>Mode</th><th>Diagnostic coverage</th></tr><tr><td>SIL 2</td><td>90 %</td></tr></table>")
    expect(page.locator(f"{body} table")).to_be_visible()
    with page.expect_file_chooser() as fc:
        page.get_by_test_id("rte-image").click()
    fc.value.set_files(files=[{"name": "architecture.png", "mimeType": "image/png", "buffer": png_bytes()}])
    expect(page.locator(f"{body} img[src^='/api/v1/images/']")).to_be_visible()
    shot(page, "32-rich-text-editor")
    page.get_by_test_id("live-done").click()
    view = page.get_by_test_id("item-description-view")
    expect(view.locator("strong")).to_have_text("all SIL variants")
    expect(view.locator("table th").first).to_have_text("Mode")
    img = view.locator("img")
    expect(img).to_be_visible()
    assert img.evaluate("el => el.complete && el.naturalWidth") == 48  # served through the access-checked image store
    expect(page.get_by_test_id("item-version")).to_have_text(re.compile(r"A\.[2-9]"))
    stored = page.request.get("/api/v1/projects/DEMO/items/SYS-7").json()["description"]
    assert '<span data-type="item-ref" data-key="SYS-6">SYS-6</span>' in stored and "<table>" in stored
    view.locator("span[data-type='item-ref']").click()  # references navigate
    expect(page).to_have_url(re.compile(r"/items/SYS-6$"))


def test_two_people_co_edit_a_document_block(page: Page, browser: Browser):
    login(page, "alex", DEMO_PW)
    rita = new_context_page(browser)
    login(rita, "rita", DEMO_PW)
    page.goto("/p/DEMO/documents/SPEC-2")
    rita.goto("/p/DEMO/documents/SPEC-2")
    expect(page.get_by_test_id("doc-presence")).to_contain_text("2")  # both in the document
    before = page.request.get("/api/v1/projects/DEMO/items/SYS-4").json()["version"]

    page.get_by_test_id("block-SYS-4").hover()
    page.get_by_test_id("edit-SYS-4").click()
    alex_body = page.locator('[data-testid="live-SYS-4-body"] .ProseMirror')
    expect(alex_body).to_have_attribute("contenteditable", "true")
    expect(rita.get_by_test_id("block-editors-SYS-4")).to_contain_text("Alex Engineer editing live")

    rita.get_by_test_id("block-SYS-4").hover()
    rita.get_by_test_id("edit-SYS-4").click()
    rita_body = rita.locator('[data-testid="live-SYS-4-body"] .ProseMirror')
    expect(rita_body).to_have_attribute("contenteditable", "true")

    alex_body.click()
    page.keyboard.press("Control+End")
    page.keyboard.type(" Alex adds HART 7 diagnostics.")
    expect(rita_body).to_contain_text("Alex adds HART 7 diagnostics.")  # instantly, without saving
    rita_body.click()
    rita.keyboard.press("Control+Home")
    rita.keyboard.type("[Reviewed] ")
    expect(alex_body).to_contain_text("[Reviewed]")
    expect(rita.locator(".collaboration-carets__label").first).to_be_visible()  # the other's caret with name
    expect(rita.get_by_test_id("live-SYS-4")).to_contain_text("Alex Engineer is editing too")
    page.wait_for_timeout(400)
    shot(page, "33-coediting-alex")
    shot(rita, "34-coediting-rita")

    rita.get_by_test_id("live-save").click()  # one version with both contributions
    expect(rita.get_by_text(re.compile(r"Saved SYS-4 as version A\.\d"))).to_be_visible()
    after = page.request.get("/api/v1/projects/DEMO/items/SYS-4").json()
    assert after["version"] != before
    assert "[Reviewed]" in after["description"] and "Alex adds HART 7 diagnostics." in after["description"]
    versions = page.request.get("/api/v1/projects/DEMO/items/SYS-4/versions").json()
    assert versions[0]["change_note"].startswith("Live co-editing with")
    page.get_by_test_id("live-done").click()
    rita.get_by_test_id("live-done").click()
    expect(page.get_by_test_id("block-SYS-4")).to_contain_text("[Reviewed]")
    rita.context.close()


def test_live_refresh_and_session_saved_on_leave(page: Page, browser: Browser):
    login(page, "alex", DEMO_PW)
    page.goto("/p/DEMO/documents/SPEC-2")
    expect(page.get_by_test_id("document")).to_be_visible()
    # Someone else changes a title through the API: the open document updates itself and says who did it.
    max_ = new_context_page(browser)
    login(max_, "max", DEMO_PW)
    title = f"Support a SIL 2 safety function ({uuid.uuid4().hex[:4]})"
    item = max_.request.get("/api/v1/projects/DEMO/items/SYS-7").json()
    assert max_.request.patch("/api/v1/projects/DEMO/items/SYS-7", data={"title": title}).ok, item
    expect(page.get_by_test_id("block-SYS-7")).to_contain_text(title)
    expect(page.get_by_text("max changed the document")).to_be_visible()

    # An editor leaves without saving: the session is saved as a version shortly after.
    max_.goto("/p/DEMO/items/SYS-7")
    max_.get_by_test_id("edit-text").click()
    body = max_.locator('[data-testid="live-editor-body"] .ProseMirror')
    expect(body).to_have_attribute("contenteditable", "true")
    body.click()
    max_.keyboard.press("Control+End")
    max_.keyboard.type(" Saved when the session ended.")
    max_.wait_for_timeout(300)
    max_.context.close()
    expect(page.get_by_test_id("block-SYS-7")).to_contain_text("Saved when the session ended.", timeout=30_000)


def test_viewer_gets_read_only_live_view(page: Page):
    login(page, "admin", ADMIN_PASSWORD)
    name = f"v{uuid.uuid4().hex[:6]}"
    user = page.request.post("/api/v1/users", data={"username": name, "display_name": "Vera Viewer", "password": "password-123"}).json()
    assert page.request.put("/api/v1/projects/DEMO/members", data={"user_id": user["id"], "role": "viewer"}).ok
    logout(page)
    login(page, name, "password-123")
    page.goto("/p/DEMO/items/SYS-5")
    page.get_by_test_id("edit-text").click()
    editor = page.get_by_test_id("live-editor")
    expect(editor).to_contain_text("Read-only")
    expect(editor.locator('[data-testid="live-editor-body"] .ProseMirror')).to_have_attribute("contenteditable", "false")
    expect(page.get_by_test_id("live-save")).to_have_count(0)
