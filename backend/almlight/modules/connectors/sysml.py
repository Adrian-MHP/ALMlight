"""SysML v2 API (OMG Systems Modeling API and Services) — SysON, Cameo/MagicDraw with SysML v2, and other servers.

Reads the latest commit of a project: requirement, concern, part, action, interface, port, use case and verification
definitions and usages with their names, short names (requirement ids), texts and documentation; satisfy relations
(``SatisfyRequirementUsage``), part decomposition (part owned by a part) and sub-requirements. Elements are
identified by their element id. Large models are cached for an hour so that the preview and the import read the
model once.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from almlight.core.config import get_settings
from almlight.core.errors import ValidationFailed
from almlight.modules.connectors.base import ExtModel, ExtObject, ExtRelation, Suggestion, clean_text
from almlight.modules.projects.models import Project

SYSTEM = "sysml"
KEEP = {"RequirementDefinition", "RequirementUsage", "ConcernDefinition", "ConcernUsage", "PartDefinition",
        "PartUsage", "ActionDefinition", "ActionUsage", "InterfaceDefinition", "InterfaceUsage", "PortDefinition",
        "UseCaseDefinition", "UseCaseUsage", "VerificationCaseDefinition", "VerificationCaseUsage"}
CACHE_SECONDS = 3600


def check_base(url: str) -> str:
    url = (url or "").strip().rstrip("/")
    u = urlparse(url)
    if u.scheme not in ("http", "https") or not u.hostname:
        raise ValidationFailed("Enter the base URL of the SysML v2 server, e.g. http://host.docker.internal:8080")
    return url


def _client(token: str | None) -> httpx.Client:
    headers = {"Accept": "application/json", "User-Agent": "Ariadne-ALM"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return httpx.Client(timeout=httpx.Timeout(600.0, connect=10.0), headers=headers, follow_redirects=False)


def _get(client: httpx.Client, url: str) -> Any:
    try:
        resp = client.get(url)
    except httpx.HTTPError as exc:
        raise ValidationFailed(f"The SysML v2 server is not reachable: {exc}") from None
    if resp.status_code != 200:
        raise ValidationFailed(f"The SysML v2 server answered {resp.status_code} for {urlparse(url).path}")
    try:
        return resp.json()
    except ValueError:
        raise ValidationFailed("The SysML v2 server did not answer with JSON") from None


def list_projects(base: str, token: str | None) -> list[dict[str, Any]]:
    with _client(token) as client:
        data = _get(client, f"{check_base(base)}/api/rest/projects")
    return [{"id": p.get("@id"), "name": p.get("name"), "description": p.get("description")}
            for p in data if isinstance(p, dict)]


def _cache_file(base: str, project_id: str, commit: str) -> Path:
    key = hashlib.sha1(f"{base}|{project_id}|{commit}".encode()).hexdigest()
    return get_settings().data_dir / "connector-cache" / f"sysml-{key}.json"


def fetch(base: str, project_id: str, token: str | None,
          refresh: bool = False) -> tuple[list[dict[str, Any]], str, str]:
    """All elements of the latest commit (cached). Returns (elements, project name, commit id)."""
    base = check_base(base)
    with _client(token) as client:
        projects = {p.get("@id"): p for p in _get(client, f"{base}/api/rest/projects") if isinstance(p, dict)}
        if project_id not in projects:
            raise ValidationFailed("The SysML v2 project does not exist on the server")
        commits = _get(client, f"{base}/api/rest/projects/{project_id}/commits")
        if not commits:
            raise ValidationFailed("The SysML v2 project has no commits")
        commit = sorted(commits, key=lambda c: c.get("created") or "")[-1]["@id"]
        cache = _cache_file(base, project_id, commit)
        if not refresh and cache.exists() and time.time() - cache.stat().st_mtime < CACHE_SECONDS:
            elements = json.loads(cache.read_text())
        else:
            elements = _get(client, f"{base}/api/rest/projects/{project_id}/commits/{commit}/elements")
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(elements))
    return elements, projects[project_id].get("name") or project_id, commit


def to_model(elements: list[dict[str, Any]], base: str, project_id: str, project_name: str) -> ExtModel:
    by_id = {e.get("@id"): e for e in elements if isinstance(e, dict)}
    model = ExtModel(system=SYSTEM, source=f"{project_name} ({urlparse(base).netloc})")
    url = f"{base}/projects/{project_id}/edit"

    def ref(v: Any) -> str | None:
        return v.get("@id") if isinstance(v, dict) else None

    def text_of(e: dict[str, Any]) -> str:
        parts = [t for t in (e.get("text") or []) if isinstance(t, str) and t.strip()]
        if not parts:
            for d in e.get("documentation") or []:
                body = (by_id.get(ref(d)) or {}).get("body")
                if body:
                    parts.append(body)
        return clean_text("\n\n".join(parts))

    kept: set[str] = set()
    for e in elements:
        t = e.get("@type")
        if t not in KEEP:
            continue
        text = text_of(e)
        name = e.get("declaredName") or e.get("name") or e.get("reqId") or e.get("declaredShortName")
        if not name:
            if not text:
                continue  # anonymous structural usage
            name = text.split("\n")[0][:80]
        short = e.get("reqId") or e.get("declaredShortName")
        fields = {k: v for k, v in (("id", short), ("qualified_name", e.get("qualifiedName"))) if v}
        path = (e.get("qualifiedName") or "").split("::")[:-1]
        model.objects.append(ExtObject(ext_id=e["@id"], kind=t, name=f"{short} {name}" if short and short not in name
                                       else name, text=text, fields=fields, parent=ref(e.get("owner")), path=path,
                                       url=url))
        kept.add(e["@id"])
    for e in elements:
        t, owner = e.get("@type"), ref(e.get("owner"))
        if t == "SatisfyRequirementUsage":
            req = ref(e.get("satisfiedRequirement"))
            by = ref(e.get("satisfyingFeature")) or owner
            if req in kept and by in kept:
                model.relations.append(ExtRelation(kind="satisfy", source=by, target=req, ext_id=e.get("@id")))  # type: ignore[arg-type]
        elif e.get("@id") in kept and owner in kept:
            parent_type = by_id[owner].get("@type", "")
            if t in ("PartUsage", "PartDefinition") and parent_type.startswith("Part"):
                model.relations.append(ExtRelation(kind="part of", source=e["@id"], target=owner))  # type: ignore[arg-type]
            elif t.startswith("Requirement") and parent_type.startswith("Requirement"):
                model.relations.append(ExtRelation(kind="subrequirement of", source=e["@id"], target=owner))  # type: ignore[arg-type]
    return model


def suggestion(project: Project, model: ExtModel) -> Suggestion:
    has = lambda key: key if project.model.item_type(key) is not None else None  # noqa: E731
    types = {}
    for kind in {o.kind for o in model.objects}:
        if kind.startswith(("Requirement", "Concern")):
            types[kind] = has("system_requirement")
        elif kind.startswith("Part"):
            types[kind] = has("system_element")
        elif kind.startswith("Action"):
            types[kind] = has("function")
        elif kind.startswith(("Interface", "Port")):
            types[kind] = has("interface")
        elif kind.startswith("UseCase"):
            types[kind] = has("stakeholder_requirement")
        elif kind.startswith("VerificationCase"):
            types[kind] = has("test_case")
    return Suggestion(types=types, relations={"satisfy": "satisfies", "part of": "contains:reverse",
                                              "subrequirement of": "derives_from"})
