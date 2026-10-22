"""Document history and document comparison.

* **History** — every change that touched a document or any item that was ever part of it (content versions,
  lifecycle, outline changes, comments, baselines). Each entry is a point in time the document can be opened at.
* **Compare** — two document states side by side: revisions of the same document, baseline vs. baseline or live,
  a branch vs. its master, or two different documents (also across projects). Items are paired by identity,
  branch relation, ReqIF identity or title; moves are detected with a longest-common-subsequence over the
  paired items; text changes come with a word-level diff.
"""

from __future__ import annotations

import difflib
import re
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from almlight.core.errors import ValidationFailed
from almlight.core.richtext import html_diff, to_text
from almlight.modules.audit.models import AuditEntry
from almlight.modules.baselines.models import Baseline, BaselineItem
from almlight.modules.branches.models import BranchItem
from almlight.modules.integrations.models import ExternalRef
from almlight.modules.io.document_snapshot import DocNode, DocSnapshot, build_snapshot
from almlight.modules.items.models import Item
from almlight.modules.links.models import Link
from almlight.modules.projects.models import Project

_WORD = re.compile(r"\s+|[^\s\w]|\w+")


def all_time_members(db: Session, project: Project, root: Item) -> set[uuid.UUID]:
    """Every item that was ever part of the document (including removed and moved-out ones)."""
    structural = project.model.structural_link_types()
    seen = {root.id}
    frontier = [root.id]
    while frontier:
        rows = db.execute(select(Link.target_id).where(Link.source_id.in_(frontier), Link.type_key.in_(structural))
                          ).scalars().all()
        frontier = [r for r in set(rows) if r not in seen]
        seen.update(frontier)
    return seen


def history(db: Session, project: Project, root: Item, limit: int = 500) -> dict[str, Any]:
    members = all_time_members(db, project, root)
    keys = {i.id: i.key for i in db.execute(select(Item).where(Item.id.in_(members))).scalars()}
    entries = db.execute(
        select(AuditEntry).where(AuditEntry.project_id == project.id,
                                 or_(AuditEntry.related_ids.overlap(list(members)),
                                     AuditEntry.entity_id.in_([str(m) for m in members])))
        .order_by(AuditEntry.id.desc()).limit(limit)
    ).scalars().all()
    baselines = db.execute(
        select(Baseline).join(BaselineItem, BaselineItem.baseline_id == Baseline.id)
        .where(Baseline.project_id == project.id, BaselineItem.item_id == root.id).order_by(Baseline.created_at.desc())
    ).scalars().all()
    return {
        "document": root.key,
        "created_at": root.created_at.isoformat(),
        "entries": [{"id": e.id, "ts": e.ts.isoformat(), "actor": e.actor_name, "action": e.action,
                     "summary": e.summary,
                     "items": sorted({keys[r] for r in e.related_ids if r in keys})} for e in entries],
        "baselines": [{"id": str(b.id), "name": b.name, "created_at": b.created_at.isoformat(),
                       "revision_rule": b.revision_rule, "scope_is_document": b.scope_root_id == root.id}
                      for b in baselines],
    }


# --- comparison ----------------------------------------------------------------------------------


def word_diff(old: str, new: str) -> list[dict[str, str]]:
    a, b = _WORD.findall(old or ""), _WORD.findall(new or "")
    out: list[dict[str, str]] = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op == "equal":
            out.append({"op": "equal", "text": "".join(a[i1:i2])})
        else:
            if i2 > i1:
                out.append({"op": "delete", "text": "".join(a[i1:i2])})
            if j2 > j1:
                out.append({"op": "insert", "text": "".join(b[j1:j2])})
    return out


def _flatten(snap: DocSnapshot) -> list[tuple[DocNode, str | None]]:
    """Document order with the key of each node's parent."""
    out: list[tuple[DocNode, str | None]] = []

    def walk(nodes: list[DocNode], parent: str | None) -> None:
        for n in nodes:
            out.append((n, parent))
            walk(n.children, n.key)

    walk(snap.root.children, None)
    return out


def _norm_title(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def _pairing(db: Session, left: list[DocNode], right: list[DocNode]) -> dict[uuid.UUID, uuid.UUID]:
    """left item id -> right item id."""
    pairs: dict[uuid.UUID, uuid.UUID] = {}
    right_ids = {n.item_id for n in right}
    used: set[uuid.UUID] = set()
    for n in left:  # 1. same item (revisions of one document, reused items)
        if n.item_id in right_ids:
            pairs[n.item_id] = n.item_id
            used.add(n.item_id)
    lefts = [n.item_id for n in left if n.item_id not in pairs]
    rights = [i for i in right_ids if i not in used]
    if lefts and rights:  # 2. branch relation (either direction)
        for bi in db.execute(select(BranchItem).where(
                or_((BranchItem.source_item_id.in_(lefts)) & (BranchItem.branch_item_id.in_(rights)),
                    (BranchItem.branch_item_id.in_(lefts)) & (BranchItem.source_item_id.in_(rights))))).scalars():
            lft, rgt = ((bi.source_item_id, bi.branch_item_id) if bi.source_item_id in lefts
                        else (bi.branch_item_id, bi.source_item_id))
            if lft not in pairs and rgt not in used:
                pairs[lft] = rgt
                used.add(rgt)
    lefts = [i for i in lefts if i not in pairs]
    rights = [i for i in rights if i not in used]
    if lefts and rights:  # 3. same ReqIF identity (the same partner object imported twice)
        refs = db.execute(select(ExternalRef).where(ExternalRef.system == "reqif", ExternalRef.kind == "spec_object",
                                                    ExternalRef.item_id.in_(lefts + rights))).scalars().all()
        by_ext: dict[str, list[uuid.UUID]] = {}
        for r in refs:
            by_ext.setdefault(r.external_id, []).append(r.item_id)
        for ids in by_ext.values():
            lft = next((i for i in ids if i in lefts and i not in pairs), None)
            rgt = next((i for i in ids if i in rights and i not in used), None)
            if lft and rgt:
                pairs[lft] = rgt
                used.add(rgt)
    # 4. unique normalised titles of the same type
    by_title: dict[tuple[str, str], list[DocNode]] = {}
    for n in right:
        if n.item_id not in used:
            by_title.setdefault((n.type_key, _norm_title(n.title)), []).append(n)
    for n in left:
        if n.item_id in pairs:
            continue
        cands = by_title.get((n.type_key, _norm_title(n.title)), [])
        if len(cands) == 1 and cands[0].item_id not in used:
            pairs[n.item_id] = cands[0].item_id
            used.add(cands[0].item_id)
    return pairs


def _lcs_keep(seq: list[int]) -> set[int]:
    """Indices (into seq) of a longest increasing subsequence — the items that did not move."""
    import bisect

    tails: list[int] = []
    tails_idx: list[int] = []
    prev = [-1] * len(seq)
    for i, v in enumerate(seq):
        pos = bisect.bisect_left(tails, v)
        if pos == len(tails):
            tails.append(v)
            tails_idx.append(i)
        else:
            tails[pos] = v
            tails_idx[pos] = i
        prev[i] = tails_idx[pos - 1] if pos > 0 else -1
    keep: set[int] = set()
    k = tails_idx[-1] if tails_idx else -1
    while k >= 0:
        keep.add(k)
        k = prev[k]
    return keep


def _node_view(n: DocNode | None) -> dict[str, Any] | None:
    if n is None:
        return None
    return {"item_id": str(n.item_id), "key": n.key, "type_key": n.type_key, "type_label": n.type_label,
            "title": n.title, "display_title": n.display_title, "number": n.number, "description": n.description,
            "state": n.state, "version": n.version, "applicability": n.applicability, "is_heading": n.is_heading,
            "fields": [{"label": a, "value": b} for a, b in n.fields]}


def compare(db: Session, left: DocSnapshot, right: DocSnapshot, *, fields: list[str] | None = None) -> dict[str, Any]:
    lflat, rflat = _flatten(left), _flatten(right)
    lnodes, rnodes = [n for n, _ in lflat], [n for n, _ in rflat]
    pairs = _pairing(db, lnodes, rnodes)
    rindex = {n.item_id: i for i, n in enumerate(rnodes)}
    lparent = {n.item_id: p for n, p in lflat}
    rparent = {n.item_id: p for n, p in rflat}
    lkey_to_r = {}
    for lid, rid in pairs.items():
        ln = next(n for n in lnodes if n.item_id == lid)
        rn = rnodes[rindex[rid]]
        lkey_to_r[ln.key] = rn.key
    paired_left = [n for n in lnodes if n.item_id in pairs]
    order = [rindex[pairs[n.item_id]] for n in paired_left]
    keep = _lcs_keep(order)
    moved_left = {paired_left[i].item_id for i in range(len(paired_left)) if i not in keep}

    def changes(ln: DocNode, rn: DocNode) -> list[dict[str, Any]]:
        out = []
        if ln.title != rn.title:
            out.append({"field": "title", "old": ln.title, "new": rn.title, "diff": word_diff(ln.title, rn.title)})
        if ln.description != rn.description:
            out.append({"field": "description", "old": ln.description, "new": rn.description,
                        "diff": word_diff(to_text(ln.description), to_text(rn.description)),
                        "html_diff": html_diff(ln.description, rn.description)})
        for name, a, b in (("state", ln.state, rn.state), ("version", ln.version, rn.version),
                           ("applicability", ln.applicability, rn.applicability)):
            if a != b and (name != "version" or ln.item_id == rn.item_id):
                out.append({"field": name, "old": a, "new": b})
        keys = sorted(set(ln.fields_raw) | set(rn.fields_raw))
        for k in keys:
            if fields and k not in fields:
                continue
            a, b = ln.fields_raw.get(k), rn.fields_raw.get(k)
            if a != b:
                out.append({"field": f"fields.{k}", "old": a, "new": b})
        return out

    rows: list[dict[str, Any]] = []
    lpos = {n.item_id: i for i, n in enumerate(lnodes)}
    removed_by_anchor: dict[int, list[DocNode]] = {}
    for n in lnodes:
        if n.item_id not in pairs:
            # anchor the removed item after the right-side position of its closest paired predecessor
            anchor = -1
            for prev in reversed(lnodes[: lpos[n.item_id]]):
                if prev.item_id in pairs:
                    anchor = rindex[pairs[prev.item_id]]
                    break
            removed_by_anchor.setdefault(anchor, []).append(n)
    reverse_pairs = {v: k for k, v in pairs.items()}
    for n in removed_by_anchor.get(-1, []):
        rows.append({"status": "removed", "left": _node_view(n), "right": None, "changes": [], "moved": False})
    for i, rn in enumerate(rnodes):
        lid = reverse_pairs.get(rn.item_id)
        if lid is None:
            rows.append({"status": "added", "left": None, "right": _node_view(rn), "changes": [], "moved": False})
        else:
            ln = lnodes[lpos[lid]]
            ch = changes(ln, rn)
            parent_changed = lkey_to_r.get(lparent[lid] or "", lparent[lid]) != rparent[rn.item_id]
            moved = lid in moved_left or parent_changed
            status = "changed" if ch else "moved" if moved else "unchanged"
            rows.append({"status": status, "left": _node_view(ln), "right": _node_view(rn), "changes": ch,
                         "moved": moved})
        for n in removed_by_anchor.get(i, []):
            rows.append({"status": "removed", "left": _node_view(n), "right": None, "changes": [], "moved": False})
    summary: dict[str, int] = {"added": 0, "removed": 0, "changed": 0, "moved": 0, "unchanged": 0}
    for r in rows:
        summary[r["status"]] += 1
        if r["status"] == "changed" and r["moved"]:
            summary["moved"] += 1
    return {"left": _side(left), "right": _side(right), "summary": summary, "rows": rows}


def _side(s: DocSnapshot) -> dict[str, Any]:
    return {"project": s.project_key, "document": s.root.key, "title": s.root.title, "source": s.source,
            "mode": s.mode, "at": s.at.isoformat() if s.at else None, "baseline": s.baseline,
            "version": s.root.version}


def parse_at(value: str | None) -> datetime | None:
    if not value:
        return None
    value = value.strip().replace(" ", "+")  # an unencoded "+" in a query string arrives as a space
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValidationFailed("'at' must be an ISO timestamp") from None
    if dt.tzinfo is None:
        from datetime import UTC

        dt = dt.replace(tzinfo=UTC)
    return dt


def snapshot_for(db: Session, project: Project, root: Item, *, at: str | None, baseline: uuid.UUID | None,
                 variant: str | None = None) -> DocSnapshot:
    return build_snapshot(db, project, root, at=parse_at(at), baseline_id=baseline, variant_key=variant)
