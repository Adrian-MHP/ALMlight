import base64
import hashlib
import hmac
import json

import httpx
from conftest import new_item
from sqlalchemy import text


def test_github_webhook_links_commits(team, project, anon):
    m, c = team["manager"], team["contributor"]
    req = new_item(c, project, "system_requirement", "Measure pressure")
    anon.post(f"/hooks/github/{project}", json={}, expect=404)  # not configured yet
    c.put(f"/projects/{project}/integrations/github", {"enabled": True}, expect=403)
    cfg = m.put(f"/projects/{project}/integrations/github", {"enabled": True})
    secret = cfg["secret"]
    assert cfg["endpoint"].endswith(f"/api/v1/hooks/github/{project}")
    payload = json.dumps({
        "ref": "refs/heads/main", "repository": {"full_name": "acme/firmware"},
        "commits": [{"id": "abc123", "message": f"Implement range check ({req['key']})\n\nDetails",
                     "url": "https://github.com/acme/firmware/commit/abc123", "author": {"name": "Dev"}},
                    {"id": "def456", "message": "Unrelated", "url": "https://x"}],
    }).encode()
    sig = "sha256=" + hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    headers = {"X-GitHub-Event": "push", "Content-Type": "application/json"}
    anon.post(f"/hooks/github/{project}", content=payload, headers={**headers, "X-Hub-Signature-256": "sha256=bad"},
              expect=401)
    res = anon.post(f"/hooks/github/{project}", content=payload, headers={**headers, "X-Hub-Signature-256": sig})
    assert res == {"ok": True, "linked": 1}
    refs = c.get(f"/projects/{project}/items/{req['key']}/external-refs")
    assert refs[0]["kind"] == "commit" and refs[0]["title"].startswith("Implement range check")
    # Redelivery is idempotent.
    anon.post(f"/hooks/github/{project}", content=payload, headers={**headers, "X-Hub-Signature-256": sig})
    assert len(c.get(f"/projects/{project}/items/{req['key']}/external-refs")) == 1


def test_azure_devops_hook(team, project, anon):
    m, c = team["manager"], team["contributor"]
    req = new_item(c, project, "system_requirement", "Measure pressure")
    secret = m.put(f"/projects/{project}/integrations/azure_devops", {"enabled": True})["secret"]
    body = {"eventType": "workitem.updated", "resource": {"workItemId": 4711, "fields": {
        "System.Title": f"Firmware task for {req['key']}", "System.State": "Active"},
        "_links": {"html": {"href": "https://dev.azure.com/acme/_workitems/edit/4711"}}}}
    anon.post(f"/hooks/azure-devops/{project}", json=body, headers={"X-ALMlight-Token": "wrong"}, expect=401)
    basic = base64.b64encode(f"almlight:{secret}".encode()).decode()
    res = anon.post(f"/hooks/azure-devops/{project}", json=body, headers={"Authorization": f"Basic {basic}"})
    assert res["linked"] == 1
    ref = c.get(f"/projects/{project}/items/{req['key']}/external-refs")[0]
    assert (ref["system"], ref["kind"], ref["status"]) == ("azure_devops", "work_item", "Active")


def test_manual_external_refs(team, project):
    c = team["contributor"]
    doc = new_item(c, project, "document", "Housing drawing")
    url = f"/projects/{project}/items/{doc['key']}/external-refs"
    c.post(url, {"system": "pdm", "kind": "cad_model", "url": "https://pdm.example/models/123", "title": "Housing"},
           expect=201)
    c.post(url, {"system": "ftp"}, expect=422)
    c.post(url, {"system": "url", "url": "javascript:alert(1)"}, expect=422)
    refs = c.get(url)
    c.delete(f"{url}/{refs[0]['id']}")
    assert c.get(url) == []


def test_outbound_webhooks(team, project, db):
    from almlight.modules.integrations.service import deliver_pending, sign

    m = team["manager"]
    m.post(f"/projects/{project}/webhooks", {"url": "ftp://x"}, expect=422)
    m.post(f"/projects/{project}/webhooks", {"url": "https://hooks.example/x", "events": ["bogus"]}, expect=422)
    hook = m.post(f"/projects/{project}/webhooks", {"url": "https://hooks.example/almlight",
                                                    "events": ["item.created"]}, expect=201)
    new_item(team["contributor"], project, "system_requirement", "R")
    received = []

    def handler(request: httpx.Request) -> httpx.Response:
        received.append(request)
        return httpx.Response(200)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        deliver_pending(db, client)
    assert len(received) == 1
    body = received[0].content
    assert json.loads(body)["event"] == "item.created"
    assert received[0].headers["X-ALMlight-Signature"] == sign(hook["secret"], body)
    deliveries = m.get(f"/projects/{project}/webhooks/{hook['id']}/deliveries")
    assert deliveries[0]["status_code"] == 200


def test_audit_chain_detects_tampering(team, project, admin, db):
    new_item(team["contributor"], project, "system_requirement", "R")
    assert admin.get("/admin/audit/verify")["ok"] is True
    db.execute(text("UPDATE audit_log SET summary = 'forged' WHERE id = 2"))
    db.commit()
    result = admin.get("/admin/audit/verify")
    assert result["ok"] is False and result["first_broken_id"] == 2
    team["contributor"].get("/admin/audit/verify", expect=403)


def test_config_update_compatibility(team, project, admin):
    cfg = admin.get(f"/projects/{project}/config")["config"]
    new_item(team["contributor"], project, "system_requirement", "R")
    trimmed = dict(cfg, item_types=[t for t in cfg["item_types"] if t["key"] != "system_requirement"])
    trimmed["link_types"] = [
        dict(lt, sources=[s for s in lt["sources"] if s != "system_requirement"],
             targets=[t for t in lt["targets"] if t != "system_requirement"])
        for lt in cfg["link_types"]
    ]
    err = admin.put(f"/projects/{project}/config", {"config": trimmed}, expect=409)
    assert "in use" in err["error"]["details"]["problems"][0]
    broken = dict(cfg, workflows=[])
    admin.put(f"/projects/{project}/config", {"config": broken}, expect=422)
    extended = json.loads(json.dumps(cfg))
    sys_type = next(t for t in extended["item_types"] if t["key"] == "system_requirement")
    sys_type["fields"].append({"key": "cost_center", "label": "Cost center", "type": "string"})
    res = admin.put(f"/projects/{project}/config", {"config": extended})
    assert res["version"] == 2
    item = new_item(team["contributor"], project, "system_requirement", "R2", fields={"cost_center": "4711"})
    assert item["fields"]["cost_center"] == "4711"
    team["contributor"].put(f"/projects/{project}/config", {"config": extended}, expect=403)
