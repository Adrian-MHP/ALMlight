"""Small helpers about an item's lifecycle state, shared by items, links and workflow."""

from __future__ import annotations

from almlight.core.errors import Locked
from almlight.modules.items.models import Item
from almlight.modules.projects.metamodel import StateDef
from almlight.modules.projects.models import Project


def state_def(project: Project, item: Item) -> StateDef | None:
    wf = project.model.workflow_for(item.type_key)
    return wf.state(item.state) if wf else None


def is_frozen(project: Project, item: Item) -> bool:
    s = state_def(project, item)
    return bool(s and s.frozen)


def is_released(project: Project, item: Item) -> bool:
    s = state_def(project, item)
    return bool(s and s.released)


def ensure_editable(project: Project, item: Item) -> None:
    s = state_def(project, item)
    if s and s.frozen:
        hint = "create a new revision" if s.released else "move it back to an editable state"
        raise Locked(
            f"{item.key} is '{s.label}' and therefore frozen — {hint} to change it",
            {"item": item.key, "state": item.state},
        )
