"""REST API of the architecture diagrams."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from almlight.core.db import get_db
from almlight.core.deps import current_user
from almlight.core.schemas import UserDirectory
from almlight.modules.diagrams import service, svg
from almlight.modules.identity.models import User
from almlight.modules.items.models import Item
from almlight.modules.items.schemas import items_out
from almlight.modules.projects.access import get_project
from almlight.modules.projects.models import Project

router = APIRouter(prefix="/projects/{project_key}/diagrams", tags=["architecture diagrams"])


class Content(BaseModel):
    model_config = ConfigDict(extra="forbid")
    nodes: list[dict[str, Any]] = Field(default_factory=list)
    edges: list[dict[str, Any]] = Field(default_factory=list)
    expected_version: int | None = Field(default=None, description="Optimistic locking: current version_no")


class AddItems(Content):
    keys: list[str] = Field(min_length=1, max_length=50)
    x: float | None = None
    y: float | None = None


class AddNote(Content):
    text: str = Field(min_length=1, max_length=1000)


class Connect(Content):
    source: str
    target: str
    type: str


class RemoveEdge(Content):
    delete_link: bool = False


def _content(body: Content) -> dict[str, Any]:
    return {"nodes": body.nodes, "edges": body.edges}


def _out(db: Session, project: Project, item: Item) -> dict[str, Any]:
    return service.view(db, project, item)


@router.get("", summary="The architecture diagrams of the project")
def listing(project_key: str, user: User = Depends(current_user),
            db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    project = get_project(db, project_key, user)
    rows = db.execute(select(Item).where(Item.project_id == project.id, Item.type_key == service.TYPE_KEY,
                                         Item.deleted_at.is_(None)).order_by(Item.seq)).scalars().all()
    users = UserDirectory(db)
    out = []
    for item, shown in zip(rows, items_out(project, rows, users), strict=True):
        content = service.content_of(item)
        out.append({**shown.model_dump(mode="json"), "viewpoint": item.fields.get("viewpoint") or "free",
                    "nodes": len(content["nodes"]), "edges": len(content["edges"])})
    return out


@router.get("/{diagram_key}.svg", summary="The diagram as an image (SVG)")
def image(project_key: str, diagram_key: str, user: User = Depends(current_user),
          db: Session = Depends(get_db)) -> Response:
    project = get_project(db, project_key, user)
    item = service.get_diagram(db, project, diagram_key)
    picture = svg.render(_out(db, project, item))
    return Response(picture, media_type="image/svg+xml",
                    headers={"Content-Disposition": f'inline; filename="{item.key}.svg"',
                             "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'"})


@router.get("/{diagram_key}", summary="One diagram with its elements and relationships")
def read(project_key: str, diagram_key: str, user: User = Depends(current_user),
         db: Session = Depends(get_db)) -> dict[str, Any]:
    project = get_project(db, project_key, user)
    return _out(db, project, service.get_diagram(db, project, diagram_key))


@router.get("/{diagram_key}/palette", summary="Element and relationship types this viewpoint suggests")
def palette(project_key: str, diagram_key: str, user: User = Depends(current_user),
            db: Session = Depends(get_db)) -> dict[str, Any]:
    project = get_project(db, project_key, user)
    item = service.get_diagram(db, project, diagram_key)
    return service.palette(project, item.fields.get("viewpoint"))


@router.get("/{diagram_key}/related", summary="Items linked to what the diagram already shows")
def related(project_key: str, diagram_key: str, limit: int = Query(default=25, ge=1, le=100),
            user: User = Depends(current_user), db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    project = get_project(db, project_key, user)
    item = service.get_diagram(db, project, diagram_key)
    keys = [n["item"] for n in service.content_of(item)["nodes"] if n.get("item")]
    return service.related(db, project, item, keys, limit)


@router.put("/{diagram_key}", summary="Save the canvas (places and sizes)")
def save(project_key: str, diagram_key: str, body: Content, user: User = Depends(current_user),
         db: Session = Depends(get_db)) -> dict[str, Any]:
    project = get_project(db, project_key, user, "contributor")
    item = service.get_diagram(db, project, diagram_key)
    item = service._save(db, project, user, item, _content(body), "Changed the diagram", body.expected_version)
    db.commit()
    return _out(db, project, item)


@router.post("/{diagram_key}/items", summary="Put items on the diagram (with the links they already have)")
def add_items(project_key: str, diagram_key: str, body: AddItems, user: User = Depends(current_user),
              db: Session = Depends(get_db)) -> dict[str, Any]:
    project = get_project(db, project_key, user, "contributor")
    item = service.get_diagram(db, project, diagram_key)
    at = (body.x, body.y) if body.x is not None and body.y is not None else None
    item = service.add_items(db, project, user, item, body.keys, _content(body), at)
    db.commit()
    return _out(db, project, item)


@router.post("/{diagram_key}/notes", summary="Put a note on the diagram")
def add_note(project_key: str, diagram_key: str, body: AddNote, user: User = Depends(current_user),
             db: Session = Depends(get_db)) -> dict[str, Any]:
    project = get_project(db, project_key, user, "contributor")
    item = service.get_diagram(db, project, diagram_key)
    item = service.add_note(db, project, user, item, body.text, _content(body))
    db.commit()
    return _out(db, project, item)


@router.post("/{diagram_key}/connect", summary="Draw a relationship — this creates a real link")
def connect(project_key: str, diagram_key: str, body: Connect, user: User = Depends(current_user),
            db: Session = Depends(get_db)) -> dict[str, Any]:
    project = get_project(db, project_key, user, "contributor")
    item = service.get_diagram(db, project, diagram_key)
    item = service.connect(db, project, user, item, source_node=body.source, target_node=body.target,
                           type_key=body.type, content=_content(body))
    db.commit()
    return _out(db, project, item)


@router.post("/{diagram_key}/nodes/{node_id}/remove", summary="Take an element off the diagram (the item stays)")
def remove_node(project_key: str, diagram_key: str, node_id: str, body: Content,
                user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    project = get_project(db, project_key, user, "contributor")
    item = service.get_diagram(db, project, diagram_key)
    item = service.remove_node(db, project, user, item, node_id, _content(body))
    db.commit()
    return _out(db, project, item)


@router.post("/{diagram_key}/edges/{edge_id}/remove",
             summary="Take a relationship off the diagram, and on request delete the link")
def remove_edge(project_key: str, diagram_key: str, edge_id: str, body: RemoveEdge,
                user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    project = get_project(db, project_key, user, "contributor")
    item = service.get_diagram(db, project, diagram_key)
    item = service.remove_edge(db, project, user, item, edge_id, delete_link=body.delete_link,
                               content=_content(body))
    db.commit()
    return _out(db, project, item)


@router.post("/{diagram_key}/layout", summary="Arrange the diagram in layers")
def layout(project_key: str, diagram_key: str, body: Content, user: User = Depends(current_user),
           db: Session = Depends(get_db)) -> dict[str, Any]:
    project = get_project(db, project_key, user, "contributor")
    item = service.get_diagram(db, project, diagram_key)
    item = service.layout(db, project, user, item, _content(body))
    db.commit()
    return _out(db, project, item)
