"""German user interface on the server side: complete message catalogue, translated errors, activity, notifications,
e-mail digests, document views and exports, the user's language setting and model label translations."""

import ast
import io
import json
import pathlib
import re
import uuid
import zipfile

from conftest import new_item

from almlight.core import i18n
from almlight.core.config import get_settings

ROOT = pathlib.Path(i18n.__file__).resolve().parents[2]
DE = {"Accept-Language": "de-DE,de;q=0.9,en;q=0.8"}
EXC = {"ValidationFailed", "Conflict", "Forbidden", "NotFound", "Locked", "Unauthorized", "DomainError", "TooManyRequests"}


def _template(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(v.value if isinstance(v, ast.Constant) else "{}" for v in node.values)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        a, b = _template(node.left), _template(node.right)
        return a + b if a is not None and b is not None else None
    return None


def _server_texts():
    """Exception messages, audit summaries and fixed texts (i18n.t) in the source."""
    messages, texts = set(), set()
    for f in (ROOT / "almlight").rglob("*.py"):
        for n in ast.walk(ast.parse(f.read_text())):
            if not isinstance(n, ast.Call):
                continue
            name = n.func.id if isinstance(n.func, ast.Name) else getattr(n.func, "attr", "")
            if name in EXC and n.args:
                t = _template(n.args[0])
                if t and re.search(r"[A-Za-z]{3}", t.replace("{}", "")):
                    messages.add(t)
            if name == "record":
                for kw in n.keywords:
                    t = _template(kw.value) if kw.arg == "summary" else None
                    if t and re.search(r"[A-Za-z]{3}", t.replace("{}", "")):
                        messages.add(t)
            if name == "t" and len(n.args) >= 2 and isinstance(n.args[1], ast.Constant):
                texts.add(n.args[1].value)
    return messages, texts


def test_catalogue_is_complete_and_consistent():
    cat = json.loads((ROOT / "almlight/locales/de.json").read_text("utf-8"))
    messages, texts = _server_texts()
    missing = sorted(messages - set(cat["messages"]))
    assert not missing, f"German translations missing for server messages: {missing[:20]}"
    assert not sorted(texts - set(cat["texts"])), sorted(texts - set(cat["texts"]))
    for en, de in cat["messages"].items():
        parts = en.count("{}")
        assert sorted({int(x) for x in re.findall(r"\{(\d+)\}", de)}) == list(range(1, parts + 1)), (en, de)
    for en, de in cat["texts"].items():
        assert sorted(re.findall(r"\{(\w+)\}", en)) == sorted(re.findall(r"\{(\w+)\}", de)), (en, de)


def test_translation_function():
    assert i18n.tr("Board not found", "de") == "Board nicht gefunden"
    assert i18n.tr("Unknown query field 'color'", "de") == "Unbekanntes Abfragefeld „color“"
    assert i18n.tr("SYS-3 is checked out by alex since 2026-10-01 12:00 UTC", "de") == \
        "SYS-3 ist seit 2026-10-01 12:00 UTC von alex ausgecheckt"  # parts can change their order
    assert i18n.tr("Something new", "de") == "Something new" and i18n.tr("Board not found", "en") == "Board not found"
    assert i18n.parse_accept_language("fr-FR,de;q=0.8") == "de" and i18n.parse_accept_language("") == "en"
    assert i18n.t("de", "page {n}", n=3) == "Seite 3" and i18n.t("en", "page {n}", n=3) == "page 3"


def test_user_language_errors_activity_and_notifications(team, project):
    c, v = team["contributor"], team["viewer"]
    p = f"/projects/{project}"
    # the browser language applies until the user chooses one
    err = c.get(f"{p}/boards/{uuid.uuid4()}", expect=404, headers=DE)
    assert err["error"]["message"] == "Board nicht gefunden"
    assert c.get(f"{p}/boards/{uuid.uuid4()}", expect=404)["error"]["message"] == "Board not found"
    me = c.put("/auth/me/locale", {"locale": "de"})
    assert me["locale"] == "de" and c.get("/auth/me")["locale"] == "de"
    c.put("/auth/me/locale", {"locale": "fr"}, expect=422)
    # the saved language wins over the browser
    assert c.get(f"{p}/boards/{uuid.uuid4()}", expect=404)["error"]["message"] == "Board nicht gefunden"
    bad = c.get(f"{p}/items?ql=color:red", expect=422)
    assert bad["error"]["message"] == "Unbekanntes Abfragefeld „color“"
    # stored summaries are shown in the reader's language; the stored text stays English
    item = new_item(c, project, "system_requirement", "Messbereich")
    v.put(f"{p}/items/{item['key']}/watch")
    c.patch(f"{p}/items/{item['key']}", {"title": "Messbereich 0–10 bar"})
    history = c.get(f"{p}/items/{item['key']}/history")
    assert any(e["summary"].startswith(f"{item['key']} bearbeitet") for e in history), history[:2]
    assert any(e["summary"].startswith("Edited ") for e in v.get(f"{p}/items/{item['key']}/history"))
    notes = v.get("/notifications", headers=DE)["items"]
    assert notes and notes[0]["title"].startswith(f"{item['key']} bearbeitet")
    c.put("/auth/me/locale", {"locale": None})
    assert c.get(f"{p}/boards/{uuid.uuid4()}", expect=404)["error"]["message"] == "Board not found"


def test_model_labels_document_export_and_digest_in_german(team, project, db, monkeypatch):
    from almlight.modules.identity.models import User
    from almlight.modules.notifications import service as notif

    c, m, v = team["contributor"], team["manager"], team["viewer"]
    p = f"/projects/{project}"
    cfg = c.get(f"{p}/config")["config"]
    assert cfg["translations"]["de"]["System Requirement"] == "Systemanforderung"
    # documents and exports use the labels in the reader's language
    spec = new_item(c, project, "specification", "Lastenheft")
    new_item(c, project, "system_requirement", "Druck messen", parent=spec["key"], fields={"priority": "must"})
    doc = c.get(f"{p}/items/{spec['key']}/document", headers=DE)
    node = doc["root"]["children"][0]
    assert node["type_label"] == "Systemanforderung" and node["state"] == "Entwurf"
    assert {"label": "Priorität", "value": "Muss"} in node["fields"] and doc["source"] == "Aktueller Stand"
    docx = c.get(f"{p}/items/{spec['key']}/export.docx", headers=DE).content
    xml = zipfile.ZipFile(io.BytesIO(docx)).read("word/document.xml").decode("utf-8")
    assert "Inhaltsverzeichnis" in xml and "Systemanforderung" in xml and "Projekt" in xml
    assert "Contents" in zipfile.ZipFile(io.BytesIO(c.get(f"{p}/items/{spec['key']}/export.docx").content)).read(
        "word/document.xml").decode("utf-8")
    assert c.get(f"{p}/items/{spec['key']}/export.pdf", headers=DE).content[:4] == b"%PDF"
    # template updates bring missing translations and keep the project's own ones
    own = dict(cfg)
    own["translations"] = {"de": {"System Requirement": "Systemanforderung (Kunde)"}}
    m.put(f"{p}/config", {"config": own})
    upd = m.get(f"{p}/template-updates")
    assert upd["translations"] and upd["translations"][0]["locale"] == "de"
    m.post(f"{p}/template-updates", {})
    de = c.get(f"{p}/config")["config"]["translations"]["de"]
    assert de["System Requirement"] == "Systemanforderung (Kunde)" and de["Draft"] == "Entwurf"
    bad = dict(own, translations={"german": {"Draft": "Entwurf"}})
    m.put(f"{p}/config", {"config": bad}, expect=422)
    # the e-mail digest is written in the recipient's language
    s = get_settings()
    monkeypatch.setattr(s, "smtp_host", "smtp.example.com")
    monkeypatch.setattr(s, "smtp_from", "alm@example.com")
    sent = []
    monkeypatch.setattr(notif, "_send", lambda msg: sent.append(msg))
    user = db.get(User, uuid.UUID(team["users"]["viewer"]["id"]))
    user.email, user.locale = "vic@example.com", "de"
    db.commit()
    item = new_item(c, project, "system_requirement", "Bitte melden")
    v.put(f"{p}/items/{item['key']}/watch")
    c.patch(f"{p}/items/{item['key']}", {"title": "Bitte melden (geändert)"})
    assert notif.send_digests(db, min_age_seconds=0) == 1
    body = sent[0].get_content()
    assert "neue Benachrichtigung" in sent[0]["Subject"] and body.startswith("Hallo ")
    assert f"{item['key']} bearbeitet" in body and "Kontoseite" in body
