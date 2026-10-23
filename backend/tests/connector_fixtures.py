"""Sample files of external tools for tests and demos: an Enterprise Architect model (.qea — EA's SQLite schema for
the tables the connector reads), an EA-style XMI 2.1 export, and medini analyze HARA/FMEA tables.

Regenerate the demo samples:  python tests/connector_fixtures.py <output dir>
"""

from __future__ import annotations

import csv
import io
import os
import sqlite3
import sys
import tempfile

EA_SCHEMA = """
CREATE TABLE t_package (Package_ID INTEGER PRIMARY KEY AUTOINCREMENT, Name TEXT, Parent_ID INTEGER DEFAULT 0,
  CreatedDate TEXT, ModifiedDate TEXT, Notes TEXT, ea_guid TEXT, XMLPath TEXT, IsControlled INTEGER DEFAULT 0,
  Version TEXT, Protected INTEGER DEFAULT 0, TPos INTEGER DEFAULT 0, PackageFlags TEXT);
CREATE TABLE t_object (Object_ID INTEGER PRIMARY KEY AUTOINCREMENT, Object_Type TEXT, Diagram_ID INTEGER DEFAULT 0,
  Name TEXT, Alias TEXT, Author TEXT, Version TEXT DEFAULT '1.0', Note TEXT, Package_ID INTEGER DEFAULT 0,
  Stereotype TEXT, NType INTEGER DEFAULT 0, Complexity TEXT DEFAULT '1', Effort INTEGER DEFAULT 0, Style TEXT,
  Backcolor INTEGER DEFAULT -1, BorderStyle INTEGER DEFAULT 0, BorderWidth INTEGER DEFAULT -1,
  Fontcolor INTEGER DEFAULT -1, Bordercolor INTEGER DEFAULT -1, CreatedDate TEXT, ModifiedDate TEXT, Status TEXT,
  Abstract TEXT DEFAULT '0', Tagged INTEGER DEFAULT 0, PDATA1 TEXT, PDATA2 TEXT, PDATA3 TEXT, PDATA4 TEXT,
  PDATA5 TEXT, Concurrency TEXT, Visibility TEXT, Persistence TEXT, Cardinality TEXT, GenType TEXT, GenFile TEXT,
  Header1 TEXT, Header2 TEXT, Phase TEXT DEFAULT '1.0', Scope TEXT DEFAULT 'Public', GenOption TEXT, GenLinks TEXT,
  Classifier INTEGER DEFAULT 0, ea_guid TEXT, ParentID INTEGER DEFAULT 0, RunState TEXT, Classifier_guid TEXT,
  TPos INTEGER DEFAULT 0, IsRoot INTEGER DEFAULT 0, IsLeaf INTEGER DEFAULT 0, IsSpec INTEGER DEFAULT 0,
  IsActive INTEGER DEFAULT 0, StateFlags TEXT, PackageFlags TEXT, Multiplicity TEXT, StyleEx TEXT,
  ActionFlags TEXT, EventFlags TEXT);
CREATE TABLE t_objectproperties (PropertyID INTEGER PRIMARY KEY AUTOINCREMENT, Object_ID INTEGER, Property TEXT,
  Value TEXT, Notes TEXT, ea_guid TEXT);
CREATE TABLE t_connector (Connector_ID INTEGER PRIMARY KEY AUTOINCREMENT, Name TEXT, Direction TEXT, Notes TEXT,
  Connector_Type TEXT, SubType TEXT, SourceCard TEXT, SourceAccess TEXT DEFAULT 'Public', DestCard TEXT,
  DestAccess TEXT DEFAULT 'Public', SourceRole TEXT, DestRole TEXT, Start_Object_ID INTEGER, End_Object_ID INTEGER,
  Stereotype TEXT, SourceIsAggregate INTEGER DEFAULT 0, DestIsAggregate INTEGER DEFAULT 0, PtStartX INTEGER DEFAULT 0,
  PtStartY INTEGER DEFAULT 0, PtEndX INTEGER DEFAULT 0, PtEndY INTEGER DEFAULT 0, SeqNo INTEGER DEFAULT 0,
  HeadStyle INTEGER DEFAULT 0, LineStyle INTEGER DEFAULT 0, RouteStyle INTEGER DEFAULT 0, IsBold INTEGER DEFAULT 0,
  LineColor INTEGER DEFAULT -1, VirtualInheritance TEXT, LinkAccess TEXT, PDATA1 TEXT, PDATA2 TEXT, PDATA3 TEXT,
  PDATA4 TEXT, PDATA5 TEXT, DiagramID INTEGER DEFAULT 0, ea_guid TEXT, SourceConstraint TEXT, DestConstraint TEXT,
  SourceIsNavigable INTEGER DEFAULT 0, DestIsNavigable INTEGER DEFAULT 1, IsRoot INTEGER DEFAULT 0,
  IsLeaf INTEGER DEFAULT 0, IsSpec INTEGER DEFAULT 0, SourceChangeable TEXT, DestChangeable TEXT, SourceTS TEXT,
  DestTS TEXT, StateFlags TEXT, ActionFlags TEXT, IsSignal INTEGER DEFAULT 0, IsStimulus INTEGER DEFAULT 0,
  DispatchAction TEXT, Target2 INTEGER DEFAULT 0, StyleEx TEXT, SourceStereotype TEXT, DestStereotype TEXT,
  SourceStyle TEXT, DestStyle TEXT, EventFlags TEXT);
CREATE TABLE t_xref (XrefID TEXT, Name TEXT, Type TEXT, Visibility TEXT, Namespace TEXT, Requirement TEXT,
  "Constraint" TEXT, Behavior TEXT, Partition TEXT, Description TEXT, Client TEXT, Supplier TEXT, Link TEXT);
"""

G = {  # stable EA GUIDs of the sample model
    "pkg_model": "{1A2B3C4D-0000-4000-8000-000000000001}", "pkg_req": "{1A2B3C4D-0000-4000-8000-000000000002}",
    "pkg_stk": "{1A2B3C4D-0000-4000-8000-000000000003}", "pkg_sys": "{1A2B3C4D-0000-4000-8000-000000000004}",
    "pkg_arch": "{1A2B3C4D-0000-4000-8000-000000000005}", "pkg_ver": "{1A2B3C4D-0000-4000-8000-000000000006}",
    "stk1": "{5E6F7A8B-0000-4000-8000-000000000011}", "sys1": "{5E6F7A8B-0000-4000-8000-000000000012}",
    "sys2": "{5E6F7A8B-0000-4000-8000-000000000013}", "block": "{5E6F7A8B-0000-4000-8000-000000000014}",
    "cell": "{5E6F7A8B-0000-4000-8000-000000000015}", "act": "{5E6F7A8B-0000-4000-8000-000000000016}",
    "itf": "{5E6F7A8B-0000-4000-8000-000000000017}", "tc": "{5E6F7A8B-0000-4000-8000-000000000018}",
    "note": "{5E6F7A8B-0000-4000-8000-000000000019}",
}


def ea_qea(notes_sys1: str = "The transmitter shall measure <b>gauge pressure</b> from 0 to 10 bar.") -> bytes:
    fd, path = tempfile.mkstemp(suffix=".qea")
    os.close(fd)
    con = sqlite3.connect(path)
    con.executescript(EA_SCHEMA)
    pkgs = [(1, "Model", 0, "pkg_model"), (2, "Requirements", 1, "pkg_req"), (3, "Stakeholder", 2, "pkg_stk"),
            (4, "System", 2, "pkg_sys"), (5, "Architecture", 1, "pkg_arch"), (6, "Verification", 1, "pkg_ver")]
    for pid, name, parent, g in pkgs:
        con.execute("INSERT INTO t_package (Package_ID, Name, Parent_ID, ea_guid, CreatedDate, ModifiedDate) "
                    "VALUES (?, ?, ?, ?, '2026-10-01 10:00:00', '2026-10-01 10:00:00')", (pid, name, parent, G[g]))
        if parent:
            con.execute("INSERT INTO t_object (Object_Type, Name, Package_ID, PDATA1, ea_guid) VALUES "
                        "('Package', ?, ?, ?, ?)", (name, parent, str(pid), G[g].replace("1A2B3C4D", "9A9A9A9A")))
    objects = [
        ("stk1", "Requirement", "Monitor process pressure", 3, None, "Operators need the process pressure on site.",
         "STK-1", "Approved"),
        ("sys1", "Requirement", "Measure gauge pressure", 4, "functionalRequirement", notes_sys1, "REQ-1", "Proposed"),
        ("sys2", "Requirement", "Report diagnostics", 4, "functionalRequirement", "Diagnostics per NAMUR NE 107.",
         "REQ-2", "Proposed"),
        ("block", "Class", "Sensor module", 5, "block", "Measuring cell and electronics.", None, "Proposed"),
        ("cell", "Class", "Measuring cell", 5, "block", "Piezoresistive cell.", None, "Proposed"),
        ("act", "Activity", "Measure pressure", 5, None, "Acquire and compensate the bridge signal.", None, "Proposed"),
        ("itf", "Interface", "4-20 mA output", 5, None, "Analog current loop.", None, "Proposed"),
        ("tc", "Class", "Full-scale test", 6, "testCase", "Apply 0 and 10 bar, check output.", "TC-1", "Proposed"),
        ("note", "Note", "Remember to review", 5, None, "A diagram note.", None, None),
    ]
    oid = {}
    for key, otype, name, pkg, st, note, alias, status in objects:
        cur = con.execute("INSERT INTO t_object (Object_Type, Name, Package_ID, Stereotype, Note, Alias, Status, "
                          "ea_guid, Author, CreatedDate, ModifiedDate) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'jdoe', "
                          "'2026-10-01 10:00:00', '2026-10-02 10:00:00')",
                          (otype, name, pkg, st, note, alias, status, G[key]))
        oid[key] = cur.lastrowid
    con.execute("INSERT INTO t_objectproperties (Object_ID, Property, Value, ea_guid) VALUES (?, 'Priority', 'must', "
                "'{AAAA0000-0000-4000-8000-000000000001}')", (oid["sys1"],))
    con.execute("INSERT INTO t_objectproperties (Object_ID, Property, Value, Notes, ea_guid) VALUES (?, 'Rationale', "
                "'<memo>', 'Customers compare against a reference gauge.', '{AAAA0000-0000-4000-8000-000000000002}')",
                (oid["sys1"],))
    conns = [("Abstraction", "satisfy", "block", "sys1", None), ("Abstraction", "deriveReqt", "sys1", "stk1", None),
             ("Abstraction", "verify", "tc", "sys1", None), ("Aggregation", None, "cell", "block", "Strong"),
             ("Dependency", "trace", "sys2", "sys1", None), ("Realisation", None, "block", "act", None),
             ("Association", None, "block", "itf", None)]
    for n, (ctype, st, a, b, sub) in enumerate(conns, start=1):
        con.execute("INSERT INTO t_connector (Connector_Type, Stereotype, Start_Object_ID, End_Object_ID, SubType, "
                    "Direction, ea_guid) VALUES (?, ?, ?, ?, ?, 'Source -> Destination', ?)",
                    (ctype, st, oid[a], oid[b], sub, f"{{CCCC0000-0000-4000-8000-{n:012d}}}"))
    con.commit()
    con.close()
    with open(path, "rb") as fh:
        data = fh.read()
    os.unlink(path)
    return data


def _xid(guid: str, prefix: str = "EAID") -> str:
    return f"{prefix}_" + guid.strip("{}").replace("-", "_")


def ea_xmi() -> bytes:
    """An XMI 2.1 export as Enterprise Architect writes it (UML part, EA extension, SysML stereotype application)."""
    r1, r2, b, t = G["sys1"], G["sys2"], G["block"], G["tc"]
    return f"""<?xml version="1.0" encoding="windows-1252"?>
<xmi:XMI xmi:version="2.1" xmlns:uml="http://schema.omg.org/spec/UML/2.1" xmlns:xmi="http://schema.omg.org/spec/XMI/2.1"
  xmlns:SysML="http://www.omg.org/spec/SysML/20150709/SysML">
  <xmi:Documentation exporter="Enterprise Architect" exporterVersion="6.5" exporterID="1628"/>
  <uml:Model xmi:type="uml:Model" name="EA_Model" visibility="public">
    <packagedElement xmi:type="uml:Package" xmi:id="{_xid(G['pkg_model'], 'EAPK')}" name="Model" visibility="public">
      <packagedElement xmi:type="uml:Package" xmi:id="{_xid(G['pkg_sys'], 'EAPK')}" name="System" visibility="public">
        <packagedElement xmi:type="uml:Class" xmi:id="{_xid(r1)}" name="Measure gauge pressure" visibility="public"/>
        <packagedElement xmi:type="uml:Class" xmi:id="{_xid(r2)}" name="Report diagnostics" visibility="public">
          <ownedComment xmi:type="uml:Comment" xmi:id="EAID_c1"><body>Diagnostics per NAMUR NE 107.</body></ownedComment>
        </packagedElement>
        <packagedElement xmi:type="uml:Class" xmi:id="{_xid(b)}" name="Sensor module" visibility="public"/>
        <packagedElement xmi:type="uml:Class" xmi:id="{_xid(t)}" name="Full-scale test" visibility="public"/>
        <packagedElement xmi:type="uml:Abstraction" xmi:id="EAID_ABS1" visibility="public" client="{_xid(b)}" supplier="{_xid(r1)}"/>
        <packagedElement xmi:type="uml:Dependency" xmi:id="EAID_DEP1" visibility="public" client="{_xid(r2)}" supplier="{_xid(r1)}"/>
      </packagedElement>
    </packagedElement>
  </uml:Model>
  <SysML:Requirement xmi:id="EAID_S1" base_Class="{_xid(r1)}" id="REQ-1" text="The transmitter shall measure gauge pressure."/>
  <xmi:Extension extender="Enterprise Architect" extenderID="6.5">
    <elements>
      <element xmi:idref="{_xid(r1)}" xmi:type="uml:Requirement" name="Measure gauge pressure" scope="public">
        <properties isSpecification="false" sType="Requirement" nType="0" scope="public" stereotype="functionalRequirement" alias="REQ-1" status="Approved"/>
        <project author="jdoe" version="1.1" phase="1.0" complexity="1" status="Approved"/>
        <tags><tag xmi:id="EAID_T1" name="Priority" value="must" modelElement="{_xid(r1)}"/></tags>
      </element>
      <element xmi:idref="{_xid(b)}" xmi:type="uml:Class" name="Sensor module" scope="public">
        <properties documentation="Measuring cell and electronics." stereotype="block"/>
      </element>
      <element xmi:idref="{_xid(t)}" xmi:type="uml:Class" name="Full-scale test" scope="public">
        <properties documentation="Apply 0 and 10 bar." stereotype="testCase"/>
      </element>
    </elements>
    <connectors>
      <connector xmi:idref="EAID_ABS1"><source xmi:idref="{_xid(b)}"/><target xmi:idref="{_xid(r1)}"/>
        <properties ea_type="Abstraction" stereotype="satisfy" direction="Source -&gt; Destination"/></connector>
      <connector xmi:idref="EAID_VER1"><source xmi:idref="{_xid(t)}"/><target xmi:idref="{_xid(r1)}"/>
        <properties ea_type="Abstraction" stereotype="verify" direction="Source -&gt; Destination"/></connector>
    </connectors>
  </xmi:Extension>
</xmi:XMI>""".encode()


HARA_ROWS = [
    ["ID", "Malfunction", "Operational Situation", "Hazardous Event", "Severity", "Exposure", "Controllability",
     "ASIL", "Safety Goal ID", "Safety Goal", "Safe State", "FTTI"],
    ["HE-001", "Pressure reading too low", "Pump running at full load", "Overpressure not detected, vessel bursts",
     "S3", "E4", "C3", "ASIL D", "SG-01", "Prevent undetected overpressure", "Alarm current < 3.6 mA", "100 ms"],
    ["HE-002", "Pressure reading frozen", "Batch filling", "Overfill not detected", "S2", "E3", "C3", "ASIL B",
     "SG-01", "Prevent undetected overpressure", "Alarm current < 3.6 mA", "100 ms"],
    ["HE-003", "Spurious alarm", "Normal operation", "Unplanned shutdown", "S1", "E4", "C2", "QM", "", "", "", ""],
]
FMEA_ROWS = [  # German headers, semicolon-separated (as exported by many tools in Germany)
    ["Nr", "Funktion", "Fehlerart", "Fehlerfolge", "Bedeutung", "Fehlerursache", "Auftreten", "Entdeckung",
     "Empfohlene Maßnahme"],
    ["FM-1", "Measuring cell", "Drift at low temperature", "Wrong pressure value", "8", "Ageing of the gel", "4", "5",
     "Temperature compensation per {req}"],
    ["FM-2", "Current output", "Output stuck", "No alarm", "9", "DAC defect", "2", "3", "Read-back check"],
]


def hara_xlsx() -> bytes:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "HARA"
    ws.append(["Hazard analysis and risk assessment — pressure transmitter"])  # a title row before the header
    for row in HARA_ROWS:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def fmea_csv(req_key: str = "SYS-1") -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    for row in FMEA_ROWS:
        w.writerow([c.replace("{req}", req_key) for c in row])
    return buf.getvalue().encode("utf-8")


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "."
    os.makedirs(out, exist_ok=True)
    for name, data in (("enterprise-architect/pressure-transmitter.qea", ea_qea()),
                       ("enterprise-architect/pressure-transmitter.xmi", ea_xmi()),
                       ("medini-analyze/hara.xlsx", hara_xlsx()), ("medini-analyze/fmea.csv", fmea_csv())):
        target = os.path.join(out, name)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "wb") as fh:
            fh.write(data)
        print("wrote", target)
