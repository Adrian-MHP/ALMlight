# 3 Analysis of the reference customer input

The first customer input was the documentation of a half-day **systems engineering and modularisation workshop**
with a mid-sized engineering company that develops a modular device platform (problem space poster, target
corridor poster, findings, fields of action and roadmap). The material itself is confidential and not part of
this repository; this page records only the generic, reusable conclusions.

The input is not a tool specification. It describes engineering problems and a target picture. That is the right
starting point ("use case first, information model second, tool decision third"), and it maps well onto the
best-practice patterns in [02-research](02-research-best-practices.md).

## 3.1 Observed problem patterns (generic)

| Area | Observation | Typical for SMEs |
|---|---|---|
| Market / customer | Product management specifies per customer wish; needs and solutions get mixed early | yes |
| Requirements | ~100 requirements, hierarchical in a work-management tool; stakeholder and system level not separated; no allocation to subsystems or modules | yes |
| Architecture & variants | Product decomposed directly into hardware / software / mechanics; no mechatronic subsystems, no module specifications, implicit knowledge | yes |
| Development | Components are reused as library or clone & own; changes driven by customer inquiries without platform control | yes |
| Verification & release | Everything re-tested in every project; release only on component level; no maturity per module or variant | yes |
| Governance | No technical system owner / system architect / safety manager role; no proper engineering change process | yes |

## 3.2 Target picture → capabilities

| Need from the workshop | Generic capability | Where in ALMlight |
|---|---|---|
| Separate stakeholder, system, subsystem/module requirements; allocate to modules | Requirement levels, `derives_from`, `satisfies` | Template *systems_engineering*, coverage view |
| Specifications as controlled documents and their release | Live documents with a release guard on contained items | Document view, `contained_items_released` guard |
| Explicit system boundary, subsystems, modules, interfaces | System elements with levels, interfaces, RFLP | Structure view |
| Decide "reuse, modify or develop new" per element | Reuse strategy field per element | `reuse_strategy`, structure badges |
| Make combinatorics transparent; feature model; allowed combinations | Feature model, constraints, variants, applicability | Variants page, configurator |
| Configuration mechanisms on requirement level | Applicability expressions on requirements, tests and structure links | 150% → 100% filter |
| Lean change process (change request / change order) with impact analysis | CMII-light change objects, impact analysis | Changes board, impact tab |
| Version and baseline logic for modules | Revisions, baselines with revision rules | Baselines page |
| Traceability requirement → test case → result; test status per component | Verification links, test runs, verification status pinned to versions | Verification tab, coverage |
| Maturity per module and variant; know what to re-test after a change | Maturity matrix, suspect links, re-test detection | Maturity view |
| Toolchain: existing work-management tool, Git and an architecture tool must stay connected | Integration via webhooks and external references | Azure DevOps / GitHub hooks |
| Identify AI levers (requirement quality, test derivation) | API-first platform with audit trail | Roadmap |
| Success criteria: reuse rate per module, module variants vs. offered variants, re-test effort, change lead time | KPIs derivable from the data | Dashboard (partly), roadmap reports |

## 3.3 Consequences for the product (not customer-specific)

1. Requirement levels and allocation must be first-class: SMEs typically have *one* requirement level today.
2. Platform/module thinking needs a structure view with reuse strategy and maturity, not only a requirement tree.
3. Variants must be expressible early on requirements (not only on BOMs) because the configuration is decided in
   sales/product management.
4. A minimal change process must be enforceable by the tool (change-controlled types), but light enough for a
   small team (one CCB approval, one change order).
5. Existing tools (work management, Git, architecture tool) are not replaced on day one; ALMlight must link to them.
6. Organisational topics (roles, governance) are supported by roles, approvals and the audit trail, but the tool
   does not replace them; consulting covers that part.

## 3.4 Deliberately not copied

- Customer-specific document names and abbreviations — these become *labels* in a customer template.
- Customer-specific product decompositions — the demo uses a generic smart-sensor example only.
- Tool-specific behaviour of the customer's current tools.
