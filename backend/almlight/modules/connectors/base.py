"""Connector framework: tools outside Ariadne (Enterprise Architect, medini analyze, SysML v2 servers, …) deliver a
neutral model of objects and relations; one pipeline maps it onto the project's information model.

Each connector parses its source into an :class:`ExtModel`. Objects keep a stable id from the source (EA GUID,
medini ID, SysML element id); the import stores it as an external reference of the item (system = connector key),
so a later import updates the same items instead of duplicating them.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ExtObject:
    ext_id: str
    kind: str                                   # source type, e.g. "Requirement", "Class«block»", "PartUsage"
    name: str
    text: str = ""                              # plain text or HTML (``html=True``)
    fields: dict[str, Any] = field(default_factory=dict)
    parent: str | None = None                   # ext_id of the containing package / element
    path: list[str] = field(default_factory=list)
    url: str | None = None
    html: bool = False

    def digest(self) -> str:
        raw = json.dumps([self.kind, self.name, self.text, self.fields], sort_keys=True, default=str)
        return hashlib.sha1(raw.encode()).hexdigest()


@dataclass
class ExtRelation:
    kind: str
    source: str                                 # ext_id, or "key:SYS-12" for an existing Ariadne item
    target: str
    ext_id: str | None = None


@dataclass
class ExtModel:
    system: str
    source: str                                 # file name or server/project label
    objects: list[ExtObject] = field(default_factory=list)
    relations: list[ExtRelation] = field(default_factory=list)
    packages: list[dict[str, Any]] = field(default_factory=list)   # [{id, name, path}] for write-back targets
    warnings: list[str] = field(default_factory=list)


@dataclass
class Suggestion:
    """Default mapping of a connector: source kind -> item type, relation kind -> link type ("link:reverse")."""

    types: dict[str, str | None] = field(default_factory=dict)
    relations: dict[str, str | None] = field(default_factory=dict)


CATALOGUE: list[dict[str, Any]] = [
    {"key": "git", "name": "Git (GitHub, GitLab, Bitbucket, Azure Repos)", "vendor": "any", "kind": "server",
     "directions": ["import"], "formats": ["HTTPS clone URL"], "page": "code",
     "description": "Repositories on the Code page; commits mentioning item keys become linked revisions."},
    {"key": "ea", "name": "Enterprise Architect", "vendor": "Sparx Systems", "kind": "file",
     "directions": ["import", "export"], "formats": [".qea", ".qeax", ".xmi", ".xml"],
     "description": "Requirements, blocks, components, activities and their traces from EA models; export as EA XMI "
                    "or written back into a .qea model."},
    {"key": "medini", "name": "medini analyze", "vendor": "Ansys", "kind": "file",
     "directions": ["import", "export"], "formats": [".xlsx", ".csv", ".reqif"],
     "description": "Hazard analysis (HARA) with ASIL, FMEA worksheets and safety requirements (ReqIF)."},
    {"key": "sysml", "name": "SysML v2 API", "vendor": "OMG standard (SysON, Cameo, …)", "kind": "server",
     "directions": ["import"], "formats": ["SysML v2 REST API"],
     "description": "Requirement, part, action, interface and verification definitions and usages with satisfy "
                    "relations from a SysML v2 server."},
    {"key": "reqif", "name": "ReqIF (DOORS, Polarion, codebeamer, …)", "vendor": "OMG standard", "kind": "file",
     "directions": ["import", "export"], "formats": [".reqif", ".reqifz"], "page": "settings",
     "description": "Requirements interchange with mapping wizard (Settings → Import / Export)."},
]


def norm(s: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def clean_text(s: str) -> str:
    """Text from model tools: drop comment decorations (`` * `` at line starts) and surplus blank lines."""
    lines = [re.sub(r"^\s*\*\s?", "", line).rstrip() for line in (s or "").replace("\r\n", "\n").split("\n")]
    text = "\n".join(lines).strip()
    return re.sub(r"\n{3,}", "\n\n", text)
