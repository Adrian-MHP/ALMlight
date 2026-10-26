"""Git interface: connecting repositories (validation, encrypted token), sync and commit index, linked revisions
from commit messages and by hand, browsing (commits, diff, tree, file, branches), creating branches, the commit
query, pull requests of GitHub repositories, push webhooks and permissions."""

import os
import shutil
import subprocess
import urllib.parse
import uuid

import pytest
from conftest import new_item

from almlight.core.config import get_settings

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


def _git(path, *args, days=0):
    env = {"PATH": os.environ["PATH"], "HOME": str(path), "GIT_CONFIG_NOSYSTEM": "1",
           "GIT_AUTHOR_NAME": "Carla", "GIT_AUTHOR_EMAIL": "carla@example.com",
           "GIT_COMMITTER_NAME": "Carla", "GIT_COMMITTER_EMAIL": "carla@example.com",
           "GIT_AUTHOR_DATE": f"2026-10-{10 + days:02d}T10:00:00+00:00",
           "GIT_COMMITTER_DATE": f"2026-10-{10 + days:02d}T10:00:00+00:00"}
    return subprocess.run(["git", *args], cwd=path, env=env, check=True, capture_output=True).stdout.decode().strip()


def _repo(keys):
    path = get_settings().local_repos_dir / f"t-{uuid.uuid4().hex[:8]}"
    path.mkdir(parents=True)
    _git(path, "init", "-q", "-b", "main")
    files = [("src/range.c", "int full_scale = 10000;\n", f"Range check for 0-10 bar ({keys[0]})"),
             ("src/range.c", "int full_scale = 100000;\n", f"Extend range, refs {keys[0]} and {keys[1]}"),
             ("docs/notes.md", "# Notes\n", "Notes without a key"),
             ("src/drift.c", "float k = 0.1f;\n", "Fix drift, closes NOPE-99")]
    for n, (f, content, msg) in enumerate(files):
        (path / f).parent.mkdir(parents=True, exist_ok=True)
        (path / f).write_text(content)
        _git(path, "add", "-A", days=n)
        _git(path, "commit", "-q", "-m", msg, days=n)
    _git(path, "checkout", "-q", "-b", f"feature/{keys[1]}-diagnostics")
    (path / "src/diag.c").write_text("int diag(void) { return 0; }\n")
    _git(path, "add", "-A", days=5)
    _git(path, "commit", "-q", "-m", "Diagnostics", days=5)
    _git(path, "checkout", "-q", "main")
    _git(path, "tag", "v1.0")
    return path


def test_connect_sync_and_linked_revisions(team, project, db):
    c, m, v = team["contributor"], team["manager"], team["viewer"]
    p = f"/projects/{project}"
    a = new_item(c, project, "system_requirement", "Measuring range")["key"]
    b = new_item(c, project, "system_requirement", "Diagnostics")["key"]
    path = _repo([a, b])
    # connecting needs a manager and a valid location; tokens are stored sealed and never returned
    c.post(f"{p}/repositories", {"name": "fw", "url": str(path)}, expect=403)
    for bad, msg in [("git@github.com:o/r.git", "HTTPS"), ("relative/path", "absolute path"),
                     ("/etc", "must be below"), ("--upload-pack=x", "clone URL")]:
        err = m.post(f"{p}/repositories", {"name": "x", "url": bad}, expect=422)
        assert msg in err["error"]["message"], (bad, err)
    # an unreachable or refused repository says what to do, instead of echoing the Git output
    err = m.post(f"{p}/repositories", {"name": "x", "url": "https://127.0.0.1:9/nope.git"}, expect=422)
    assert "cannot be reached" in err["error"]["message"] or "Cannot reach" in err["error"]["message"], err
    repo = m.post(f"{p}/repositories", {"name": "fw", "url": str(path), "token": "secret-token-123"}, expect=201)
    assert repo["sync"]["ok"] and repo["sync"]["new_commits"] == 5 and repo["sync"]["linked"] == 3
    assert repo["has_token"] and "token" not in repo and repo["default_branch"] == "main"
    assert repo["branch_count"] == 2 and repo["tag_count"] == 1
    from almlight.modules.vcs.models import Repository

    stored = db.get(Repository, uuid.UUID(repo["id"]))
    assert stored.token_enc and "secret-token-123" not in stored.token_enc
    m.post(f"{p}/repositories", {"name": "fw", "url": str(path)}, expect=409)
    rid = repo["id"]
    # linked revisions from commit messages (keys of other projects are ignored)
    revs = v.get(f"{p}/items/{a}/revisions")
    assert [r["title"] for r in revs["revisions"]] == [f"Extend range, refs {a} and {b}", f"Range check for 0-10 bar ({a})"]
    assert revs["revisions"][0]["source"] == "message" and revs["revisions"][0]["repository"]["name"] == "fw"
    rb = v.get(f"{p}/items/{b}/revisions")
    assert len(rb["revisions"]) == 1 and rb["branches"][0]["name"] == f"feature/{b}-diagnostics"
    assert rb["branch_name"].startswith(f"feature/{b}-diagnostics")
    # link a revision by hand (contributor), unique, removable; message links stay
    notes = c.get(f"{p}/repositories/{rid}/commits?q=Notes")["commits"][0]
    v.post(f"{p}/items/{b}/revisions", {"repository": rid, "sha": notes["sha"][:7]}, expect=403)
    link = c.post(f"{p}/items/{b}/revisions", {"repository": rid, "sha": notes["sha"][:7]}, expect=201)
    c.post(f"{p}/items/{b}/revisions", {"repository": rid, "sha": notes["sha"]}, expect=409)
    c.post(f"{p}/items/{b}/revisions", {"repository": rid, "sha": "zz"}, expect=422)
    c.post(f"{p}/items/{b}/revisions", {"repository": rid, "sha": "abcdef12"}, expect=404)
    assert len(c.get(f"{p}/items/{b}/revisions")["revisions"]) == 2
    msg_link = c.get(f"{p}/items/{a}/revisions")["revisions"][0]["link_id"]
    c.delete(f"{p}/items/{a}/revisions/{msg_link}", expect=422)
    c.delete(f"{p}/items/{b}/revisions/{link['link_id']}")
    # the commit query: items with / without linked commits, by hash
    with_commits = {i["key"] for i in c.get(f"{p}/items?ql=" + urllib.parse.quote("commits:true") + "&limit=100")["items"]}
    assert with_commits == {a, b}
    sha = revs["revisions"][1]["sha"]
    assert {i["key"] for i in c.get(f"{p}/items?ql=commit:{sha[:9]}")["items"]} == {a}
    gap = {i["key"] for i in c.get(f"{p}/items?type=system_requirement&ql=" + urllib.parse.quote("NOT commits:true"))["items"]}
    assert a not in gap and b not in gap
    # sync is incremental and idempotent
    again = c.post(f"{p}/repositories/{rid}/sync")
    assert again["sync"]["new_commits"] == 0 and again["commit_count"] == 5
    (path / "src/range.c").write_text("int full_scale = 160000;\n")
    _git(path, "add", "-A", days=7)
    _git(path, "commit", "-q", "-m", f"160 bar ({b})", days=7)
    res = c.post(f"{p}/repositories/{rid}/sync")["sync"]
    assert res["new_commits"] == 1 and res["linked"] == 1
    assert len(c.get(f"{p}/items/{b}/revisions")["revisions"]) == 2


def test_browse_branches_files_and_create_branch(team, project):
    c, m, v = team["contributor"], team["manager"], team["viewer"]
    p = f"/projects/{project}"
    a = new_item(c, project, "system_requirement", "Range")["key"]
    b = new_item(c, project, "system_requirement", "Diagnostics")["key"]
    path = _repo([a, b])
    rid = m.post(f"{p}/repositories", {"name": "fw", "url": str(path)}, expect=201)["id"]
    hist = v.get(f"{p}/repositories/{rid}/commits")
    assert hist["total"] == 5 and hist["commits"][0]["title"] == "Diagnostics"
    assert v.get(f"{p}/repositories/{rid}/commits?ref=main")["total"] == 4
    assert v.get(f"{p}/repositories/{rid}/commits?path=src/range.c")["total"] == 2
    assert v.get(f"{p}/repositories/{rid}/commits?item={a}")["total"] == 2
    ext = v.get(f"{p}/repositories/{rid}/commits?q=Extend")["commits"][0]
    assert {i["key"] for i in ext["items"]} == {a, b}
    detail = v.get(f"{p}/repositories/{rid}/commits/{ext['sha'][:8]}")
    assert detail["files"][0]["path"] == "src/range.c" and "+int full_scale = 100000;" in detail["files"][0]["patch"]
    assert detail["files"][0]["additions"] == 1 and detail["branches"] == sorted(detail["branches"]) and "main" in detail["branches"]
    v.get(f"{p}/repositories/{rid}/commits/{'0' * 8}", expect=404)
    root = v.get(f"{p}/repositories/{rid}/tree")
    assert [e["name"] for e in root["entries"]] == ["docs", "src"] and root["ref"] == "main"
    src = v.get(f"{p}/repositories/{rid}/tree?path=src&ref=feature/{b}-diagnostics")
    assert {e["name"] for e in src["entries"]} == {"range.c", "drift.c", "diag.c"}
    f = v.get(f"{p}/repositories/{rid}/file?path=src/range.c")
    assert f["text"] == "int full_scale = 100000;\n" and f["language"] == "c" and len(f["history"]) == 2
    old = v.get(f"{p}/repositories/{rid}/file?path=src/range.c&ref=v1.0")
    assert old["text"].startswith("int full_scale = 100000")
    raw = v.get(f"{p}/repositories/{rid}/raw?path=docs/notes.md")
    assert raw.content == b"# Notes\n" and "sandbox" in raw.headers["content-security-policy"]
    v.get(f"{p}/repositories/{rid}/file?path=../etc/passwd", expect=422)
    v.get(f"{p}/repositories/{rid}/tree?ref=--output=x", expect=422)
    v.get(f"{p}/repositories/{rid}/file?path=src/none.c", expect=422)
    v.get(f"{p}/repositories/{rid}/tree?path=src/range.c", expect=404)  # a file, not a folder
    v.get(f"{p}/repositories/{rid}/tree?path=nothing", expect=404)
    v.get(f"{p}/repositories/{rid}/tree?path=src%00x", expect=422)
    v.get(f"{p}/repositories/{rid}/file?path=src/%0arange.c", expect=422)
    assert v.get(f"{p}/repositories/{rid}/commits?path=:(exclude)src")["total"] == 0  # literal pathspecs, no magic
    branches = v.get(f"{p}/repositories/{rid}/branches")
    assert branches[0]["name"] == "main" and branches[0]["default"]
    feat = next(x for x in branches if x["name"].startswith("feature/"))
    assert feat["items"] == [{"key": b, "title": "Diagnostics"}] and any(x["kind"] == "tag" for x in branches)
    # create a branch for an item (pushed to the remote), refuse duplicates and bad names
    v.post(f"{p}/repositories/{rid}/branches", {"name": f"feature/{a}-x", "item": a}, expect=403)
    made = c.post(f"{p}/repositories/{rid}/branches", {"name": f"feature/{a}-range", "item": a}, expect=201)
    assert made["name"] == f"feature/{a}-range"
    assert f"feature/{a}-range" in _git(path, "branch", "--list")
    c.post(f"{p}/repositories/{rid}/branches", {"name": f"feature/{a}-range"}, expect=409)
    c.post(f"{p}/repositories/{rid}/branches", {"name": "bad..name"}, expect=422)
    assert any(x["name"] == f"feature/{a}-range" for x in c.get(f"{p}/items/{a}/revisions")["branches"])
    # disconnect: index and mirror are removed
    c.delete(f"{p}/repositories/{rid}", expect=403)
    m.delete(f"{p}/repositories/{rid}")
    assert v.get(f"{p}/repositories") == [] and c.get(f"{p}/items/{a}/revisions")["revisions"] == []


def test_github_pull_requests_and_push_webhook(team, project, db, monkeypatch):
    import httpx

    from almlight.modules.projects.models import Project
    from almlight.modules.vcs import service
    from almlight.modules.vcs.models import Repository

    c = team["contributor"]
    a = new_item(c, project, "system_requirement", "Range")["key"]
    proj = db.query(Project).filter_by(key=project).one()
    repo = Repository(project_id=proj.id, name="gh", url="https://github.com/acme/fw.git", provider="github",
                      web_url="https://github.com/acme/fw", refs=[], meta={})
    db.add(repo)
    db.commit()
    calls = []

    class Resp:
        def __init__(self, status, data, etag=None):
            self.status_code, self._data, self.headers = status, data, {"ETag": etag} if etag else {}

        def json(self):
            return self._data

    pulls = [{"number": 7, "title": f"{a}: extend range", "body": "", "head": {"ref": "feature/x"},
              "base": {"ref": "main"}, "state": "closed", "merged_at": "2026-10-20T10:00:00Z",
              "html_url": "https://github.com/acme/fw/pull/7", "user": {"login": "carla"}, "updated_at": "x"},
             {"number": 8, "title": "Unrelated", "body": None, "head": {"ref": "chore"}, "base": {"ref": "main"},
              "state": "open", "merged_at": None, "html_url": "u", "user": {"login": "x"}, "updated_at": "y"}]

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, url, params=None, headers=None):
            calls.append((url, dict(headers or {})))
            return Resp(304, None) if headers.get("If-None-Match") else Resp(200, pulls, etag='"abc"')

    monkeypatch.setattr(httpx, "Client", FakeClient)
    assert service._sync_pull_requests(db, proj, repo, None) == 1
    db.commit()
    prs = c.get(f"/projects/{project}/items/{a}/revisions")["pull_requests"]
    assert prs[0]["external_id"] == "acme/fw#7" and prs[0]["status"] == "merged"
    assert calls[0][0] == "https://api.github.com/repos/acme/fw/pulls" and "Authorization" not in calls[0][1]
    assert service._sync_pull_requests(db, proj, repo, None) == 1 and calls[1][1]["If-None-Match"] == '"abc"'
    # a push webhook asks for an immediate sync of the matching repository
    repo.next_sync_at = None
    assert service.request_sync(db, proj, "https://github.com/acme/fw") == 1 and repo.next_sync_at is not None


def test_unreachable_messages_tell_the_person_what_to_do():
    from almlight.modules.vcs.service import _unreachable

    prompt = "fatal: could not read Username for 'https://github.com': terminal prompts disabled"
    assert "private or does not exist" in _unreachable(prompt, with_token=False)
    assert "wrong, expired" in _unreachable(prompt, with_token=True)
    assert "wrong, expired" in _unreachable("remote: Invalid username or password. fatal: Authentication failed", True)
    assert "does not know this repository" in _unreachable("remote: Repository not found.", False)
    assert "cannot be reached" in _unreachable("fatal: unable to access: Could not resolve host: nope", False)
    assert _unreachable("something else entirely", False).startswith("Cannot reach the repository:")


def test_concurrent_syncs_index_each_commit_once(team, project):
    """Connecting syncs at once while the background worker may pick up the new repository: syncs of one repository
    run one after the other (a waiting request indexes only what is still new, the worker skips a busy repository)."""
    import threading

    from sqlalchemy import func, select

    from almlight.core.db import session_factory
    from almlight.modules.vcs import service
    from almlight.modules.vcs.models import RepoCommit, Repository

    m = team["manager"]
    a = new_item(team["contributor"], project, "system_requirement", "Concurrent sync")["key"]
    path = _repo([a, a])
    rid = uuid.UUID(m.post(f"/projects/{project}/repositories", {"name": "fw", "url": str(path)}, expect=201)["id"])
    for n in range(3):
        (path / f"src/new{n}.c").write_text(f"int n{n};\n")
        _git(path, "add", "-A", days=10 + n)
        _git(path, "commit", "-q", "-m", f"More for {a} ({n})", days=10 + n)
    results, errors = [], []

    def run():
        try:
            with session_factory()() as s:
                results.append(service.sync(s, s.get(Repository, rid)))
                s.commit()
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=run) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(60)
    assert not errors, errors
    assert sorted(r["new_commits"] for r in results) == [0, 0, 3]
    with session_factory()() as s:
        assert s.execute(select(func.count()).select_from(RepoCommit).where(RepoCommit.repository_id == rid)).scalar() == 8
        assert s.get(Repository, rid).commit_count == 8
        # while a sync holds the repository, the worker skips it instead of waiting
        s.execute(select(Repository.id).where(Repository.id == rid).with_for_update())
        with session_factory()() as worker:
            assert service.sync(worker, worker.get(Repository, rid), wait=False)["busy"]
        s.rollback()
