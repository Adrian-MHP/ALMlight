# ADR-0023 Tests, risks, plans and BOM as views on the generic item/link model

**Context.** Enterprise suites have dedicated modules (test management, risk management, planning, BOM) with their own
tables and screens. Building separate data models would duplicate versioning, workflow, audit, baselines, variants
and import/export — and would not be configurable per customer.

**Decision.** The features are built on items, links and workflows, connected to the engine through **semantic
bindings** in the information model (`test_steps_field`, `defect_type`, `risk_type`, `mitigation_link`,
`release_type`, `planned_link`): test steps are a field of the test case, step results are stored with the test record
(the only new column), risks and releases are item types with computed fields and workflows, planning is the
`planned in` link (editable on frozen items, as planning does not change them), BOM quantity, unit, find number and
effectivity are attributes of the structural link. Each feature adds an aggregation endpoint and a page (risk matrix
and register, plans with burn-up, multi-level BOM with roll-up and where-used); a feature is shown only when the
project's model binds it.

**Consequences.** + Everything is versioned, baselined, audited, traceable, importable and exportable like any item.
+ Customers rename, extend or switch off the features in YAML. + Few new tables. − Aggregations are computed on
request (measured: < 150 ms for 300 risks, 150 planned items, 541 BOM lines). − Feature semantics depend on the
bindings; templates must keep them consistent (validated on save).
