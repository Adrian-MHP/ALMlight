"""Demo dataset: a generic smart pressure sensor product platform.

Loaded on startup when ``ALMLIGHT_DEMO_DATA=true`` (never in production). Idempotent: does
nothing if the demo project exists. Demo users share the password ``demo1234``.
"""

from __future__ import annotations

import io
import logging
import struct
import zlib

from sqlalchemy import select
from sqlalchemy.orm import Session

from almlight.modules.baselines import service as baselines
from almlight.modules.identity.models import User
from almlight.modules.identity.service import create_user
from almlight.modules.integrations import service as integrations
from almlight.modules.items import service as items
from almlight.modules.items.models import Item
from almlight.modules.links import service as links
from almlight.modules.projects import service as projects
from almlight.modules.projects.models import Project
from almlight.modules.verification import service as verification
from almlight.modules.workflow import engine

log = logging.getLogger("almlight.seed")
DEMO_KEY = "DEMO"
DEMO_PASSWORD = "demo1234"


def _drawing_png(w: int = 160, h: int = 100) -> bytes:
    """A tiny technical-drawing-like PNG (outline with a bore), generated so the repository holds no binaries."""
    def px(x: int, y: int) -> bytes:
        border = x in (8, w - 9) or y in (8, h - 9)
        bore = abs((x - w // 2) ** 2 + (y - h // 2) ** 2 - 22 ** 2) < 45
        axis = (x == w // 2 or y == h // 2) and (x // 3) % 2 == 0 and (y // 3) % 2 == 0
        return b"\x1f\x2d\x3d" if border or bore else b"\x0e\x6e\x76" if axis else b"\xf7\xf9\xfb"

    raw = b"".join(b"\x00" + b"".join(px(x, y) for x in range(w)) for y in range(h))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def _step_model(name: str, rev: int, note: str) -> bytes:
    return (f"ISO-10303-21;\nHEADER;\nFILE_DESCRIPTION(('{name} rev {rev}: {note}'),'2;1');\n"
            f"FILE_NAME('{name.lower()}.step','2026-10-01',('Demo'),('Demo'),'','','');\n"
            "FILE_SCHEMA(('AP242_MANAGED_MODEL_BASED_3D_ENGINEERING_MIM_LF'));\nENDSEC;\nDATA;\nENDSEC;\n"
            "END-ISO-10303-21;\n").encode()


def _user(db: Session, username: str, name: str) -> User:
    user = db.execute(select(User).where(User.username == username)).scalar_one_or_none()
    return user or create_user(db, None, username=username, display_name=name, password=DEMO_PASSWORD)


def _backdate(db: Session, item: Item, *, created: int, events: dict[str, int]) -> None:
    """Move an item's creation and lifecycle events into the past (demo history only)."""
    from datetime import timedelta

    from almlight.core.db import utcnow
    from almlight.modules.workflow.models import WorkflowEvent

    now = utcnow()
    item.created_at = now - timedelta(days=created)
    for ev in db.execute(select(WorkflowEvent).where(WorkflowEvent.item_id == item.id)).scalars():
        if ev.to_state in events:
            ev.created_at = now - timedelta(days=events[ev.to_state])


def seed_demo(db: Session) -> None:
    if db.execute(select(Project.id).where(Project.key == DEMO_KEY)).scalar():
        return
    admin = db.execute(select(User).where(User.is_admin.is_(True)).order_by(User.created_at)).scalars().first()
    alex = _user(db, "alex", "Alex Engineer")
    rita = _user(db, "rita", "Rita Reviewer")
    max_ = _user(db, "max", "Max Manager")
    project = projects.create_project(db, admin, key=DEMO_KEY, name="Smart Sensor Platform (demo)",
                                      template_key="systems_engineering",
                                      description="Demo product family: modular pressure transmitters with "
                                                  "variants, verification and closed-loop change.")
    for user, role in ((alex, "contributor"), (rita, "reviewer"), (max_, "manager")):
        projects.set_member(db, admin, project, user, role)

    def new(type_key: str, title: str, *, parent: Item | None = None, by: User = alex, **kw) -> Item:
        return items.create_item(db, project, by, type_key=type_key, title=title, parent=parent, **kw)

    def link(type_key: str, source: Item, target: Item, **kw) -> None:
        links.create_link(db, project, alex, type_key=type_key, source=source, target=target, **kw)

    # --- feature model -----------------------------------------------------------------------
    fam = new("feature", "Pressure transmitter family", fields={"code": "SENSOR", "feature_kind": "mandatory"})
    out = new("feature", "Output signal", parent=fam,
              fields={"code": "OUTPUT", "feature_kind": "mandatory", "group": "alternative"})
    new("feature", "4-20 mA analog", parent=out, fields={"code": "OUT_420"})
    new("feature", "4-20 mA with HART", parent=out, fields={"code": "OUT_HART"})
    fiol = new("feature", "IO-Link", parent=out, fields={"code": "OUT_IOLINK"})
    rng = new("feature", "Measuring range", parent=fam,
              fields={"code": "RANGE", "feature_kind": "mandatory", "group": "alternative"})
    new("feature", "0-10 bar", parent=rng, fields={"code": "R10"})
    new("feature", "0-100 bar", parent=rng, fields={"code": "R100"})
    sil = new("feature", "Functional safety SIL 2", parent=fam, fields={"code": "SIL2"})
    atex = new("feature", "Explosion protection (Ex)", parent=fam, fields={"code": "EX"})
    link("excludes", sil, fiol)
    link("excludes", atex, fiol)

    # --- stakeholder requirements ------------------------------------------------------------------
    stk_spec = new("specification", "Stakeholder Requirements Specification",
                   fields={"doc_kind": "stakeholder_specification"})
    stk = {
        "monitor": new("stakeholder_requirement", "Monitor process pressure reliably", parent=stk_spec,
                       description="Operators need a continuous, trustworthy pressure value to run the process "
                                   "safely and efficiently.", fields={"priority": "must", "source": "Market study"}),
        "integrate": new("stakeholder_requirement", "Integrate into existing control systems", parent=stk_spec,
                         description="The measured value must be available in common plant and factory control "
                                     "systems without adapters.", fields={"priority": "must"}),
        "safety": new("stakeholder_requirement", "Support safety-instrumented functions", parent=stk_spec,
                      description="Process industry customers use the transmitter in safety loops.",
                      fields={"priority": "should", "source": "Key account feedback"}, applicability="SIL2"),
        "cost": new("stakeholder_requirement", "Low cost of ownership", parent=stk_spec,
                    description="Long calibration intervals and simple replacement.", fields={"priority": "should"}),
    }

    # --- system requirements in a live document --------------------------------------------------
    sys_spec = new("specification", "System Requirements Specification", fields={"doc_kind": "system_specification"})
    h_meas = new("heading", "Measurement", parent=sys_spec)
    h_if = new("heading", "Interfaces", parent=sys_spec)
    h_env = new("heading", "Environment and safety", parent=sys_spec)
    sysr = {
        "range": new("system_requirement", "Measure process pressure over the configured range", parent=h_meas,
                     description="The transmitter shall measure gauge pressure over the full configured measuring "
                                 "range (0-10 bar or 0-100 bar).",
                     fields={"priority": "must", "kind": "performance", "estimate": 8}),
        "accuracy": new("system_requirement", "Accuracy of 0.1 % of span", parent=h_meas,
                        description="The measurement deviation shall not exceed +/- 0.1 % of span at reference "
                                    "conditions.", fields={"priority": "must", "kind": "performance", "estimate": 5}),
        "analog": new("system_requirement", "Provide a 4-20 mA output signal", parent=h_if,
                      description="The measured value shall be provided as a 4-20 mA current signal.",
                      fields={"priority": "must", "kind": "interface", "estimate": 3},
                      applicability="OUT_420 or OUT_HART"),
        "hart": new("system_requirement", "Provide HART communication", parent=h_if,
                    description="Configuration and diagnostics shall be available via HART 7.",
                    fields={"priority": "must", "kind": "interface", "estimate": 8}, applicability="OUT_HART"),
        "iolink": new("system_requirement", "Provide an IO-Link interface", parent=h_if,
                      description="The transmitter shall act as an IO-Link device (COM2).",
                      fields={"priority": "must", "kind": "interface", "estimate": 13}, applicability="OUT_IOLINK"),
        "temp": new("system_requirement", "Operate from -40 to +85 degC", parent=h_env,
                    fields={"priority": "must", "kind": "environmental", "verification_method": "test",
                            "estimate": 5}),
        "sil": new("system_requirement", "Support a SIL 2 safety function", parent=h_env,
                   description="Systematic capability SC 2 and diagnostic coverage according to the safety "
                               "manual.", fields={"priority": "must", "kind": "safety", "safety_relevant": True,
                                                  "verification_method": "analysis", "estimate": 13},
                   applicability="SIL2"),
    }
    for key, target in (("range", "monitor"), ("accuracy", "monitor"), ("analog", "integrate"),
                        ("hart", "integrate"), ("iolink", "integrate"), ("temp", "monitor"), ("sil", "safety")):
        link("derives_from", sysr[key], stk[target])

    # --- functions and system structure (RFLP) -----------------------------------------------------
    fn_acq = new("function", "Acquire process pressure")
    fn_proc = new("function", "Process and compensate the signal")
    fn_comm = new("function", "Communicate the measured value")
    product = new("system_element", "Smart pressure transmitter",
                  fields={"level": "product", "perspective": "physical", "discipline": "mechatronic"})
    sensor = new("system_element", "Sensor unit", parent=product,
                 fields={"level": "subsystem", "discipline": "mechatronic", "reuse_strategy": "reused"})
    proc = new("system_element", "Signal processing", parent=product,
               fields={"level": "subsystem", "discipline": "mechatronic", "reuse_strategy": "modified"})
    comm = new("system_element", "Communication unit", parent=product,
               fields={"level": "subsystem", "discipline": "mechatronic", "reuse_strategy": "new"})
    cell = new("system_element", "Measuring cell", parent=sensor,
               fields={"level": "module", "perspective": "physical", "discipline": "mechanical",
                       "reuse_strategy": "reused", "part_number": "MC-1001"})
    board = new("system_element", "Electronics board", parent=proc,
                fields={"level": "module", "perspective": "physical", "discipline": "hardware",
                        "reuse_strategy": "modified", "part_number": "EB-2040"})
    fw = new("system_element", "Firmware", parent=proc,
             fields={"level": "module", "discipline": "software", "reuse_strategy": "modified"})
    hart_mod = new("system_element", "HART modem", parent=comm, applicability="OUT_HART",
                   fields={"level": "module", "discipline": "hardware", "reuse_strategy": "purchased"})
    iol_mod = new("system_element", "IO-Link transceiver", parent=comm, applicability="OUT_IOLINK",
                  fields={"level": "module", "discipline": "hardware", "reuse_strategy": "purchased"})
    housing = new("system_element", "Housing", parent=product,
                  fields={"level": "component", "discipline": "mechanical", "reuse_strategy": "standard",
                          "part_number": "HS-0007"})
    for el, fn in ((sensor, fn_acq), (proc, fn_proc), (comm, fn_comm)):
        link("realizes", el, fn)
    mrq_cell = new("element_requirement", "Measuring cell overload resistance 2x range",
                   fields={"discipline": "mechanical", "priority": "must"})
    mrq_comp = new("element_requirement", "Compensate temperature drift in firmware",
                   fields={"discipline": "software", "priority": "must"})
    link("derives_from", mrq_cell, sysr["range"])
    link("derives_from", mrq_comp, sysr["accuracy"])
    link("derives_from", mrq_comp, sysr["temp"])
    for el, req in ((sensor, sysr["range"]), (cell, mrq_cell), (proc, sysr["accuracy"]), (fw, mrq_comp),
                    (comm, sysr["analog"]), (hart_mod, sysr["hart"]), (iol_mod, sysr["iolink"]),
                    (housing, sysr["temp"]), (board, sysr["sil"])):
        link("satisfies", el, req)
    iface = new("interface", "Cell-to-electronics signal interface",
                fields={"interface_kind": "electrical", "standardized": True})
    link("connects", iface, cell)
    link("connects", iface, board)
    datasheet = new("document", "Measuring cell datasheet", fields={"doc_kind": "datasheet",
                                                                   "external_ref": "PDM-DOC-88231"})
    link("documented_by", cell, datasheet)
    integrations.upsert_ref(db, project, mrq_comp, system="github", kind="commit", external_id="9f3c2ab",
                            url="https://git.example.com/sensor/firmware/commit/9f3c2ab",
                            title=f"Add polynomial temperature compensation ({mrq_comp.key})", status="pushed",
                            data={"repository": "sensor/firmware"})

    # --- verification --------------------------------------------------------------------------------
    tcs = {
        "range": new("test_case", "Full-scale range test", fields={
            "test_level": "system", "method": "automated", "automation_id": "sensor.range.test_full_scale",
            "test_steps": [
                {"step": "Mount the transmitter on the pressure calibrator", "expected": "Zero reading 4.00 mA"},
                {"step": "Apply 0, 25, 50, 75 and 100 % of the range", "expected": "Output linear, within 0.1 %"},
                {"step": "Release the pressure", "expected": "Output returns to 4.00 mA"}]}),
        "accuracy": new("test_case", "Accuracy at reference conditions",
                        fields={"test_level": "system", "method": "manual", "test_steps": [
                            {"step": "Stabilise at 23 degC for 2 h", "expected": "Temperature within 23 +/- 1 degC"},
                            {"step": "Apply 50 % of range five times", "expected": "Deviation <= 0.1 % of span"}]}),
        "analog": new("test_case", "Current loop output test", applicability="OUT_420 or OUT_HART",
                      fields={"test_level": "system", "method": "hil", "automation_id": "sensor.output.test_loop"}),
        "hart": new("test_case", "HART communication test", applicability="OUT_HART",
                    fields={"test_level": "integration", "method": "automated"}),
        "temp": new("test_case", "Temperature cycle test", fields={"test_level": "system", "method": "manual",
                    "test_steps": [{"step": "Cycle -40 to +85 degC, 10 cycles", "expected": "No damage"},
                                   {"step": "Measure at +85 degC", "expected": "Deviation <= 0.25 % of span"},
                                   {"step": "Measure at -40 degC", "expected": "Deviation <= 0.25 % of span"}]}),
        "accept": new("test_case", "Customer acceptance: pressure monitoring", fields={"test_level": "validation"}),
    }
    for key in ("range", "accuracy", "analog", "hart", "temp"):
        link("verifies", tcs[key], sysr[key])
    link("verifies", tcs["accept"], stk["monitor"])

    # --- lifecycle: approve stakeholder needs and the core system requirements ----------------------
    def approve(item: Item, transition: str = "approve", submit: str = "submit") -> None:
        engine.execute_transition(db, project, alex, item, submit)
        req = engine.pending_request(db, item)
        if req is None:
            engine.execute_transition(db, project, alex, item, transition)
            req = engine.pending_request(db, item)
        engine.vote(db, project, rita, req, decision="approve", password=DEMO_PASSWORD)

    for item in (*stk.values(), sysr["range"], sysr["accuracy"], sysr["analog"], sysr["temp"]):
        approve(item)
    for item in tcs.values():
        engine.execute_transition(db, project, rita, item, "mark_ready")
    approve(cell, transition="release", submit="freeze")

    run = new("test_run", "Lab verification run 1", fields={"environment": "Lab A", "build": "FW 1.3.0",
                                                            "variant": "VAR-1"})
    verification.add_test_cases(db, project, alex, run, [tcs["range"], tcs["accuracy"], tcs["analog"], tcs["temp"]])
    engine.execute_transition(db, project, alex, run, "start")
    results = {"range": "passed", "accuracy": "passed", "analog": "passed", "temp": "failed"}
    minutes = {"range": 20, "accuracy": 45, "analog": 15, "temp": 240}
    step_results = {
        "range": [{"result": "passed", "actual": "4.00 mA"}, {"result": "passed", "actual": "max. 0.04 %"},
                  {"result": "passed", "actual": "4.00 mA"}],
        "temp": [{"result": "passed"}, {"result": "passed", "actual": "0.18 %"},
                 {"result": "failed", "actual": "0.41 % at -40 degC"}],
    }
    failed_record = None
    for record, tc in verification.records_of(db, run):
        key = next(k for k, v in tcs.items() if v.id == tc.id)
        verification.set_result(db, project, alex, run, record.id, result=results[key],
                                duration_ms=minutes[key] * 60_000, step_results=step_results.get(key),
                                comment="Drift at -40 degC exceeds limit" if results[key] == "failed" else None)
        if results[key] == "failed":
            failed_record = record
    if failed_record is not None:
        verification.raise_defect(db, project, alex, run, failed_record.id, step=3,
                                  title="Temperature drift at -40 degC exceeds 0.25 %")
    engine.execute_transition(db, project, alex, run, "complete")

    # --- variants ------------------------------------------------------------------------------------
    for title, sel, market in (
        ("Standard analog, 0-10 bar", ["SENSOR", "OUTPUT", "OUT_420", "RANGE", "R10"], "General industry"),
        ("Process HART SIL 2, 0-100 bar", ["SENSOR", "OUTPUT", "OUT_HART", "RANGE", "R100", "SIL2"],
         "Process industry"),
        ("Factory IO-Link, 0-10 bar", ["SENSOR", "OUTPUT", "OUT_IOLINK", "RANGE", "R10"], "Factory automation"),
    ):
        new("variant", title, fields={"selection": sel, "market": market})

    baselines.create_baseline(db, project, rita, name="Concept baseline",
                              description="Requirements and architecture after concept review")

    # --- an open change: extend the range, which makes downstream links suspect ---------------------
    cr = new("change_request", "Extend measuring range to 160 bar", by=max_,
             fields={"reason": "customer_request", "priority": "high",
                     "impact_analysis": "Affects range requirement, measuring cell and range test."})
    link("affects", cr, sysr["range"])
    link("affects", cr, cell)
    engine.execute_transition(db, project, max_, cr, "analyse")
    items.update_item(db, project, alex, mrq_cell,
                      items.ContentChange(description="Overload resistance shall be at least twice the upper "
                                                      "range value, including the 160 bar option under review."),
                      change_note="Prepared for range extension")

    # --- platform reuse: a second product shares the measuring cell and the housing ---------------------
    switch = new("system_element", "Compact pressure switch",
                 fields={"level": "product", "perspective": "physical", "discipline": "mechatronic"})
    link("contains", switch, cell, attributes={"quantity": 1})
    link("contains", switch, housing, attributes={"quantity": 1})
    new("system_element", "Switch electronics", parent=switch,
        fields={"level": "module", "discipline": "hardware", "reuse_strategy": "new"})

    # --- a completed closed-loop change (dated in the past, so lead-time KPIs have history) -------------
    cr2 = new("change_request", "Qualify a second supplier for the measuring cell", by=max_,
              fields={"reason": "cost_reduction", "priority": "medium",
                      "impact_analysis": "Measuring cell only; interface unchanged; re-test range and accuracy."})
    link("affects", cr2, cell)
    engine.execute_transition(db, project, max_, cr2, "analyse")
    engine.execute_transition(db, project, alex, cr2, "approve")
    engine.vote(db, project, max_, engine.pending_request(db, cr2), decision="approve", password=DEMO_PASSWORD)
    co1 = new("change_order", "Introduce measuring cell from supplier B", by=max_)
    link("implements", co1, cr2)
    link("affects", co1, cell, attributes={"action": "revise"})
    engine.execute_transition(db, project, max_, co1, "start_work")
    items.revise_item(db, project, alex, cell, change_order=co1, change_note="Second source")
    items.update_item(db, project, alex, cell, items.ContentChange(fields={"supplier": "Supplier B",
                                                                           "part_number": "MC-1001-B"}),
                      change_note="Supplier B part")
    engine.execute_transition(db, project, alex, co1, "submit")
    engine.execute_transition(db, project, alex, co1, "release")
    engine.vote(db, project, max_, engine.pending_request(db, co1), decision="approve", password=DEMO_PASSWORD)
    _backdate(db, cr2, created=45, events={"in_analysis": 41, "approved": 33})
    _backdate(db, co1, created=31, events={"in_work": 29, "in_approval": 16, "released": 14})
    _backdate(db, cr, created=9, events={"in_analysis": 8})

    # --- document review: baseline, later changes, comments and a release collection ---------------------
    review = baselines.create_baseline(db, project, rita, name="System spec — review 1", scope_root=sys_spec,
                                       description="Frozen for the first design review")
    items.update_item(db, project, alex, sysr["iolink"], items.ContentChange(
        description="The transmitter shall act as an IO-Link device (COM3, IO-Link 1.1.3)."),
        change_note="Review finding: COM3")
    new("system_requirement", "Provide NAMUR NE 107 diagnostics", parent=h_if,
        description="Device status shall be signalled according to NAMUR NE 107 (failure, check, out of spec).",
        fields={"priority": "should", "kind": "interface"})
    thread = items.add_comment(db, project, rita, sysr["accuracy"],
                               "Is 0.1 % achievable over the full temperature range?", document=sys_spec)
    items.add_comment(db, project, alex, sysr["accuracy"],
                      f"Yes, with the firmware compensation ({mrq_comp.key}); see test {tcs['temp'].key}.",
                      parent_id=thread.id)
    from almlight.modules.doc_collections import service as collections

    release = collections.create(db, project, max_, "Release 1.0 (pilot customers)",
                                 "Specifications delivered with the first pilot release")
    collections.add_document(db, project, max_, release, stk_spec, None)
    collections.add_document(db, project, max_, release, sys_spec, review)

    # --- product structure as a BOM: find numbers, quantities, effectivity -------------------------------
    from datetime import date, timedelta

    def bom(parent: Item, child: Item, find: str, qty: float = 1, unit: str = "pcs", **extra: str) -> None:
        link_row = next(lk for lk, it in links.children(db, parent, project.model.structural_link_types())
                        if it.id == child.id)
        links.update_link(db, project, alex, link_row, attributes={"quantity": qty, "unit": unit, "find_number": find,
                                                                   **extra})

    for parent, child, find in ((product, sensor, "10"), (product, proc, "20"), (product, comm, "30"),
                                (product, housing, "40"), (sensor, cell, "11"), (proc, board, "21"), (proc, fw, "22"),
                                (comm, hart_mod, "31"), (comm, iol_mod, "32")):
        bom(parent, child, find)
    seal = new("system_element", "O-ring 12x2 FKM", parent=sensor,
               fields={"level": "component", "discipline": "mechanical", "reuse_strategy": "purchased",
                       "part_number": "OR-1220", "supplier": "Seal Co."})
    bom(sensor, seal, "12", 2)
    gland_old = new("system_element", "Cable gland M16", parent=product,
                    fields={"level": "component", "discipline": "mechanical", "reuse_strategy": "purchased",
                            "part_number": "CG-M16"})
    gland_new = new("system_element", "Cable gland M20 (EMC)", parent=product,
                    fields={"level": "component", "discipline": "mechanical", "reuse_strategy": "purchased",
                            "part_number": "CG-M20E"})
    year = date.today().year
    bom(product, gland_old, "50", effective_to=f"{year}-12-31")
    bom(product, gland_new, "50", effective_from=f"{year + 1}-01-01")

    # --- risk management (FMEA) -----------------------------------------------------------------------
    def risk(title: str, mode: str, s: int, o: int, d: int, *, after: tuple[int, int, int] | None = None,
             mitigated_by: tuple[Item, ...] = (), applies_to: tuple[Item, ...] = (), mitigate: bool = False) -> Item:
        fields = {"failure_mode": mode, "severity": s, "occurrence": o, "detection": d}
        if after:
            fields.update(severity_after=after[0], occurrence_after=after[1], detection_after=after[2])
        r = new("risk", title, fields=fields)
        for m in mitigated_by:
            link("mitigated_by", r, m)
        for el in applies_to:
            link("risk_for", r, el)
        if mitigate:
            engine.execute_transition(db, project, alex, r, "mitigate")
        return r

    risk("Overpressure destroys the measuring cell", "Burst of the diaphragm above 2x range", 9, 5, 5,
         after=(9, 2, 3), mitigated_by=(mrq_cell, tcs["range"]), applies_to=(cell,), mitigate=True)
    risk("Temperature drift exceeds the accuracy", "Uncompensated drift at low temperature", 7, 6, 4,
         after=(7, 3, 3), mitigated_by=(mrq_comp, tcs["temp"]), applies_to=(fw, board), mitigate=True)
    risk("Loss of HART communication", "Modem fails after ESD event", 5, 3, 4, applies_to=(hart_mod,))
    risk("Undetected sensor failure in a SIL loop", "Frozen output value is not diagnosed", 10, 3, 7,
         applies_to=(board,))

    # --- release planning ----------------------------------------------------------------------------
    today = date.today()
    r10 = new("release", "Release 1.0 — pilot customers", by=max_,
              fields={"start_date": (today.replace(day=1)).isoformat(), "due_date": f"{today.year}-12-15",
                      "goal": "Analog and IO-Link variants for pilot customers", "capacity": 50})
    engine.execute_transition(db, project, max_, r10, "start")
    r11 = new("release", "Release 1.1 — HART and SIL 2", by=max_,
              fields={"start_date": f"{today.year + 1}-01-07", "due_date": f"{today.year + 1}-04-30",
                      "goal": "Process variant with HART and SIL 2 certification"})
    monday = today - timedelta(days=today.weekday())

    def day(n: int) -> str:
        return (monday + timedelta(days=n)).isoformat()

    sprint_a = new("release", "Sprint 1 — core measurement", by=max_,
                   fields={"kind": "iteration", "start_date": day(-14), "due_date": day(11), "capacity": 20,
                           "goal": "Range, accuracy and verification run"})
    sprint_b = new("release", "Sprint 2 — interfaces and environment", by=max_,
                   fields={"kind": "iteration", "start_date": day(14), "due_date": day(39), "capacity": 20})
    for sp in (sprint_a, sprint_b):
        link("part_of", sp, r10)
    engine.execute_transition(db, project, max_, sprint_a, "start")
    for it in (sysr["range"], sysr["accuracy"], run):
        link("planned_in", it, sprint_a)
    for it in (sysr["analog"], sysr["temp"]):
        link("planned_in", it, sprint_b)
    link("planned_in", sysr["iolink"], r10)
    for it in (sysr["hart"], sysr["sil"], cr):
        link("planned_in", it, r11)
    # approvals spread over the sprint, so the burn-up shows the real progression
    for item, ago in ((sysr["range"], 12), (sysr["accuracy"], 8), (sysr["analog"], 4), (sysr["temp"], 2)):
        _backdate(db, item, created=30, events={"in_review": ago + 1, "approved": ago})

    # --- schedule: tasks with dependencies (finish-to-start, start-to-start with lag) and milestones ----
    def task(title: str, start: int, finish: int, plan: Item, progress: int = 0, state: str | None = None, *,
             owner: User = alex, hours: float | None = None) -> Item:
        fields: dict = {"start_date": day(start), "due_date": day(finish), "progress": progress}
        if hours:
            fields["estimate"] = hours
        t = new("task", title, by=max_, fields=fields, owner_id=owner.id)
        link("planned_in", t, plan)
        if state in ("in_progress", "done"):
            engine.execute_transition(db, project, max_, t, "start")
        if state == "done":
            engine.execute_transition(db, project, max_, t, "finish")
        return t

    proto = task("Build B-samples", -21, -10, sprint_a, 100, "done", hours=60)
    emc = task("EMC pre-compliance test", -7, 4, sprint_a, 60, "in_progress", hours=64)
    qual = task("Temperature qualification", 7, 18, sprint_b, owner=rita, hours=48)
    review_dr2 = task("Design review DR2", 21, 23, sprint_b, owner=max_, hours=12)
    freeze = new("release", "Design freeze", by=max_, fields={"kind": "milestone", "due_date": day(23)})
    pilot = task("Pilot production preparation", 24, 46, r10, hours=120)
    sop = new("release", "Start of pilot deliveries", by=max_, fields={"kind": "milestone", "due_date": day(46)})
    for ms in (freeze, sop):
        link("part_of", ms, r10)
    for succ, pred in ((emc, proto), (qual, emc), (review_dr2, qual), (freeze, review_dr2), (pilot, freeze),
                       (sop, pilot)):
        link("depends_on", succ, pred)
    # the report is written alongside the qualification: start three working days after it, finish with it
    report = task("Qualification report", 10, 21, sprint_b, owner=rita, hours=24)
    link("depends_on", report, qual, attributes={"dependency_type": "ss", "lag": 3})
    template = task("Prepare EMC test report template", -7, -3, sprint_a, 100, "done", hours=8)
    # alex is double-booked this week (EMC test and the FMEA update): the resource view shows the overload and
    # levelling moves the FMEA update behind the EMC test
    task("Update FMEA after EMC findings", 0, 4, sprint_a, hours=32)
    projects.set_member(db, admin, project, rita, "reviewer", hours_per_day=6)  # part-time in this project

    # --- time recording: hours worked on the tasks so far ----------------------------------------------
    from almlight.modules.worklog.models import WorkRecord

    def worked(who: User, item: Item, offsets: range, hours: float, comment: str | None = None) -> None:
        for n in offsets:
            d = monday + timedelta(days=n)
            if d.weekday() < 5 and d <= today:
                db.add(WorkRecord(project_id=project.id, item_id=item.id, user_id=who.id, day=d, hours=hours,
                                  comment=comment))

    worked(alex, proto, range(-21, -9), 6, "Sample build")
    worked(alex, template, range(-7, -2), 2)
    worked(alex, emc, range(-7, 1), 5, "Pre-compliance measurements")
    db.flush()
    baselines.create_baseline(db, project, max_, name="Schedule baseline",
                              description="Plan agreed at the sprint 1 kick-off")
    # the qualification slips by three days: the timeline shows the baseline and the conflicts with DR2 and
    # the report; auto-scheduling moves them
    items.update_item(db, project, max_, qual, items.ContentChange(fields={"start_date": day(10),
                                                                          "due_date": day(21)}),
                      change_note="Climate chamber booked three days later")

    # --- files: a drawing and a CAD model with two revisions, checked out by alex ---------------------
    from almlight.modules.files import service as files

    items.add_attachment(db, project, alex, housing, filename="housing-drawing.png", content_type="image/png",
                         stream=io.BytesIO(_drawing_png()))
    step = items.add_attachment(db, project, alex, housing, filename="housing.step", content_type="application/step",
                                stream=io.BytesIO(_step_model("Housing", 1, "2.0 mm wall")))
    items.revise_attachment(db, project, alex, housing, step["id"], filename="housing.step",
                            content_type="application/step",
                            stream=io.BytesIO(_step_model("Housing", 2, "2.5 mm wall")),
                            comment="Wall thickness 2.5 mm for IP67")
    files.checkout(db, project, alex, housing, step["id"], "Adding the M20 thread for the EMC cable gland")

    # --- collaboration: rita watches the system specification, alex mentions her ---------------------
    from almlight.modules.notifications import service as notifications
    from almlight.modules.queries.models import SavedQuery

    notifications.watch(db, rita, project, sys_spec, True)
    nm107 = db.execute(select(Item).where(Item.project_id == project.id,
                                          Item.title == "Provide NAMUR NE 107 diagnostics")).scalar_one()
    items.add_comment(db, project, alex, nm107, "@rita could you check the status mapping against NE 107 table 1?",
                      document=sys_spec)
    link("planned_in", nm107, sprint_b)
    from almlight.modules.boards.models import Board
    from almlight.modules.boards.router import BoardConfig, validate_config

    for name, cfg in (
        ("Requirements by status", BoardConfig(types=["system_requirement"], columns_by="state",
                                               swimlanes_by="field.priority", card_fields=["estimate", "kind"],
                                               wip={"in_review": 3})),
        ("Sprint board", BoardConfig(types=["system_requirement", "task", "test_run", "change_request",
                                            "problem_report"],
                                     conditions=[{"field": "release", "op": "in",
                                                  "values": [sprint_a.key, sprint_b.key]}],
                                     columns_by="release", swimlanes_by="type", card_fields=["estimate"])),
    ):
        db.add(Board(project_id=project.id, owner_id=max_.id, name=name, shared=True,
                     config=validate_config(project, cfg)))
    db.add(SavedQuery(project_id=project.id, owner_id=rita.id, name="Unverified system requirements", shared=True,
                      query={"type": ["system_requirement"], "link_type": "verifies", "link_dir": "in",
                             "link_exists": False}))

    # --- shared reports ---------------------------------------------------------------------------------
    from almlight.modules.reports import service as reports
    from almlight.modules.reports.schemas import ReportIn

    reports.create_report(db, project, max_, ReportIn(title="Project KPI overview", template="kpi_overview",
                                                      description="Platform and process KPIs for the steering board"))
    reports.create_report(db, project, rita, ReportIn(title="Requirements status", template="requirements_status",
                                                      description="Lifecycle, coverage and progress"))
    db.commit()
    log.warning("Demo project %s loaded (users alex/rita/max, password '%s')", DEMO_KEY, DEMO_PASSWORD)
