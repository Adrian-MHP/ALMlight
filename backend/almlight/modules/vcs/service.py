"""Git repositories of a project: mirrors, commit index, linked revisions, browsing and branches.

Like Polarion's repository integration: every connected repository is mirrored (read-only, bare) and its commits
are indexed; item keys in commit messages ("Fix SYS-12 range check") link the commit to the item as a *linked
revision*. Revisions can also be linked by hand. Pull requests of GitHub repositories are linked the same way.
"""

from __future__ import annotations

import logging
import re
import shutil
import threading
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from almlight.core import secretbox
from almlight.core.config import get_settings
from almlight.core.db import session_factory, utcnow
from almlight.core.errors import Conflict, NotFound, ValidationFailed
from almlight.modules.audit import service as audit
from almlight.modules.identity.models import User
from almlight.modules.integrations.models import ExternalRef
from almlight.modules.items.models import Item
from almlight.modules.projects.models import Project
from almlight.modules.vcs import git
from almlight.modules.vcs.models import CommitLink, RepoCommit, Repository

log = logging.getLogger("almlight.vcs")
KEY_RE = re.compile(r"(?<![A-Za-z0-9])([A-Z][A-Z0-9]{0,7}-\d+)(?![0-9])")
PROVIDERS = ("github", "gitlab", "bitbucket", "azure", "git")


# --- configuration --------------------------------------------------------------------------------------------


def detect(url: str, local: bool) -> tuple[str, str | None]:
    """(provider, web URL) from the clone URL."""
    if local:
        return "git", None
    u = urlparse(url)
    host, path = (u.hostname or "").lower(), u.path.rstrip("/")
    path = path[:-4] if path.endswith(".git") else path
    base = f"https://{u.hostname}{path}"
    if host == "github.com" or host.endswith(".github.com"):
        return "github", base
    if "gitlab" in host:
        return "gitlab", base
    if host == "bitbucket.org":
        return "bitbucket", base
    if host == "dev.azure.com" or host.endswith(".visualstudio.com"):
        return "azure", base
    return "git", None


def web_link(repo: Repository, kind: str, ref: str = "", path: str = "") -> str | None:
    base = repo.web_url
    if not base:
        return None
    p = repo.provider
    if kind == "commit":
        return {"github": f"{base}/commit/{ref}", "gitlab": f"{base}/-/commit/{ref}",
                "bitbucket": f"{base}/commits/{ref}", "azure": f"{base}/commit/{ref}"}.get(p, f"{base}/commit/{ref}")
    if kind == "file":
        return {"github": f"{base}/blob/{ref}/{path}", "gitlab": f"{base}/-/blob/{ref}/{path}",
                "bitbucket": f"{base}/src/{ref}/{path}", "azure": f"{base}?path=/{path}&version=GC{ref}"}.get(p)
    if kind == "branch":
        return {"github": f"{base}/tree/{ref}", "gitlab": f"{base}/-/tree/{ref}", "bitbucket": f"{base}/branch/{ref}",
                "azure": f"{base}?version=GB{ref}"}.get(p)
    return base


def mirror_path(repo: Repository) -> Path:
    return get_settings().repos_dir / f"{repo.id}.git"


def _auth(repo: Repository) -> git.Auth | None:
    token = secretbox.unseal(repo.token_enc)
    return git.Auth(token=token, user=repo.auth_user) if token else None


def repo_out(repo: Repository, *, with_refs: bool = False) -> dict[str, Any]:
    out = {"id": str(repo.id), "name": repo.name, "url": repo.url, "provider": repo.provider, "web_url": repo.web_url,
           "default_branch": repo.default_branch, "enabled": repo.enabled, "has_token": bool(repo.token_enc),
           "auth_user": repo.auth_user, "commit_count": repo.commit_count,
           "branch_count": sum(1 for r in repo.refs if r["kind"] == "branch"),
           "tag_count": sum(1 for r in repo.refs if r["kind"] == "tag"),
           "last_sync_at": repo.last_sync_at.isoformat() if repo.last_sync_at else None, "last_error": repo.last_error,
           "pull_requests": repo.meta.get("pull_requests"), "can_push": bool(repo.token_enc) or repo.provider == "git"}
    if with_refs:
        out["refs"] = repo.refs
    return out


def get_repo(db: Session, project: Project, repo_id: uuid.UUID | str) -> Repository:
    try:
        rid = uuid.UUID(str(repo_id))
    except ValueError:
        raise NotFound("Repository not found") from None
    repo = db.get(Repository, rid)
    if repo is None or repo.project_id != project.id:
        raise NotFound("Repository not found")
    return repo


def _unreachable(error: str, with_token: bool) -> str:
    """Turn the Git output of a failed first contact into something the person can act on."""
    low = error.lower()
    if "could not read username" in low or "authentication failed" in low or "invalid username or password" in low:
        return ("The Git server did not accept the access: " + (
            "the access token is wrong, expired or lacks read access to this repository (a GitHub token needs "
            "'Contents: read'; a password does not work)." if with_token else
            "the repository is private or does not exist — add an access token (not your password)."))
    if "repository not found" in low or "not found" in low or "403" in low:
        return "The Git server does not know this repository, or the access token may not read it — check the URL."
    if "timed out" in low or "could not resolve host" in low or "failed to connect" in low:
        return f"The Git server cannot be reached from this installation: {error}"
    return f"Cannot reach the repository: {error}"


def add_repository(db: Session, project: Project, actor: User, *, name: str, url: str, token: str | None = None,
                   auth_user: str | None = None, web_url: str | None = None) -> Repository:
    name = (name or "").strip()
    if not name or len(name) > 100:
        raise ValidationFailed("Give the repository a name (at most 100 characters)")
    if db.execute(select(Repository.id).where(Repository.project_id == project.id, Repository.name == name)).first():
        raise Conflict(f"A repository named '{name}' already exists in {project.key}")
    clean, local = git.check_url(url)
    provider, web = detect(clean, local)
    try:
        git.ls_remote(clean, git.Auth(token=token, user=auth_user) if token else None, local)
    except git.GitError as exc:
        raise ValidationFailed(_unreachable(str(exc), bool(token))) from None
    repo = Repository(project_id=project.id, name=name, url=clean, provider=provider,
                      web_url=(web_url or "").strip().rstrip("/") or web, auth_user=(auth_user or "").strip() or None,
                      token_enc=secretbox.seal(token) if token else None, created_by=actor.id, next_sync_at=utcnow())
    db.add(repo)
    db.flush()
    audit.record(db, actor=actor, action="repository.added", entity_type="project", entity_id=project.id,
                 project_id=project.id, summary=f"Connected repository {name} ({provider}) to {project.key}",
                 details={"repository": str(repo.id), "url": clean})
    return repo


def update_repository(db: Session, project: Project, actor: User, repo: Repository, *, name: str | None = None,
                      token: str | None = None, clear_token: bool = False, auth_user: str | None = None,
                      web_url: str | None = None, enabled: bool | None = None) -> Repository:
    if name is not None and name.strip() and name.strip() != repo.name:
        repo.name = name.strip()[:100]
    if token:
        repo.token_enc = secretbox.seal(token)
    elif clear_token:
        repo.token_enc = None
    if auth_user is not None:
        repo.auth_user = auth_user.strip() or None
    if web_url is not None:
        repo.web_url = web_url.strip().rstrip("/") or None
    if enabled is not None:
        repo.enabled = enabled
    audit.record(db, actor=actor, action="repository.updated", entity_type="project", entity_id=project.id,
                 project_id=project.id, summary=f"Changed repository {repo.name}",
                 details={"repository": str(repo.id),
                          "token": "changed" if token else "removed" if clear_token else None})
    return repo


def delete_repository(db: Session, project: Project, actor: User, repo: Repository) -> None:
    path = mirror_path(repo)
    audit.record(db, actor=actor, action="repository.removed", entity_type="project", entity_id=project.id,
                 project_id=project.id, summary=f"Disconnected repository {repo.name} from {project.key}",
                 details={"repository": str(repo.id), "url": repo.url})
    db.delete(repo)
    db.flush()
    shutil.rmtree(path, ignore_errors=True)


# --- sync -----------------------------------------------------------------------------------------------------


def _project_keys(db: Session, project: Project, texts: list[str]) -> dict[str, uuid.UUID]:
    keys = {m for t in texts if t for m in KEY_RE.findall(t)}
    if not keys:
        return {}
    rows = db.execute(select(Item.key, Item.id).where(Item.project_id == project.id, Item.key.in_(keys),
                                                      Item.deleted_at.is_(None))).all()
    return dict(rows)


def sync(db: Session, repo: Repository, wait: bool = True) -> dict[str, Any]:
    """Fetch the mirror, index new commits and link them to the items they mention.

    One sync per repository at a time (row lock until the caller commits): a request waits for a running sync and
    then indexes only what is still new; the background worker (``wait=False``) skips a repository that is busy.
    """
    db.flush()  # changes the caller made are written first: the reload below must not discard them
    locked = db.execute(select(Repository.id).where(Repository.id == repo.id)
                        .with_for_update(skip_locked=not wait)).scalar_one_or_none()
    if locked is None:
        return {"ok": True, "busy": True, "new_commits": 0, "linked": 0}
    db.refresh(repo)
    project = db.get(Project, repo.project_id)
    settings = get_settings()
    path = mirror_path(repo)
    auth = _auth(repo)
    local = repo.provider == "git" and not repo.url.startswith(("http://", "https://"))
    started = time.monotonic()
    try:
        git.mirror(path, repo.url, auth, local)
        refs = git.refs(path)
        known = set(db.execute(select(RepoCommit.sha).where(RepoCommit.repository_id == repo.id)).scalars())
        shas = git.rev_list(path, ["--all"], settings.git_max_commits) if refs else []
        new = [s for s in shas if s not in known]
        infos = git.commits(path, new)
    except git.GitError as exc:
        repo.last_error = str(exc)[:1000]
        repo.next_sync_at = utcnow() + timedelta(minutes=max(settings.git_sync_minutes, 1))
        return {"ok": False, "error": repo.last_error}
    keyed = _project_keys(db, project, [i.message for i in infos])  # type: ignore[arg-type]
    rows, links = [], []
    for info in infos:
        cid = uuid.uuid4()
        rows.append(RepoCommit(id=cid, repository_id=repo.id, sha=info.sha, parents=info.parents,
                               author_name=info.author_name[:255], author_email=info.author_email[:255],
                               authored_at=info.authored_at, committer_name=info.committer_name[:255],
                               committed_at=info.committed_at, message=info.message, files=info.files,
                               additions=info.additions, deletions=info.deletions, file_count=info.file_count))
        links += [CommitLink(commit_id=cid, item_id=keyed[key], project_id=repo.project_id, source="message")
                  for key in set(KEY_RE.findall(info.message)) if key in keyed]
    db.add_all(rows)
    db.flush()
    db.add_all(links)
    db.flush()
    linked = len(links)
    repo.refs = refs
    repo.default_branch = git.default_branch(path) or repo.default_branch
    repo.commit_count = len(known) + len(infos)
    repo.last_sync_at = utcnow()
    repo.last_error = None
    repo.next_sync_at = utcnow() + timedelta(minutes=max(settings.git_sync_minutes, 1))
    prs = _sync_pull_requests(db, project, repo, auth) if repo.provider == "github" else None  # type: ignore[arg-type]
    if infos or linked:
        audit.record(db, actor=None, actor_name="git", action="repository.synced", entity_type="project",
                     entity_id=project.id, project_id=project.id,  # type: ignore[union-attr]
                     summary=f"Indexed {len(infos)} commit(s) of {repo.name}, {linked} linked to items",
                     details={"repository": str(repo.id), "commits": len(infos), "linked": linked})
    return {"ok": True, "new_commits": len(infos), "linked": linked, "refs": len(refs), "pull_requests": prs,
            "seconds": round(time.monotonic() - started, 2)}


def _sync_pull_requests(db: Session, project: Project, repo: Repository, auth: git.Auth | None) -> int | None:
    """GitHub pull requests that mention item keys (title, description, branch) become references on the items."""
    base = repo.web_url or ""
    m = re.match(r"https://github\.com/([^/]+)/([^/]+)$", base)
    if not m:
        return None
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "Ariadne-ALM"}
    if auth and auth.token:
        headers["Authorization"] = f"Bearer {auth.token}"
    etag = repo.meta.get("pr_etag")
    if etag:
        headers["If-None-Match"] = etag
    try:
        with httpx.Client(timeout=15) as client:
            resp = client.get(f"https://api.github.com/repos/{m.group(1)}/{m.group(2)}/pulls",
                              params={"state": "all", "per_page": 50, "sort": "updated", "direction": "desc"},
                              headers=headers)
    except httpx.HTTPError as exc:
        repo.meta = {**repo.meta, "pull_requests": {"error": str(exc)[:200]}}
        return None
    if resp.status_code == 304:
        return repo.meta.get("pull_requests", {}).get("linked", 0)
    if resp.status_code != 200:
        repo.meta = {**repo.meta, "pull_requests": {"error": f"GitHub answered {resp.status_code}"}}
        return None
    pulls = resp.json()
    linked = 0
    for pr in pulls:
        texts = [pr.get("title"), pr.get("body"), (pr.get("head") or {}).get("ref")]
        status = "merged" if pr.get("merged_at") else pr.get("state")
        for item_id in _project_keys(db, project, [t for t in texts if t]).values():
            ext = f"{m.group(1)}/{m.group(2)}#{pr.get('number')}"
            ref = db.execute(select(ExternalRef).where(ExternalRef.item_id == item_id, ExternalRef.system == "github",
                                                       ExternalRef.kind == "pull_request",
                                                       ExternalRef.external_id == ext)).scalar_one_or_none()
            data = {"repository_id": str(repo.id), "number": pr.get("number"),
                    "author": (pr.get("user") or {}).get("login"),
                    "head": (pr.get("head") or {}).get("ref"), "base": (pr.get("base") or {}).get("ref"),
                    "updated_at": pr.get("updated_at")}
            if ref is None:
                db.add(ExternalRef(project_id=project.id, item_id=item_id, system="github", kind="pull_request",
                                   external_id=ext, url=pr.get("html_url"), title=pr.get("title"), status=status,
                                   data=data))
            else:
                ref.title, ref.status, ref.url = pr.get("title"), status, pr.get("html_url")
                ref.data, ref.updated_at = data, utcnow()
            linked += 1
    repo.meta = {**repo.meta, "pr_etag": resp.headers.get("ETag"),
                 "pull_requests": {"checked": len(pulls), "linked": linked, "at": utcnow().isoformat()}}
    return linked


def sync_due(db: Session) -> int:
    due = db.execute(select(Repository).where(Repository.enabled.is_(True), or_(
        Repository.next_sync_at.is_(None), Repository.next_sync_at <= utcnow()))
        .order_by(Repository.next_sync_at.nulls_first()).limit(5)).scalars().all()
    for repo in due:
        try:
            sync(db, repo, wait=False)
            db.commit()
        except Exception:  # noqa: BLE001 — one broken repository must not stop the others
            db.rollback()
            log.exception("syncing repository %s failed", repo.id)
            with session_factory()() as other:
                r = other.get(Repository, repo.id)
                if r is not None:
                    r.last_error = "Sync failed — see the server log"
                    r.next_sync_at = utcnow() + timedelta(minutes=max(get_settings().git_sync_minutes, 1))
                    other.commit()
    return len(due)


def request_sync(db: Session, project: Project, url_hint: str | None) -> int:
    """A push webhook: sync the repositories of the project with that URL soon."""
    n = 0
    for repo in db.execute(select(Repository).where(Repository.project_id == project.id)).scalars():
        if not url_hint or url_hint.rstrip("/").removesuffix(".git") in (repo.url.removesuffix(".git"), repo.web_url):
            repo.next_sync_at = utcnow()
            n += 1
    return n


class GitSyncWorker:
    """Background thread fetching repositories that are due (every ``git_sync_minutes``)."""

    def __init__(self, interval: float = 15.0):
        self.interval = interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if get_settings().git_sync_minutes <= 0:
            return
        self._thread = threading.Thread(target=self._run, name="git-sync", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                with session_factory()() as db:
                    sync_due(db)
            except Exception:  # noqa: BLE001
                log.exception("git sync round failed")
            self._stop.wait(self.interval)


# --- linked revisions -----------------------------------------------------------------------------------------


def commit_out(repo: Repository, c: RepoCommit, *, links: list[dict] | None = None) -> dict[str, Any]:
    title = c.message.split("\n", 1)[0]
    return {"repository": {"id": str(repo.id), "name": repo.name, "provider": repo.provider}, "sha": c.sha,
            "short": c.sha[:8], "title": title, "message": c.message, "author": c.author_name,
            "author_email": c.author_email, "authored_at": c.authored_at.isoformat(),
            "committed_at": c.committed_at.isoformat(), "parents": c.parents, "additions": c.additions,
            "deletions": c.deletions, "file_count": c.file_count, "url": web_link(repo, "commit", c.sha),
            **({"items": links} if links is not None else {})}


def _links_by_commit(db: Session, commit_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[dict]]:
    if not commit_ids:
        return {}
    rows = db.execute(select(CommitLink.commit_id, CommitLink.id, CommitLink.source, Item.key, Item.title)
                      .join(Item, Item.id == CommitLink.item_id)
                      .where(CommitLink.commit_id.in_(commit_ids), Item.deleted_at.is_(None))).all()
    out: dict[uuid.UUID, list[dict]] = {}
    for cid, lid, source, key, title in rows:
        out.setdefault(cid, []).append({"link_id": str(lid), "key": key, "title": title, "source": source})
    return out


def item_revisions(db: Session, project: Project, item: Item) -> dict[str, Any]:
    rows = db.execute(select(CommitLink, RepoCommit, Repository).join(RepoCommit, RepoCommit.id == CommitLink.commit_id)
                      .join(Repository, Repository.id == RepoCommit.repository_id)
                      .where(CommitLink.item_id == item.id).order_by(RepoCommit.committed_at.desc())).all()
    revisions = [{**commit_out(repo, c), "link_id": str(link.id), "source": link.source} for link, c, repo in rows]
    branches = []
    repos = db.execute(select(Repository).where(Repository.project_id == project.id)).scalars().all()
    pattern = re.compile(rf"(?<![A-Za-z0-9]){re.escape(item.key)}(?![0-9])", re.I)
    for repo in repos:
        for r in repo.refs:
            if r["kind"] == "branch" and pattern.search(r["name"]):
                branches.append({"repository": {"id": str(repo.id), "name": repo.name}, "name": r["name"],
                                 "sha": r["sha"], "date": r.get("date"), "url": web_link(repo, "branch", r["name"])})
    prs = db.execute(select(ExternalRef).where(ExternalRef.item_id == item.id, ExternalRef.kind == "pull_request")
                     .order_by(ExternalRef.updated_at.desc())).scalars().all()
    return {"revisions": revisions, "branches": branches,
            "pull_requests": [{"id": str(p.id), "external_id": p.external_id, "title": p.title, "status": p.status,
                               "url": p.url, "system": p.system, "data": p.data} for p in prs],
            "repositories": [{"id": str(r.id), "name": r.name, "provider": r.provider, "can_push": bool(r.token_enc)
                              or r.provider == "git", "default_branch": r.default_branch} for r in repos],
            "branch_name": suggested_branch(item)}


def suggested_branch(item: Item) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", item.title.lower()).strip("-")[:40].strip("-")
    return f"feature/{item.key}-{slug}" if slug else f"feature/{item.key}"


def find_commit(db: Session, repo: Repository, sha: str) -> RepoCommit:
    sha = (sha or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{4,64}", sha):
        raise ValidationFailed("Enter a commit hash (at least 4 hexadecimal characters)")
    rows = db.execute(select(RepoCommit).where(RepoCommit.repository_id == repo.id, RepoCommit.sha.like(f"{sha}%"))
                      .limit(2)).scalars().all()
    if not rows:
        raise NotFound(f"Commit {sha} not found in {repo.name} (synchronise the repository first)")
    if len(rows) > 1:
        raise ValidationFailed(f"{sha} is ambiguous in {repo.name} — enter more characters")
    return rows[0]


def link_revision(db: Session, project: Project, actor: User, item: Item, repo: Repository, sha: str) -> CommitLink:
    c = find_commit(db, repo, sha)
    if db.execute(select(CommitLink.id).where(CommitLink.commit_id == c.id, CommitLink.item_id == item.id)).first():
        raise Conflict(f"{c.sha[:8]} is already linked to {item.key}")
    link = CommitLink(commit_id=c.id, item_id=item.id, project_id=project.id, source="manual", created_by=actor.id)
    db.add(link)
    db.flush()
    audit.record(db, actor=actor, action="revision.linked", entity_type="item", entity_id=item.id,
                 project_id=project.id, summary=f"Linked revision {c.sha[:8]} ({repo.name}) to {item.key}",
                 details={"repository": str(repo.id), "sha": c.sha}, related_ids=[item.id])
    return link


def unlink_revision(db: Session, project: Project, actor: User, item: Item, link_id: uuid.UUID) -> None:
    link = db.get(CommitLink, link_id)
    if link is None or link.item_id != item.id:
        raise NotFound("Linked revision not found")
    if link.source == "message":
        raise ValidationFailed("This revision mentions the item in its commit message; it stays linked")
    c = db.get(RepoCommit, link.commit_id)
    audit.record(db, actor=actor, action="revision.unlinked", entity_type="item", entity_id=item.id,
                 project_id=project.id, summary=f"Removed linked revision {c.sha[:8] if c else '?'} from {item.key}",
                 related_ids=[item.id])
    db.delete(link)


# --- browsing -------------------------------------------------------------------------------------------------


def _ready(repo: Repository) -> Path:
    path = mirror_path(repo)
    if not (path / "HEAD").exists():
        raise ValidationFailed(f"{repo.name} has not been synchronised yet")
    return path


def list_commits(db: Session, repo: Repository, *, q: str | None = None, ref: str | None = None,
                 path: str | None = None, item: str | None = None, limit: int = 50, offset: int = 0) -> dict[str, Any]:
    stmt = select(RepoCommit).where(RepoCommit.repository_id == repo.id)
    if ref or path:
        mirror = _ready(repo)
        start = git.resolve(mirror, ref) if ref else "--all"
        shas = git.rev_list(mirror, [start], 5000, [git._clean_path(path)] if path else None)
        stmt = stmt.where(RepoCommit.sha.in_(shas))
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(RepoCommit.message.ilike(like), RepoCommit.author_name.ilike(like),
                              RepoCommit.sha.like(f"{q.strip().lower()}%")))
    if item:
        stmt = stmt.where(RepoCommit.id.in_(select(CommitLink.commit_id).join(Item, Item.id == CommitLink.item_id)
                                            .where(Item.key == item.strip().upper())))
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rows = db.execute(stmt.order_by(RepoCommit.committed_at.desc()).limit(min(limit, 200))
                      .offset(offset)).scalars().all()
    links = _links_by_commit(db, [c.id for c in rows])
    return {"total": total, "commits": [commit_out(repo, c, links=links.get(c.id, [])) for c in rows]}


def commit_detail(db: Session, repo: Repository, sha: str) -> dict[str, Any]:
    c = find_commit(db, repo, sha)
    mirror = _ready(repo)
    files, truncated = git.show_patch(mirror, c.sha)
    stats = {f["path"]: f for f in c.files}
    for f in files:
        s = stats.get(f["path"]) or {}
        f["additions"], f["deletions"] = s.get("additions", 0), s.get("deletions", 0)
    links = _links_by_commit(db, [c.id]).get(c.id, [])
    return {**commit_out(repo, c, links=links), "files": files, "truncated": truncated,
            "branches": git.contains(mirror, c.sha)}


def browse(db: Session, repo: Repository, ref: str | None, path: str) -> dict[str, Any]:
    mirror = _ready(repo)
    rev = ref or repo.default_branch or "HEAD"
    sha = git.resolve(mirror, rev)
    entries = git.tree(mirror, sha, path)
    head = db.execute(select(RepoCommit).where(RepoCommit.repository_id == repo.id,
                                               RepoCommit.sha == sha)).scalar_one_or_none()
    url = web_link(repo, "file", rev, path) if path else web_link(repo, "branch", rev)
    return {"ref": rev, "sha": sha, "path": git._clean_path(path), "entries": entries,
            "commit": commit_out(repo, head) if head else None, "url": url}


LANG = {".py": "python", ".c": "c", ".h": "c", ".cpp": "cpp", ".hpp": "cpp", ".cc": "cpp", ".ts": "typescript",
        ".tsx": "typescript", ".js": "javascript", ".json": "json", ".md": "markdown", ".yaml": "yaml", ".yml": "yaml",
        ".xml": "xml", ".java": "java", ".cs": "csharp", ".rs": "rust", ".go": "go", ".sql": "sql", ".sh": "shell",
        ".toml": "toml", ".ini": "ini", ".txt": "text", ".cmake": "cmake", ".mk": "make"}


def file_view(db: Session, repo: Repository, ref: str | None, path: str) -> dict[str, Any]:
    mirror = _ready(repo)
    rev = ref or repo.default_branch or "HEAD"
    sha = git.resolve(mirror, rev)
    data, size = git.blob(mirror, sha, path)
    binary = b"\0" in data[:8000]
    too_big = size > git.MAX_BLOB_BYTES
    text = None if binary or too_big else data.decode("utf-8", "replace")
    history_shas = git.rev_list(mirror, [sha], 20, [git._clean_path(path)])
    hist = db.execute(select(RepoCommit).where(RepoCommit.repository_id == repo.id, RepoCommit.sha.in_(history_shas))
                      .order_by(RepoCommit.committed_at.desc())).scalars().all()
    ext = Path(path).suffix.lower()
    return {"ref": rev, "sha": sha, "path": git._clean_path(path), "size": size, "binary": binary, "too_big": too_big,
            "text": text, "language": LANG.get(ext, "text"), "history": [commit_out(repo, c) for c in hist],
            "url": web_link(repo, "file", rev, path)}


def raw_file(repo: Repository, ref: str | None, path: str) -> tuple[bytes, str]:
    mirror = _ready(repo)
    sha = git.resolve(mirror, ref or repo.default_branch or "HEAD")
    data, _ = git.blob(mirror, sha, path)
    return data, Path(path).name


def branches(db: Session, project: Project, repo: Repository) -> list[dict[str, Any]]:
    out = []
    for r in sorted(repo.refs, key=lambda r: (r["kind"] != "branch", r["name"] != repo.default_branch, r["name"])):
        keys = set(KEY_RE.findall(r["name"].upper()))
        items = db.execute(select(Item.key, Item.title).where(Item.project_id == project.id, Item.key.in_(keys),
                                                              Item.deleted_at.is_(None))).all() if keys else []
        head = db.execute(select(RepoCommit).where(RepoCommit.repository_id == repo.id,
                                                   RepoCommit.sha == r["sha"])).scalar_one_or_none()
        out.append({**r, "default": r["name"] == repo.default_branch,
                    "items": [{"key": k, "title": t} for k, t in items],
                    "head": commit_out(repo, head) if head else None,
                    "url": web_link(repo, "branch", r["name"]) if r["kind"] == "branch" else None})
    return out


def create_branch(db: Session, project: Project, actor: User, repo: Repository, *, name: str,
                  source: str | None, item: Item | None) -> dict[str, Any]:
    mirror = _ready(repo)
    auth = _auth(repo)
    local = repo.provider == "git" and not repo.url.startswith(("http://", "https://"))
    if not auth and not local:
        raise ValidationFailed(f"Creating branches in {repo.name} needs an access token with write permission "
                               "(repository settings)")
    name = (name or "").strip()
    if any(r["kind"] == "branch" and r["name"] == name for r in repo.refs):
        raise Conflict(f"Branch {name} already exists in {repo.name}")
    sha = git.resolve(mirror, source or repo.default_branch or "HEAD")
    try:
        git.push_branch(mirror, repo.url, auth, local, sha, name)
    except git.GitError as exc:
        raise ValidationFailed(f"{repo.name} refused the branch: {exc}") from None
    repo.refs = [*repo.refs, {"name": name, "kind": "branch", "sha": sha, "date": datetime.now(UTC).isoformat()}]
    repo.next_sync_at = utcnow()
    audit.record(db, actor=actor, action="repository.branch_created", entity_type="item" if item else "project",
                 entity_id=item.id if item else project.id, project_id=project.id,
                 summary=f"Created branch {name} in {repo.name}" + (f" for {item.key}" if item else ""),
                 details={"repository": str(repo.id), "branch": name, "sha": sha},
                 related_ids=[item.id] if item else None)
    return {"name": name, "sha": sha, "url": web_link(repo, "branch", name)}

