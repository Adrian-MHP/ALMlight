# Sample files for the connectors

Small, generic files to try the connectors (Project → Connectors) and for the automated tests.

| File | Tool | What it shows |
|---|---|---|
| `enterprise-architect/pressure-transmitter.qea` | Enterprise Architect 16+ model (SQLite) | Packages, requirements with notes, alias, status and tagged values, blocks, an activity, an interface, a test case; satisfy, deriveReqt, verify, trace, realisation and composition connectors. Also the target for *Write back into .qea*. |
| `enterprise-architect/pressure-transmitter.xmi` | EA XMI 2.1 export | The same elements in EA's XMI structure, incl. a SysML «requirement» stereotype application |
| `medini-analyze/hara.xlsx` | medini analyze HARA | Hazardous events with S/E/C, ASIL, safety goals, safe state, FTTI (HE-003 deliberately states QM where ISO 26262 gives ASIL A — the import reports it) |
| `medini-analyze/fmea.csv` | FMEA worksheet | German column names, semicolon-separated; the measure of FM-1 mentions `SYS-1` and is linked as mitigation |

The `.qea` file contains the tables of EA's repository schema that the connector reads; it is not a complete EA
project. Regenerate the files with `python backend/tests/connector_fixtures.py samples` (inside the test container).
