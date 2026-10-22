"""Demo dataset: a generic smart pressure sensor product platform.

Loaded on startup when ``ALMLIGHT_DEMO_DATA=true`` (never in production). Idempotent: does
nothing if the demo project exists. Demo users share the password ``demo1234``.
"""

from __future__ import annotations

import logging

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


def _user(db: Session, username: str, name: str) -> User:
    user = db.execute(select(User).where(User.username == username)).scalar_one_or_none()
    return user or create_user(db, None, username=username, display_name=name, password=DEMO_PASSWORD)


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
    h_meas = new("heading", "1 Measurement", parent=sys_spec)
    h_if = new("heading", "2 Interfaces", parent=sys_spec)
    h_env = new("heading", "3 Environment and safety", parent=sys_spec)
    sysr = {
        "range": new("system_requirement", "Measure process pressure over the configured range", parent=h_meas,
                     description="The transmitter shall measure gauge pressure over the full configured measuring "
                                 "range (0-10 bar or 0-100 bar).",
                     fields={"priority": "must", "kind": "performance"}),
        "accuracy": new("system_requirement", "Accuracy of 0.1 % of span", parent=h_meas,
                        description="The measurement deviation shall not exceed +/- 0.1 % of span at reference "
                                    "conditions.", fields={"priority": "must", "kind": "performance"}),
        "analog": new("system_requirement", "Provide a 4-20 mA output signal", parent=h_if,
                      description="The measured value shall be provided as a 4-20 mA current signal.",
                      fields={"priority": "must", "kind": "interface"}, applicability="OUT_420 or OUT_HART"),
        "hart": new("system_requirement", "Provide HART communication", parent=h_if,
                    description="Configuration and diagnostics shall be available via HART 7.",
                    fields={"priority": "must", "kind": "interface"}, applicability="OUT_HART"),
        "iolink": new("system_requirement", "Provide an IO-Link interface", parent=h_if,
                      description="The transmitter shall act as an IO-Link device (COM2).",
                      fields={"priority": "must", "kind": "interface"}, applicability="OUT_IOLINK"),
        "temp": new("system_requirement", "Operate from -40 to +85 degC", parent=h_env,
                    fields={"priority": "must", "kind": "environmental", "verification_method": "test"}),
        "sil": new("system_requirement", "Support a SIL 2 safety function", parent=h_env,
                   description="Systematic capability SC 2 and diagnostic coverage according to the safety "
                               "manual.", fields={"priority": "must", "kind": "safety", "safety_relevant": True,
                                                  "verification_method": "analysis"}, applicability="SIL2"),
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
            "steps": "1. Apply 0, 25, 50, 75, 100 % of range\n2. Record the output", "expected_result":
            "Output within tolerance at all points"}),
        "accuracy": new("test_case", "Accuracy at reference conditions",
                        fields={"test_level": "system", "method": "manual"}),
        "analog": new("test_case", "Current loop output test", applicability="OUT_420 or OUT_HART",
                      fields={"test_level": "system", "method": "hil", "automation_id": "sensor.output.test_loop"}),
        "hart": new("test_case", "HART communication test", applicability="OUT_HART",
                    fields={"test_level": "integration", "method": "automated"}),
        "temp": new("test_case", "Temperature cycle test", fields={"test_level": "system", "method": "manual"}),
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
    for record, tc in verification.records_of(db, run):
        key = next(k for k, v in tcs.items() if v.id == tc.id)
        verification.set_result(db, project, alex, run, record.id, result=results[key],
                                comment="Drift at -40 degC exceeds limit" if results[key] == "failed" else None)
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
    db.commit()
    log.warning("Demo project %s loaded (users alex/rita/max, password '%s')", DEMO_KEY, DEMO_PASSWORD)
