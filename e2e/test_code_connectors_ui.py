"""Git interface (Code page, linked revisions, branch for an item, commit query) and connectors (Enterprise
Architect import with mapping wizard, medini analyze HARA) in the browser."""

import re

from playwright.sync_api import Page, expect

from conftest import login, shot

DEMO_PW = "demo1234"
API = "/api/v1/projects/DEMO"


def test_code_page_linked_revisions_and_branch(page: Page):
    login(page, "alex", DEMO_PW)
    repo = page.request.get(f"{API}/repositories").json()[0]
    assert repo["name"] == "sensor-firmware" and repo["commit_count"] >= 9
    page.goto("/p/DEMO/code")
    expect(page.get_by_test_id("repo-status")).to_contain_text("commits")
    commits = page.get_by_test_id("commit-list")
    expect(commits).to_contain_text("Implement measuring ranges")
    # commit view: message, linked item, diff
    page.get_by_test_id("commit-search").fill("measuring ranges")
    row = commits.locator("tbody tr").first
    expect(row).to_contain_text("Implement measuring ranges")
    range_key = re.search(r"\(([A-Z]+-\d+)\)", row.inner_text()).group(1)
    row.locator("button").first.click()
    view = page.get_by_test_id("commit-view")
    expect(view.get_by_test_id("commit-items")).to_contain_text(range_key)
    expect(view.get_by_test_id("diff-src/pressure.c")).to_contain_text("FULL_SCALE_MBAR")
    shot(page, "70-code-commit")
    page.get_by_test_id("commit-back").click()
    # files: browse into src and open a file; branches show the item in the feature branch name
    page.get_by_test_id("code-tab-files").click()
    page.get_by_test_id("file-tree").get_by_test_id("tree-src").click()
    page.get_by_test_id("file-tree").get_by_test_id("tree-pressure.c").click()
    expect(page.get_by_test_id("file-view")).to_contain_text("pressure_in_range")
    page.get_by_test_id("code-tab-branches").click()
    expect(page.get_by_test_id("branch-list")).to_contain_text("hart-diagnostics")
    expect(page.get_by_test_id("branch-list")).to_contain_text("v0.9.0")
    # the item shows its linked revisions; create a branch for it (local demo repository accepts pushes)
    page.goto(f"/p/DEMO/items/{range_key}?tab=development")
    revs = page.get_by_test_id("revision-list")
    expect(revs).to_contain_text("Implement measuring ranges")
    page.get_by_test_id("revision-create-branch").click()
    expect(page.get_by_test_id("revision-branch").first).to_contain_text(f"feature/{range_key}")
    shot(page, "71-linked-revisions")
    # link an unrelated commit by hand, then remove it again
    readme = page.request.get(f"{API}/repositories/{repo['id']}/commits?q=README").json()["commits"][0]
    page.get_by_test_id("revision-sha").fill(readme["short"])
    page.get_by_test_id("revision-link").click()
    expect(revs).to_contain_text("Update README")
    revs.get_by_test_id(f"revision-{readme['short']}").get_by_test_id("revision-unlink").click()
    expect(revs).not_to_contain_text("Update README")
    # the query finds items with linked commits
    keys = {i["key"] for i in page.request.get(f"{API}/items?ql=commits:true&limit=100").json()["items"]}
    assert range_key in keys


def test_connectors_ea_import_and_medini_hara(page: Page):
    login(page, "max", DEMO_PW)
    page.goto("/p/DEMO/connectors")
    page.get_by_test_id("conn-ea-import").click()
    wizard = page.get_by_test_id("conn-wizard")
    wizard.get_by_test_id("conn-file").click()
    page.set_input_files("input[type=file]", "/samples/enterprise-architect/pressure-transmitter.qea")
    wizard.get_by_test_id("conn-preview-run").click()
    expect(wizard.get_by_test_id("conn-types")).to_contain_text("Requirement«functionalRequirement»")
    expect(wizard.get_by_test_id("conn-preview")).to_contain_text("8 new")
    shot(page, "72-ea-import-wizard")
    wizard.get_by_test_id("conn-apply").click()
    expect(page.get_by_text(re.compile(r"Imported: 8 created"))).to_be_visible()
    found = page.request.get(f"{API}/items?q=gauge&limit=50").json()["items"]
    assert any(i["title"] == "Measure gauge pressure" for i in found)
    xmi = page.request.get(f"{API}/connectors/ea/export.xmi")
    assert xmi.ok and b"Enterprise Architect" in xmi.body()
    # medini analyze HARA: hazards with the computed ASIL and safety goals
    page.get_by_test_id("conn-medini-hara").click()
    wizard = page.get_by_test_id("conn-wizard")
    page.set_input_files("input[type=file]", "/samples/medini-analyze/hara.xlsx")
    wizard.get_by_test_id("conn-preview-run").click()
    expect(wizard.get_by_test_id("conn-preview")).to_contain_text("HE-003")  # the ASIL mismatch is reported
    wizard.get_by_test_id("conn-apply").click()
    expect(page.get_by_text(re.compile(r"Imported: 4 created"))).to_be_visible()
    hazards = page.request.get(f"{API}/items?type=hazard").json()["items"]
    assert len(hazards) == 3
