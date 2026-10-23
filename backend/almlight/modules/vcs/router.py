"""Git repositories (Code page) and linked revisions of items."""

from __future__ import annotations

import mimetypes
import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from almlight.core.db import get_db
from almlight.core.deps import current_user
from almlight.core.schemas import Ok
from almlight.modules.identity.models import User
from almlight.modules.items import service as items_svc
from almlight.modules.projects.access import get_project
from almlight.modules.vcs import service
from almlight.modules.vcs.models import Repository

router = APIRouter(prefix="/projects/{project_key}", tags=["code (git)"])


class RepoIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(max_length=100)
    url: str = Field(max_length=1000, description="HTTPS clone URL (or a permitted local path)")
    token: str | None = Field(default=None, max_length=500, description="Access token (stored encrypted)")
    auth_user: str | None = Field(default=None, max_length=100, description="User name for the token (Bitbucket)")
    web_url: str | None = Field(default=None, max_length=1000)


class RepoPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, max_length=100)
    token: str | None = Field(default=None, max_length=500)
    clear_token: bool = False
    auth_user: str | None = Field(default=None, max_length=100)
    web_url: str | None = Field(default=None, max_length=1000)
    enabled: bool | None = None


class LinkIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    repository: uuid.UUID
    sha: str = Field(max_length=64)


class BranchIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(max_length=200)
    source: str | None = Field(default=None, max_length=200, description="Branch, tag or commit to start from")
    item: str | None = Field(default=None, description="Item the branch is for (audit, linking)")


@router.get("/repositories", summary="Connected Git repositories")
def list_repositories(project_key: str, user: User = Depends(current_user),
                      db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    project = get_project(db, project_key, user)
    repos = db.execute(select(Repository).where(Repository.project_id == project.id)
                       .order_by(Repository.name)).scalars()
    return [service.repo_out(r) for r in repos]


@router.post("/repositories", status_code=201, summary="Connect a Git repository (manager)")
def add_repository(project_key: str, body: RepoIn, user: User = Depends(current_user),
                   db: Session = Depends(get_db)) -> dict[str, Any]:
    project = get_project(db, project_key, user, "manager")
    repo = service.add_repository(db, project, user, name=body.name, url=body.url, token=body.token,
                                  auth_user=body.auth_user, web_url=body.web_url)
    db.commit()
    result = service.sync(db, repo)
    db.commit()
    return {**service.repo_out(repo), "sync": result}


@router.patch("/repositories/{repo_id}", summary="Change a repository (manager)")
def update_repository(project_key: str, repo_id: uuid.UUID, body: RepoPatch, user: User = Depends(current_user),
                      db: Session = Depends(get_db)) -> dict[str, Any]:
    project = get_project(db, project_key, user, "manager")
    repo = service.get_repo(db, project, repo_id)
    service.update_repository(db, project, user, repo, **body.model_dump())
    db.commit()
    return service.repo_out(repo)


@router.delete("/repositories/{repo_id}", response_model=Ok, summary="Disconnect a repository (manager)")
def delete_repository(project_key: str, repo_id: uuid.UUID, user: User = Depends(current_user),
                      db: Session = Depends(get_db)) -> Ok:
    project = get_project(db, project_key, user, "manager")
    service.delete_repository(db, project, user, service.get_repo(db, project, repo_id))
    db.commit()
    return Ok()


@router.post("/repositories/{repo_id}/sync", summary="Fetch now and index new commits")
def sync_repository(project_key: str, repo_id: uuid.UUID, user: User = Depends(current_user),
                    db: Session = Depends(get_db)) -> dict[str, Any]:
    project = get_project(db, project_key, user, "contributor")
    repo = service.get_repo(db, project, repo_id)
    result = service.sync(db, repo)
    db.commit()
    return {**service.repo_out(repo), "sync": result}


@router.get("/repositories/{repo_id}", summary="One repository with its branches and tags")
def get_repository(project_key: str, repo_id: uuid.UUID, user: User = Depends(current_user),
                   db: Session = Depends(get_db)) -> dict[str, Any]:
    project = get_project(db, project_key, user)
    return service.repo_out(service.get_repo(db, project, repo_id), with_refs=True)


@router.get("/repositories/{repo_id}/commits", summary="Commit history (search, branch, path, linked item)")
def commits(project_key: str, repo_id: uuid.UUID, q: str | None = None, ref: str | None = None,
            path: str | None = None, item: str | None = None, limit: int = Query(default=50, ge=1, le=200),
            offset: int = Query(default=0, ge=0), user: User = Depends(current_user),
            db: Session = Depends(get_db)) -> dict[str, Any]:
    project = get_project(db, project_key, user)
    return service.list_commits(db, service.get_repo(db, project, repo_id), q=q, ref=ref, path=path, item=item,
                                limit=limit, offset=offset)


@router.get("/repositories/{repo_id}/commits/{sha}", summary="A commit: message, changed files, diff, linked items")
def commit(project_key: str, repo_id: uuid.UUID, sha: str, user: User = Depends(current_user),
           db: Session = Depends(get_db)) -> dict[str, Any]:
    project = get_project(db, project_key, user)
    return service.commit_detail(db, service.get_repo(db, project, repo_id), sha)


@router.get("/repositories/{repo_id}/branches", summary="Branches and tags with the items their names mention")
def branches(project_key: str, repo_id: uuid.UUID, user: User = Depends(current_user),
             db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    project = get_project(db, project_key, user)
    return service.branches(db, project, service.get_repo(db, project, repo_id))


@router.post("/repositories/{repo_id}/branches", status_code=201, summary="Create a branch in the remote repository")
def create_branch(project_key: str, repo_id: uuid.UUID, body: BranchIn, user: User = Depends(current_user),
                  db: Session = Depends(get_db)) -> dict[str, Any]:
    project = get_project(db, project_key, user, "contributor")
    repo = service.get_repo(db, project, repo_id)
    item = items_svc.get_item(db, project, body.item) if body.item else None
    result = service.create_branch(db, project, user, repo, name=body.name, source=body.source, item=item)
    db.commit()
    return result


@router.get("/repositories/{repo_id}/tree", summary="Files and folders at a branch, tag or commit")
def tree(project_key: str, repo_id: uuid.UUID, ref: str | None = None, path: str = "",
         user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    project = get_project(db, project_key, user)
    return service.browse(db, service.get_repo(db, project, repo_id), ref, path)


@router.get("/repositories/{repo_id}/file", summary="A file's content and history")
def file(project_key: str, repo_id: uuid.UUID, path: str, ref: str | None = None,
         user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    project = get_project(db, project_key, user)
    return service.file_view(db, service.get_repo(db, project, repo_id), ref, path)


@router.get("/repositories/{repo_id}/raw", summary="Download a file")
def raw(project_key: str, repo_id: uuid.UUID, path: str, ref: str | None = None,
        user: User = Depends(current_user), db: Session = Depends(get_db)) -> Response:
    project = get_project(db, project_key, user)
    data, name = service.raw_file(service.get_repo(db, project, repo_id), ref, path)
    ctype = mimetypes.guess_type(name)[0] or "application/octet-stream"
    safe = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in name)
    return Response(data, media_type=ctype, headers={"Content-Disposition": f'attachment; filename="{safe}"',
                                                     "Content-Security-Policy": "default-src 'none'; sandbox"})


@router.get("/items/{item_key}/revisions", summary="Linked revisions, branches and pull requests of an item")
def item_revisions(project_key: str, item_key: str, user: User = Depends(current_user),
                   db: Session = Depends(get_db)) -> dict[str, Any]:
    project = get_project(db, project_key, user)
    return service.item_revisions(db, project, items_svc.get_item(db, project, item_key))


@router.post("/items/{item_key}/revisions", status_code=201, summary="Link a revision (commit) to an item")
def link_revision(project_key: str, item_key: str, body: LinkIn, user: User = Depends(current_user),
                  db: Session = Depends(get_db)) -> dict[str, Any]:
    project = get_project(db, project_key, user, "contributor")
    item = items_svc.get_item(db, project, item_key)
    link = service.link_revision(db, project, user, item, service.get_repo(db, project, body.repository), body.sha)
    db.commit()
    return {"link_id": str(link.id)}


@router.delete("/items/{item_key}/revisions/{link_id}", response_model=Ok, summary="Remove a manually linked revision")
def unlink_revision(project_key: str, item_key: str, link_id: uuid.UUID, user: User = Depends(current_user),
                    db: Session = Depends(get_db)) -> Ok:
    project = get_project(db, project_key, user, "contributor")
    service.unlink_revision(db, project, user, items_svc.get_item(db, project, item_key), link_id)
    db.commit()
    return Ok()
