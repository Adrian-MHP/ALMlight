"""Risk management (FMEA): risk matrix before and after mitigation, risk register, mitigation coverage."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from almlight.core.db import get_db
from almlight.core.deps import current_user
from almlight.modules.identity.models import User
from almlight.modules.items.models import Item
from almlight.modules.links.models import Link
from almlight.modules.projects.access import get_project
from almlight.modules.projects.models import Project

router = APIRouter(prefix="/projects/{project_key}", tags=["risks"])
SCALE = 10


def risk_overview(db: Session, project: Project) -> dict[str, Any]:
    sem = project.model.semantics
    t = project.model.item_type(sem.risk_type) if sem.risk_type else None
    if t is None:
        return {"enabled": False}
    risks = db.execute(select(Item).where(Item.project_id == project.id, Item.type_key == t.key,
                                          Item.deleted_at.is_(None)).order_by(Item.seq)).scalars().all()
    ids = [r.id for r in risks]
    mitigations: dict[Any, int] = {}
    if ids and project.model.link_type(sem.mitigation_link):
        mitigations = dict(db.execute(
            select(Link.source_id, func.count()).where(Link.source_id.in_(ids), Link.type_key == sem.mitigation_link,
                                                      Link.deleted_at.is_(None)).group_by(Link.source_id)).all())
    wf = project.model.workflow_for(t.key)

    def matrix(sev: str, occ: str) -> list[list[int]]:
        m = [[0] * SCALE for _ in range(SCALE)]
        for r in risks:
            s, o = r.fields.get(sev), r.fields.get(occ)
            if isinstance(s, int) and isinstance(o, int) and 1 <= s <= SCALE and 1 <= o <= SCALE:
                m[s - 1][o - 1] += 1
        return m

    rows = []
    for r in risks:
        st = wf.state(r.state) if wf else None
        f = r.fields
        rows.append({"key": r.key, "title": r.title, "state": r.state, "state_label": st.label if st else r.state,
                     "state_category": st.category if st else None, "state_color": st.color if st else None,
                     "severity": f.get("severity"), "occurrence": f.get("occurrence"), "detection": f.get("detection"),
                     "rpn": f.get("rpn"), "level": f.get("risk_level"), "severity_after": f.get("severity_after"),
                     "occurrence_after": f.get("occurrence_after"), "detection_after": f.get("detection_after"),
                     "rpn_after": f.get("rpn_after"), "residual_level": f.get("residual_level"),
                     "failure_mode": f.get("failure_mode"), "mitigations": mitigations.get(r.id, 0)})
    rows.sort(key=lambda x: -(x["rpn"] or 0))
    active = [x for x in rows if x["state_category"] not in ("obsolete",)]
    summary = {
        "total": len(active),
        "high": sum(1 for x in active if x["level"] == "high"),
        "medium": sum(1 for x in active if x["level"] == "medium"),
        "low": sum(1 for x in active if x["level"] == "low"),
        "unrated": sum(1 for x in active if x["rpn"] is None),
        "high_unmitigated": sum(1 for x in active if x["level"] == "high" and not x["mitigations"]),
        "residual_high": sum(1 for x in active if x["residual_level"] == "high"),
        "accepted": sum(1 for x in active if x["state_category"] == "released"),
    }
    return {"enabled": True, "type": t.key, "type_label": t.label, "scale": SCALE,
            "matrix": matrix("severity", "occurrence"), "residual_matrix": matrix("severity_after", "occurrence_after"),
            "risks": rows, "summary": summary}


@router.get("/risks", summary="Risk matrix (severity × occurrence), register and mitigation coverage")
def risks(project_key: str, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    return risk_overview(db, get_project(db, project_key, user))
