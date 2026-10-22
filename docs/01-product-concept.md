# 1 Product concept

## Vision

**ALMlight is a digital engineering backbone for small and medium-sized engineering companies**: one connected,
versioned and auditable source of truth for requirements, architecture, verification, documents, variants and
changes, without the licence costs and operating effort of enterprise ALM/PLM suites such as Polarion,
Teamcenter or 3DEXPERIENCE.

It adopts the *proven concepts* of those suites (typed work items, live documents, traceability with suspect
links, revisions and maturity states, closed-loop change management, baselines, feature-based variant
management) and implements them in a deliberately lean, configurable product.

## Problem

Small and mid-sized companies that develop mechatronic systems face the same engineering demands as large OEMs
(product variants, platform reuse, safety and security standards, customer audits, regulatory duties such as the
EU Cyber Resilience Act), but typically work with:

- requirements in Word/Excel or in a generic ticket system, without levels or allocation to modules,
- architecture knowledge in people's heads or in drawing tools,
- reuse by *clone & own*, re-testing everything per project because nobody knows what is verified,
- informal change handling ("technical inquiries") without impact analysis,
- no common baseline of what was released, tested and delivered.

Enterprise tools solve this but cost six-figure licence and integration budgets and need dedicated admins.

## Delivery model

ALMlight is delivered by MHP as a **tailored solution per customer**:

1. *Assess*: workshops on the customer's engineering process and pain points.
2. *Model*: derive the customer's information model (item types, fields, link types, workflows) —
   "use case first, information model second, tool third".
3. *Configure*: express that model as a process template (YAML) — no code changes for most customers.
4. *Extend*: add connectors or small plugins where the customer's tool landscape needs them.
5. *Hand over*: the customer runs ALMlight on their own infrastructure with minimal maintenance.

Product consequences:

| Requirement of the model | Product decision |
|---|---|
| Tailor per customer without forking | Configurable metamodel as data (process templates) + semantic bindings |
| Customer runs it themselves | Two containers (app + PostgreSQL), automatic migrations, built-in backup/archive |
| No licence lock-in | Only permissively licensed dependencies (MIT/BSD/Apache/PostgreSQL) |
| Connect existing tools | API-first, webhooks in/out, standard formats (ReqIF, JUnit XML, CSV/Excel) |
| Audits and compliance | Immutable versions, e-signatures, hash-chained audit trail |

## Target users

| Persona | Needs |
|---|---|
| Product manager | Capture market/stakeholder needs, see what is covered and released per variant |
| Systems engineer / architect | Decompose the system, allocate requirements, define interfaces and variants |
| Developer (HW/SW/ME) | Know the valid requirements for "my" module, link commits/PRs/CAD data |
| Test engineer | Derive test cases, record results (manual and CI), know what must be re-tested |
| Quality / safety manager | Approvals with signatures, baselines, audit trail, traceability evidence |
| Change control board | Impact analysis, decisions, controlled release of changes |
| Project/platform owner | Dashboards: coverage, maturity, open changes, suspect links |

## Guiding principles

1. **Information model first** — the value is in the connected data, not in screens.
2. **Everything is an item** — requirements, elements, tests, changes, documents and features share one engine
   for versioning, workflow, traceability, search and audit.
3. **Immutable history** — every save is a version; released revisions never change.
4. **Configuration over code** — customer-specific structures live in templates.
5. **Lean operations** — few moving parts; boring, robust technology.
6. **Open integration** — REST API for everything the UI does; standard exchange formats.
7. **Best practice over wish lists** — proven concepts of leading ALM/PLM suites take precedence over
   one-off customer requests, then tailored by configuration.

## Capability map

| Capability | MVP (implemented) | Later (prepared) |
|---|---|---|
| Projects, configurable item types & fields | ✔ templates, JSON/YAML, compatibility checks | Visual template editor |
| Requirements & specifications | ✔ levels, live documents, ordering, headings | Rich-text/tables, Word export |
| Documents & files | ✔ controlled documents, versioned attachments (SHA-256 store) | S3 storage, viewer for CAD/PDF |
| Relations & traceability | ✔ typed links, rules, cycles, suspect links, matrix, impact analysis | Graph visualisation |
| Versioning & history | ✔ revisions/iterations, diff, restore, timeline | — |
| Baselines | ✔ project or sub-tree, latest/released rule, compare | Baseline-based exports/reports |
| Branching & merging | ✔ revisions under change orders; document branches with field-level 3-way merge (both directions) | Structural move/delete merge |
| Status, workflows, approvals | ✔ configurable workflows, guards, effects, approvals, four-eyes, e-signature | Parallel approval steps, delegation |
| Configuration & change management | ✔ PR → CR → CO, change-controlled revisions, release via CO | Effectivity (date/serial) |
| Variants | ✔ feature model, constraints, variants, applicability (150% model) | Variant-specific baselines, BOM export |
| Verification | ✔ test cases/runs, JUnit import, re-test detection, coverage, maturity | Test automation plugins |
| Search & navigation | ✔ full-text, filters, global search, dashboards | Saved queries, query language |
| Users & roles | ✔ local users, project roles, API tokens | SSO (OIDC/Entra ID), groups |
| Audit & compliance | ✔ hash-chained audit trail, signatures, status accounting | Compliance report templates |
| Import / export | ✔ CSV/Excel (dry run), ReqIF export, project archive | ReqIF import, OSLC |
| Integrations | ✔ GitHub & Azure DevOps hooks, external refs, outbound webhooks, CI | GitLab, SysML v2 API, PDM/CAD, AI assistant |
