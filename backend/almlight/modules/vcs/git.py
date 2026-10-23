"""Thin, safe wrapper around the ``git`` command line for bare mirrors of connected repositories.

Safety: no interactive prompts, no credential helpers, only the allowed transport protocols (https/http, and file
for permitted local paths), every URL after ``--``, credentials passed in the environment (``GIT_CONFIG_*``) and
not on the command line, and a timeout on every call. Mirrors are bare, so no hooks or checkouts run.
"""

from __future__ import annotations

import base64
import os
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from almlight.core.config import get_settings
from almlight.core.errors import NotFound, ValidationFailed

SEP_REC, SEP_FIELD = "\x1e", "\x1f"
LOG_FORMAT = SEP_REC + SEP_FIELD.join(["%H", "%P", "%an", "%ae", "%aI", "%cn", "%cI", "%B"]) + SEP_FIELD
MAX_FILES_PER_COMMIT = 300
MAX_DIFF_BYTES = 600_000
MAX_BLOB_BYTES = 1_000_000


class GitError(Exception):
    pass


@dataclass
class Auth:
    token: str | None = None
    user: str | None = None


@dataclass
class CommitInfo:
    sha: str
    parents: list[str]
    author_name: str
    author_email: str
    authored_at: datetime
    committer_name: str
    committed_at: datetime
    message: str
    files: list[dict] = field(default_factory=list)
    additions: int = 0
    deletions: int = 0
    file_count: int = 0


def _env(auth: Auth | None, allow_file: bool) -> dict[str, str]:
    allowed = ["https", "http"] + (["file"] if allow_file else [])
    cfg: list[tuple[str, str]] = [("protocol.allow", "never"), ("credential.helper", ""), ("core.askPass", ""),
                                  *((f"protocol.{p}.allow", "always") for p in allowed)]
    if auth and auth.token:
        basic = base64.b64encode(f"{auth.user or 'x-access-token'}:{auth.token}".encode()).decode()
        cfg.append(("http.extraHeader", f"Authorization: Basic {basic}"))
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(get_settings().data_dir),
           "GIT_TERMINAL_PROMPT": "0", "GIT_ASKPASS": "", "SSH_ASKPASS": "", "LC_ALL": "C.UTF-8",
           "GIT_CONFIG_NOSYSTEM": "1", "GIT_LITERAL_PATHSPECS": "1", "GIT_CONFIG_COUNT": str(len(cfg))}
    for i, (k, v) in enumerate(cfg):
        env[f"GIT_CONFIG_KEY_{i}"], env[f"GIT_CONFIG_VALUE_{i}"] = k, v
    return env


def run(args: list[str], *, cwd: Path | None = None, auth: Auth | None = None, allow_file: bool = False,
        stdin: bytes | None = None, timeout: int | None = None) -> bytes:
    try:
        proc = subprocess.run(["git", *args], cwd=cwd, env=_env(auth, allow_file), input=stdin, capture_output=True,
                              timeout=timeout or get_settings().git_timeout_seconds, check=False)
    except subprocess.TimeoutExpired:
        raise GitError("git timed out") from None
    except FileNotFoundError:
        raise GitError("git is not installed on the server") from None
    if proc.returncode != 0:
        msg = proc.stderr.decode("utf-8", "replace").strip().splitlines()
        # never echo credentials; git does not print the extra header, but be safe with URLs containing user:pass@
        text = " ".join(line for line in msg if line)[-500:]
        raise GitError(text.replace(auth.token, "***") if auth and auth.token else text)
    return proc.stdout


def check_url(url: str) -> tuple[str, bool]:
    """Validate a repository location. Returns (normalised url, is_local)."""
    url = (url or "").strip()
    if not url or any(ch.isspace() for ch in url) or url.startswith("-") or len(url) > 1000:
        raise ValidationFailed("Enter the clone URL of the repository, e.g. https://github.com/owner/repo.git")
    if url.startswith(("https://", "http://")):
        return url, False
    if url.startswith(("ssh://", "git@", "git://")):
        raise ValidationFailed("Use the HTTPS clone URL (SSH needs keys on the server); "
                               "add a token for private repositories")
    path = Path(url[7:] if url.startswith("file://") else url)
    if not path.is_absolute():
        raise ValidationFailed("Enter an HTTPS clone URL or an absolute path to a repository on the server")
    settings = get_settings()
    resolved = path.resolve()
    allowed_root = settings.local_repos_dir.resolve()
    if not settings.git_allow_local_paths and allowed_root not in (resolved, *resolved.parents):
        raise ValidationFailed(f"Local repositories must be below {allowed_root} "
                               "(or allow local paths in the configuration)")
    return str(resolved), True


def ls_remote(url: str, auth: Auth | None, local: bool) -> list[tuple[str, str]]:
    out = run(["ls-remote", "--heads", "--tags", "--", url], auth=auth, allow_file=local, timeout=60)
    return [tuple(line.split("\t", 1)) for line in out.decode().splitlines() if "\t" in line]  # type: ignore[misc]


def mirror(path: Path, url: str, auth: Auth | None, local: bool) -> None:
    """Create the bare mirror (branches and tags only) or fetch it."""
    if not (path / "HEAD").exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        run(["init", "--bare", "--quiet", str(path)])
        run(["config", "remote.origin.url", url], cwd=path)
        run(["config", "--replace-all", "remote.origin.fetch", "+refs/heads/*:refs/heads/*"], cwd=path)
        run(["config", "--add", "remote.origin.fetch", "+refs/tags/*:refs/tags/*"], cwd=path)
    else:
        run(["config", "remote.origin.url", url], cwd=path)
    run(["fetch", "--prune", "--quiet", "--no-recurse-submodules", "origin"], cwd=path, auth=auth, allow_file=local)
    try:  # default branch of the remote, for browsing
        head = run(["ls-remote", "--symref", "--", url, "HEAD"], auth=auth, allow_file=local, timeout=60).decode()
        for line in head.splitlines():
            if line.startswith("ref: ") and line.endswith("\tHEAD"):
                run(["symbolic-ref", "HEAD", line[5:].split("\t")[0]], cwd=path)
    except GitError:
        pass


def refs(path: Path) -> list[dict]:
    fmt = f"%(refname){SEP_FIELD}%(objectname){SEP_FIELD}%(*objectname){SEP_FIELD}%(committerdate:iso-strict)"
    out = run(["for-each-ref", f"--format={fmt}", "refs/heads", "refs/tags"], cwd=path).decode()
    result = []
    for line in out.splitlines():
        name, sha, peeled, date = (line.split(SEP_FIELD) + ["", "", "", ""])[:4]
        kind = "branch" if name.startswith("refs/heads/") else "tag"
        result.append({"name": name.split("/", 2)[2], "kind": kind, "sha": peeled or sha, "date": date or None})
    return result


def default_branch(path: Path) -> str | None:
    try:
        return run(["symbolic-ref", "--short", "HEAD"], cwd=path).decode().strip() or None
    except GitError:
        return None


def rev_list(path: Path, revs: list[str], limit: int, paths: list[str] | None = None) -> list[str]:
    args = ["rev-list", f"--max-count={limit}", *revs]
    if paths:
        args += ["--", *paths]
    return run(args, cwd=path).decode().split()


def commits(path: Path, shas: list[str]) -> list[CommitInfo]:
    if not shas:
        return []
    out = run(["log", "--no-walk=unsorted", "--stdin", f"--format={LOG_FORMAT}", "--numstat", "--no-color",
               "--no-renames"], cwd=path, stdin=("\n".join(shas) + "\n").encode())
    result = []
    for rec in out.decode("utf-8", "replace").split(SEP_REC)[1:]:
        parts = rec.split(SEP_FIELD)
        if len(parts) < 9:
            continue
        sha, parents, an, ae, ad, cn, cd, body, rest = parts[:9]
        info = CommitInfo(sha=sha, parents=parents.split(), author_name=an, author_email=ae,
                          authored_at=datetime.fromisoformat(ad), committer_name=cn,
                          committed_at=datetime.fromisoformat(cd), message=body.strip())
        for line in rest.strip().splitlines():
            cols = line.split("\t")
            if len(cols) != 3:
                continue
            add = int(cols[0]) if cols[0].isdigit() else 0
            dele = int(cols[1]) if cols[1].isdigit() else 0
            info.additions += add
            info.deletions += dele
            info.file_count += 1
            if len(info.files) < MAX_FILES_PER_COMMIT:
                info.files.append({"path": cols[2], "additions": add, "deletions": dele, "binary": cols[0] == "-"})
        result.append(info)
    return result


def show_patch(path: Path, sha: str) -> tuple[list[dict], bool]:
    """Unified diff of a commit against its first parent, split per file. Returns (files, truncated)."""
    out = run(["show", "--format=", "--patch", "--no-color", "-M", "--first-parent", "-m", sha], cwd=path)
    truncated = len(out) > MAX_DIFF_BYTES
    text = out[:MAX_DIFF_BYTES].decode("utf-8", "replace")
    files: list[dict] = []
    for chunk in text.split("\ndiff --git ") if text else []:
        chunk = chunk if chunk.startswith("diff --git ") else "diff --git " + chunk
        head = chunk.split("\n", 1)[0]
        old_path = new_path = head[len("diff --git "):]
        if " b/" in head:
            a, b = head[len("diff --git "):].split(" b/", 1)
            old_path, new_path = a[2:] if a.startswith("a/") else a, b
        status = "modified"
        if "\nnew file mode" in chunk[:400]:
            status = "added"
        elif "\ndeleted file mode" in chunk[:400]:
            status = "deleted"
        elif "\nrename from " in chunk[:400]:
            status = "renamed"
        binary = "\nBinary files " in chunk[:600]
        hunk_at = chunk.find("\n@@")
        files.append({"path": new_path, "old_path": old_path, "status": status, "binary": binary,
                      "patch": chunk[hunk_at + 1:] if hunk_at >= 0 else ""})
    return files, truncated


def contains(path: Path, sha: str) -> list[str]:
    try:
        out = run(["for-each-ref", "--contains", sha, "--format=%(refname:short)", "refs/heads"], cwd=path)
    except GitError:
        return []
    return out.decode().split()


def resolve(path: Path, ref: str) -> str:
    if not ref or ref.startswith("-") or any(ch.isspace() for ch in ref) or ".." in ref:
        raise ValidationFailed("Invalid branch, tag or commit")
    try:
        return run(["rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"], cwd=path).decode().strip()
    except GitError:
        raise ValidationFailed(f"'{ref}' is not a branch, tag or commit of this repository") from None


def _clean_path(p: str) -> str:
    p = (p or "").strip().strip("/")
    if p.startswith("-") or ".." in p.split("/") or len(p) > 1000 or any(ord(ch) < 32 or ord(ch) == 127 for ch in p):
        raise ValidationFailed("Invalid path")
    return p


def tree(path: Path, sha: str, sub: str) -> list[dict]:
    sub = _clean_path(sub)
    out = run(["ls-tree", "-l", "-z", sha, "--", f"{sub}/" if sub else "."], cwd=path)
    entries = []
    for rec in out.decode("utf-8", "replace").split("\0"):
        if not rec:
            continue
        meta, name = rec.split("\t", 1)
        mode, kind, obj, size = meta.split()
        entries.append({"name": name.rsplit("/", 1)[-1], "path": name, "kind": "dir" if kind == "tree" else
                        "submodule" if kind == "commit" else "file", "size": int(size) if size.isdigit() else None})
    if sub and not entries:  # Git has no empty folders: the path is a file or does not exist
        raise NotFound(f"'{sub}' is not a folder in this revision")
    entries.sort(key=lambda e: (e["kind"] != "dir", e["name"].lower()))
    return entries


def blob(path: Path, sha: str, file: str) -> tuple[bytes, int]:
    file = _clean_path(file)
    spec = f"{sha}:{file}"
    try:
        size = int(run(["cat-file", "-s", spec], cwd=path).decode().strip())
    except GitError:
        raise ValidationFailed(f"'{file}' does not exist in this revision") from None
    data = run(["cat-file", "blob", spec], cwd=path) if size <= MAX_BLOB_BYTES * 5 else b""
    return data, size


def push_branch(path: Path, url: str, auth: Auth | None, local: bool, sha: str, name: str) -> None:
    try:
        run(["check-ref-format", "--branch", name])
    except GitError:
        raise ValidationFailed(f"'{name}' is not a valid branch name") from None
    run(["push", "--quiet", "--", url, f"{sha}:refs/heads/{name}"], cwd=path, auth=auth, allow_file=local, timeout=120)
