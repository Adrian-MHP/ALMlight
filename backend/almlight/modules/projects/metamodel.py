"""Configurable information model ("process template").

A template defines the item types (with their fields), link types and lifecycle workflows
of a project. Customer tailoring happens here — in data, not in code. Templates are YAML
files shipped in ``templates/`` and copied into each project as JSON, so a project keeps
working even when the shipped template evolves.
"""

from __future__ import annotations

import re
from functools import cached_property
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Role = Literal["viewer", "contributor", "reviewer", "manager"]
ROLE_RANK: dict[str, int] = {"viewer": 0, "contributor": 1, "reviewer": 2, "manager": 3}

FieldType = Literal[
    "string", "text", "integer", "number", "boolean", "date", "enum", "multienum", "tags", "user", "url"
]
ItemCategory = Literal["requirement", "architecture", "verification", "change", "document", "variability", "other"]
StateCategory = Literal["draft", "review", "released", "obsolete", "open", "in_progress", "closed"]

KEY_RE = r"^[a-z][a-z0-9_]{0,48}$"
TEMPLATES_DIR = Path(__file__).parent / "templates"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class EnumOption(_Strict):
    key: str
    label: str
    color: str | None = None


class FieldDef(_Strict):
    key: str = Field(pattern=KEY_RE)
    label: str
    type: FieldType = "string"
    required: bool = False
    options: list[EnumOption] = Field(default_factory=list)
    default: Any = None
    pattern: str | None = None
    help: str | None = None

    @field_validator("options", mode="before")
    @classmethod
    def _shorthand_options(cls, v: Any) -> Any:
        # Allow `options: [must, should]` as shorthand for key == label.
        if isinstance(v, list):
            return [{"key": o, "label": o.replace("_", " ").capitalize()} if isinstance(o, str) else o for o in v]
        return v

    @model_validator(mode="after")
    def _check(self) -> FieldDef:
        if self.type in ("enum", "multienum") and not self.options:
            raise ValueError(f"field '{self.key}' of type {self.type} needs options")
        if self.pattern:
            re.compile(self.pattern)
        return self

    def option_keys(self) -> set[str]:
        return {o.key for o in self.options}


class StateDef(_Strict):
    key: str = Field(pattern=KEY_RE)
    label: str
    category: StateCategory = "draft"
    initial: bool = False
    frozen: bool = False
    released: bool = False
    implementation_open: bool = False
    color: str | None = None


class ApprovalDef(_Strict):
    roles: list[Role] = Field(default_factory=lambda: ["reviewer"])
    count: int = Field(default=1, ge=1, le=10)
    signature: bool = False
    allow_self_approval: bool = False
    reject_to: str | None = None


class TransitionDef(_Strict):
    key: str = Field(pattern=KEY_RE)
    label: str
    from_: list[str] = Field(alias="from")
    to: str
    min_role: Role = "contributor"
    approval: ApprovalDef | None = None
    signature: bool = False
    comment_required: bool = False
    guards: list[str] = Field(default_factory=list)
    effects: list[str] = Field(default_factory=list)


KNOWN_GUARDS = {"contained_items_released", "has_affected_items", "affected_items_revised", "all_records_executed"}
KNOWN_EFFECTS = {"release_affected_items"}


class WorkflowDef(_Strict):
    key: str = Field(pattern=KEY_RE)
    label: str
    states: list[StateDef]
    transitions: list[TransitionDef] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check(self) -> WorkflowDef:
        keys = [s.key for s in self.states]
        if len(keys) != len(set(keys)):
            raise ValueError(f"workflow '{self.key}' has duplicate states")
        if sum(1 for s in self.states if s.initial) != 1:
            raise ValueError(f"workflow '{self.key}' needs exactly one initial state")
        tkeys = [t.key for t in self.transitions]
        if len(tkeys) != len(set(tkeys)):
            raise ValueError(f"workflow '{self.key}' has duplicate transitions")
        for t in self.transitions:
            for s in [*t.from_, t.to] + ([t.approval.reject_to] if t.approval and t.approval.reject_to else []):
                if s not in keys:
                    raise ValueError(f"workflow '{self.key}': transition '{t.key}' references unknown state '{s}'")
            unknown = (set(t.guards) - KNOWN_GUARDS) | (set(t.effects) - KNOWN_EFFECTS)
            if unknown:
                raise ValueError(f"workflow '{self.key}': transition '{t.key}' uses unknown guards/effects {unknown}")
        return self

    def state(self, key: str | None) -> StateDef | None:
        return next((s for s in self.states if s.key == key), None)

    @property
    def initial_state(self) -> StateDef:
        return next(s for s in self.states if s.initial)

    @property
    def released_state(self) -> StateDef | None:
        return next((s for s in self.states if s.released), None)

    def transition(self, key: str) -> TransitionDef | None:
        return next((t for t in self.transitions if t.key == key), None)


class ItemTypeDef(_Strict):
    key: str = Field(pattern=KEY_RE)
    label: str
    prefix: str = Field(pattern=r"^[A-Z][A-Z0-9]{0,7}$")
    category: ItemCategory = "other"
    description: str | None = None
    icon: str | None = None
    color: str | None = None
    workflow: str | None = None
    change_controlled: bool = False
    document: bool = False
    fields: list[FieldDef] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check(self) -> ItemTypeDef:
        keys = [f.key for f in self.fields]
        if len(keys) != len(set(keys)):
            raise ValueError(f"item type '{self.key}' has duplicate fields")
        return self

    def field(self, key: str) -> FieldDef | None:
        return next((f for f in self.fields if f.key == key), None)


class LinkTypeDef(_Strict):
    key: str = Field(pattern=KEY_RE)
    label: str
    reverse_label: str
    description: str | None = None
    sources: list[str] = Field(default_factory=lambda: ["*"])
    targets: list[str] = Field(default_factory=lambda: ["*"])
    structural: bool = False
    acyclic: bool = False
    suspect_on_target_change: bool = False
    editable_on_frozen_source: bool = False
    attributes: list[FieldDef] = Field(default_factory=list)

    def allows(self, source_type: str, target_type: str) -> bool:
        return ("*" in self.sources or source_type in self.sources) and (
            "*" in self.targets or target_type in self.targets
        )


class Semantics(_Strict):
    """Binds engine features (change control, verification, variants, maturity) to configured keys.

    Defaults follow the shipped templates; a tailored template can rename its types and links and
    point the engine at them here.
    """

    affects_link: str = "affects"
    implements_link: str = "implements"
    verifies_link: str = "verifies"
    satisfies_link: str = "satisfies"
    derives_link: str = "derives_from"
    requires_link: str = "requires"
    excludes_link: str = "excludes"
    heading_type: str | None = "heading"
    test_case_types: list[str] = Field(default_factory=lambda: ["test_case"])
    test_run_type: str | None = "test_run"
    stakeholder_types: list[str] = Field(default_factory=lambda: ["stakeholder_requirement"])
    element_types: list[str] = Field(default_factory=lambda: ["system_element"])


class ProjectTemplate(_Strict):
    key: str = Field(pattern=KEY_RE)
    label: str
    description: str | None = None
    version: int = 1
    revision_scheme: Literal["letters", "numbers"] = "letters"
    item_types: list[ItemTypeDef]
    link_types: list[LinkTypeDef] = Field(default_factory=list)
    workflows: list[WorkflowDef] = Field(default_factory=list)
    semantics: Semantics = Field(default_factory=Semantics)

    @model_validator(mode="after")
    def _check(self) -> ProjectTemplate:
        type_keys = [t.key for t in self.item_types]
        if len(type_keys) != len(set(type_keys)):
            raise ValueError("duplicate item type keys")
        prefixes = [t.prefix for t in self.item_types]
        if len(prefixes) != len(set(prefixes)):
            raise ValueError("duplicate item type prefixes")
        link_keys = [lt.key for lt in self.link_types]
        if len(link_keys) != len(set(link_keys)):
            raise ValueError("duplicate link type keys")
        wf_keys = {w.key for w in self.workflows}
        if len(wf_keys) != len(self.workflows):
            raise ValueError("duplicate workflow keys")
        for t in self.item_types:
            if t.workflow and t.workflow not in wf_keys:
                raise ValueError(f"item type '{t.key}' references unknown workflow '{t.workflow}'")
        tk = set(type_keys)
        for lt in self.link_types:
            for ref in [*lt.sources, *lt.targets]:
                if ref != "*" and ref not in tk:
                    raise ValueError(f"link type '{lt.key}' references unknown item type '{ref}'")
        return self

    # --- lookups -----------------------------------------------------------------
    @cached_property
    def _types(self) -> dict[str, ItemTypeDef]:
        return {t.key: t for t in self.item_types}

    @cached_property
    def _links(self) -> dict[str, LinkTypeDef]:
        return {lt.key: lt for lt in self.link_types}

    @cached_property
    def _workflows(self) -> dict[str, WorkflowDef]:
        return {w.key: w for w in self.workflows}

    def item_type(self, key: str) -> ItemTypeDef | None:
        return self._types.get(key)

    def link_type(self, key: str) -> LinkTypeDef | None:
        return self._links.get(key)

    def workflow(self, key: str | None) -> WorkflowDef | None:
        return self._workflows.get(key) if key else None

    def workflow_for(self, type_key: str) -> WorkflowDef | None:
        t = self.item_type(type_key)
        return self.workflow(t.workflow) if t else None

    def structural_link_types(self) -> list[str]:
        return [lt.key for lt in self.link_types if lt.structural]


def load_template_file(path: Path) -> ProjectTemplate:
    with path.open(encoding="utf-8") as fh:
        return ProjectTemplate.model_validate(yaml.safe_load(fh))


def available_templates() -> dict[str, ProjectTemplate]:
    return {t.key: t for t in (load_template_file(p) for p in sorted(TEMPLATES_DIR.glob("*.yaml")))}


def parse_config(data: dict[str, Any]) -> ProjectTemplate:
    return ProjectTemplate.model_validate(data)


def dump_config(template: ProjectTemplate) -> dict[str, Any]:
    return template.model_dump(mode="json", by_alias=True)
