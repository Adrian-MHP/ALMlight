"""Scheduling on a working-day calendar (Mon–Fri): dependency types with lag, total slack and the forward pass.

Dates are inclusive days: a task from Monday to Friday occupies five working days. Dependencies follow the usual
scheduling-tool semantics (Teamcenter Schedule Manager, MS Project), predecessor P, successor S, lag L in working
days (negative = lead):

====  ===================================  ==========================================================
Type  Meaning                              Rule
====  ===================================  ==========================================================
FS    S starts after P finishes            S.start later than P.finish + L
SS    S starts when P starts               S.start no earlier than P.start + L
FF    S finishes when P finishes           S.finish no earlier than P.finish + L
SF    S finishes when P starts             S.finish no earlier than the working day before P.start + L
====  ===================================  ==========================================================

A milestone is a point in time: as successor of a finish-to-start dependency it may fall on the day P finishes.
"""

from __future__ import annotations

import heapq
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Literal

DepType = Literal["fs", "ss", "ff", "sf"]
DEP_TYPES: dict[str, str] = {"fs": "finish-to-start", "ss": "start-to-start", "ff": "finish-to-finish",
                             "sf": "start-to-finish"}


def is_workday(d: date) -> bool:
    return d.weekday() < 5


def add_workdays(d: date, n: int) -> date:
    """n working days after d (before d for negative n); d itself for 0."""
    step = 1 if n > 0 else -1
    for _ in range(abs(n)):
        d += timedelta(days=step)
        while not is_workday(d):
            d += timedelta(days=step)
    return d


def prev_workday(d: date) -> date:
    return add_workdays(d, -1)


def workday_on_or_after(d: date) -> date:
    while not is_workday(d):
        d += timedelta(days=1)
    return d


def workdays(a: date, b: date) -> int:
    """Working days from a to b: positive if b is later, negative if earlier, 0 on the same day."""
    if a == b:
        return 0
    sign, lo, hi = (1, a, b) if b > a else (-1, b, a)
    n, d = 0, lo
    while d < hi:
        d += timedelta(days=1)
        if is_workday(d):
            n += 1
    return sign * n


def span(start: date, due: date) -> int:
    """Working days covered by an inclusive date range (at least 1)."""
    return max(1, workdays(start, due) + (1 if is_workday(start) else 0))


@dataclass(frozen=True)
class Dep:
    pred: str
    succ: str
    type: DepType = "fs"
    lag: int = 0


@dataclass(frozen=True)
class _Rule:
    s_point: Literal["start", "due"]   # which end of the successor is constrained
    p_point: Literal["start", "due"]   # which end of the predecessor gives the bound
    offset: int                        # working days added to the predecessor's end
    strict: bool                       # successor point must be later than (not just on) the bound


def _rule(dep: Dep, succ_milestone: bool) -> _Rule:
    if dep.type == "ss":
        return _Rule("start", "start", dep.lag, False)
    if dep.type == "ff":
        return _Rule("due", "due", dep.lag, False)
    if dep.type == "sf":
        return _Rule("due", "start", dep.lag - 1, False)
    return _Rule("due", "due", dep.lag, False) if succ_milestone else _Rule("start", "due", dep.lag, True)


def _point(node: dict[str, Any], which: str) -> date:
    return node["_start"] if which == "start" else node["_due"]


def violated(nodes: dict[str, dict[str, Any]], dep: Dep) -> bool:
    s, p = nodes[dep.succ], nodes[dep.pred]
    r = _rule(dep, s["kind"] == "milestone")
    bound = add_workdays(_point(p, r.p_point), r.offset)
    value = _point(s, r.s_point)
    return value <= bound if r.strict else value < bound


def conflict_message(nodes: dict[str, dict[str, Any]], dep: Dep) -> str:
    s, p = nodes[dep.succ], nodes[dep.pred]
    lag = f" (lag {dep.lag:+d} working days)" if dep.lag else ""
    if s["kind"] == "milestone" and dep.type == "fs":
        return f"Milestone {dep.succ} ({s['_due']}) is before {dep.pred} finishes{lag}"
    verb = {"fs": ("starts", "finishes"), "ss": ("starts", "starts"), "ff": ("finishes", "finishes"),
            "sf": ("finishes", "starts")}[dep.type]
    sv = s["_start"] if verb[0] == "starts" else s["_due"]
    pv = p["_start"] if verb[1] == "starts" else p["_due"]
    return f"{dep.succ} {verb[0]} {sv} but {dep.pred} {verb[1]} {pv} ({DEP_TYPES[dep.type]}){lag}"


def slack(nodes: dict[str, dict[str, Any]], deps: list[Dep], deadline: dict[str, date]) -> None:
    """Total slack in working days with fixed dates: how far a node could slip before a successor or its deadline
    moves. Negative slack = a dependency is already violated (or the deadline is missed). Sets ``node["slack"]``."""
    succs: dict[str, list[Dep]] = defaultdict(list)
    for d in deps:
        succs[d.pred].append(d)
    late_finish: dict[str, date] = {}

    def lf(n: str, depth: int = 0) -> date:
        if n in late_finish:
            return late_finish[n]
        node = nodes[n]
        limit = deadline.get(n, node["_due"])
        if depth < 200:
            for d in succs.get(n, []):
                sn = nodes[d.succ]
                r = _rule(d, sn["kind"] == "milestone")
                s_lf = lf(d.succ, depth + 1)
                s_latest = s_lf if r.s_point == "due" else add_workdays(s_lf, -workdays(sn["_start"], sn["_due"]))
                bound_max = prev_workday(s_latest) if r.strict else s_latest
                p_latest = add_workdays(bound_max, -r.offset)
                if r.p_point == "start":
                    p_latest = add_workdays(p_latest, workdays(node["_start"], node["_due"]))
                limit = min(limit, p_latest)
        late_finish[n] = limit
        return limit

    for n, node in nodes.items():
        node["slack"] = workdays(node["_due"], lf(n))


def topological(nodes: dict[str, Any], deps: list[Dep], priority: Callable[[str], Any] | None = None) -> list[str]:
    """Nodes ordered so predecessors come first (ties by ``priority``, else by key); nodes in a cycle are left out."""
    rank = priority or (lambda n: n)
    indeg = {n: 0 for n in nodes}
    succs: dict[str, list[str]] = defaultdict(list)
    for d in deps:
        if d.pred in nodes and d.succ in nodes:
            indeg[d.succ] += 1
            succs[d.pred].append(d.succ)
    ready = [(rank(n), n) for n, k in indeg.items() if k == 0]
    heapq.heapify(ready)
    out: list[str] = []
    while ready:
        _, n = heapq.heappop(ready)
        out.append(n)
        for s in succs[n]:
            indeg[s] -= 1
            if indeg[s] == 0:
                heapq.heappush(ready, (rank(s), s))
    return out


def required_shift(nodes: dict[str, dict[str, Any]], dep: Dep) -> int:
    """Working days the successor must move (positive = later) so the dependency just holds."""
    s, p = nodes[dep.succ], nodes[dep.pred]
    r = _rule(dep, s["kind"] == "milestone")
    bound = add_workdays(_point(p, r.p_point), r.offset)
    needed = workday_on_or_after(bound + timedelta(days=1) if r.strict else bound)
    return workdays(_point(s, r.s_point), needed)


def forward(nodes: dict[str, dict[str, Any]], deps: list[Dep], movable: set[str],
            mode: Literal["push", "asap"] = "push") -> dict[str, tuple[date, date]]:
    """Forward pass: move movable successors so every dependency holds. *push* only moves items later; *asap* also
    pulls dependent items in to the earliest date their predecessors allow. Returns new (start, due) per moved node;
    ``nodes`` is updated in place so later successors see the new dates."""
    by_succ: dict[str, list[Dep]] = defaultdict(list)
    for d in deps:
        if d.pred in nodes and d.succ in nodes:
            by_succ[d.succ].append(d)
    moved: dict[str, tuple[date, date]] = {}
    for n in topological(nodes, deps):
        incoming = by_succ.get(n)
        if not incoming or n not in movable:
            continue
        if mode == "push":
            shift = max([required_shift(nodes, d) for d in incoming if violated(nodes, d)], default=0)
        else:
            shift = max(required_shift(nodes, d) for d in incoming)
        if shift == 0:
            continue
        node = nodes[n]
        node["_start"], node["_due"] = add_workdays(node["_start"], shift), add_workdays(node["_due"], shift)
        moved[n] = (node["_start"], node["_due"])
    return moved


# --- resources ----------------------------------------------------------------------------------------------------


def allocation(start: date, due: date, hours: float | None, per_day: float, today: date) -> dict[date, float]:
    """How a task's remaining work is spread: evenly over its working days from today on; ``hours`` None means
    full-time (the person's hours per day). Work of an overdue task lands on the next working day."""
    first = max(start, today)
    days = []
    d = first
    while d <= due:
        if is_workday(d):
            days.append(d)
        d += timedelta(days=1)
    if not days:
        days = [workday_on_or_after(max(today, first if due >= first else today))]
    each = per_day if hours is None else hours / len(days)
    return {d: each for d in days}


def _shift_for_deps(nodes: dict[str, dict[str, Any]], incoming: list[Dep]) -> int:
    return max([required_shift(nodes, d) for d in incoming if violated(nodes, d)], default=0)


def level(nodes: dict[str, dict[str, Any]], deps: list[Dep], movable: set[str], owner: dict[str, str | None],
          hours: dict[str, float | None], per_day: dict[str, float], today: date,
          horizon: int = 260) -> tuple[dict[str, tuple[date, date]], dict[str, dict[date, float]]]:
    """Resource levelling: delay movable tasks (never earlier) until their owner has room, keeping every dependency.
    Fixed work (started, frozen, outside the scope) is booked first; the rest in dependency order, earlier and
    less flexible tasks first. A task needing more than a full day is placed where its owner has nothing else.
    Returns the moved nodes and the resulting load per person and day."""
    load: dict[str, dict[date, float]] = defaultdict(lambda: defaultdict(float))
    by_succ: dict[str, list[Dep]] = defaultdict(list)
    for d in deps:
        if d.pred in nodes and d.succ in nodes:
            by_succ[d.succ].append(d)

    def book(n: str) -> None:
        u = owner.get(n)
        node = nodes[n]
        if not u or node["kind"] != "task" or hours.get(n) == 0:
            return
        for day, h in allocation(node["_start"], node["_due"], hours.get(n), per_day.get(u, 8.0), today).items():
            load[u][day] += h

    for n in nodes:
        if n not in movable:
            book(n)
    order = topological(nodes, deps, priority=lambda n: (nodes[n]["_start"], nodes[n].get("slack", 0), n))
    moved: dict[str, tuple[date, date]] = {}
    for n in order:
        if n not in movable:
            continue
        node = nodes[n]
        original = (node["_start"], node["_due"])
        base = _shift_for_deps(nodes, by_succ.get(n, []))
        start, due = add_workdays(node["_start"], base), add_workdays(node["_due"], base)
        u = owner.get(n)
        if u and node["kind"] == "task" and hours.get(n) != 0 and due >= today:
            cap = per_day.get(u, 8.0)
            for extra in range(horizon):
                s, d = add_workdays(start, extra), add_workdays(due, extra)
                need = allocation(s, d, hours.get(n), cap, today)
                if all(load[u][day] + h <= cap + 1e-6 or load[u][day] <= 1e-6 for day, h in need.items()):
                    start, due = s, d
                    break
        node["_start"], node["_due"] = start, due
        book(n)
        if (start, due) != original:
            moved[n] = (start, due)
    return moved, load
