# ADR-0022 Computed fields as validated expressions; additive template updates

**Context.** FMEA needs the RPN (S×O×D) and a risk level from bands; customers ask for similar derived values
(weights, scores, effort sums). Spreadsheet-like scripting would be powerful but unsafe and hard to validate.
Existing projects must also receive new template capabilities (risk, release, test steps, BOM attributes) without
losing their own tailoring.

**Decision.** Two declarative computed field kinds in the information model: `formula` — arithmetic over numeric
fields with a whitelist of operators and four functions, parsed with Python's AST and validated when the model is
saved — and `classify` — an enum value from numeric bands. The server recomputes computed fields on every save and
ignores client input for them; the browser evaluates the same small grammar only as a live preview. Number fields get
`min`/`max`. Template updates are computed as a **diff of additions** between the shipped template and the project
model (new item types, fields, link types, link attributes, workflows, semantics) and applied by a manager in one
step through the normal, data-validated model update; nothing existing is changed or removed.

**Consequences.** + Safe, explainable calculations that survive import, export and archives. + Projects pick up new
capabilities without migrations of their own model. − No conditionals or lookups in formulas (tables such as ISO
26262 ASIL determination need a future lookup kind). − Renamed or changed template elements are not propagated —
on purpose, they are the project's tailoring.
