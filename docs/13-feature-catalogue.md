# 13 Feature catalogue — Ariadne compared with an enterprise engineering backbone

This catalogue lists what Ariadne 0.7 delivers, grouped by the capability areas customers know from the enterprise
suites: **Polarion ALM** for requirements, tests, documents and process, and **Teamcenter** for product structure,
change and data management. The reference column describes the capability as users of those suites expect it; it is
an orientation based on publicly documented functionality, not a feature-by-feature statement about a specific
release of those products.

**Legend** ● available · ◐ partly, or by configuration · ○ on the roadmap · — deliberately out of scope

## 13.1 Summary

| Capability area | Reference | Ariadne 0.7 |
|---|---|---|
| Requirements & live documents | Polarion | ● |
| Traceability & impact analysis | Polarion | ● |
| Workflow, review, e-signature, audit | Polarion / Teamcenter | ● |
| Test management | Polarion | ● (no parametrised test runs yet) |
| Risk management (FMEA) | Polarion (FMEA/risk templates) | ● (ASIL lookup tables ◐) |
| Release planning | Polarion Plans | ● releases, iterations, milestones, capacity, planning board |
| Kanban boards | Polarion boards | ● configurable, drag & drop runs workflow transitions |
| Schedule / timeline | Teamcenter Schedule Manager | ● Gantt, FS/SS/FF/SF dependencies with lag, critical path, baseline comparison, auto-schedule |
| Time recording & resources | Polarion work records, Teamcenter timesheets / resource graph | ● timesheet, spent/remaining, resource load, levelling |
| Queries, bulk edit | Polarion query builder, bulk edit | ● query builder with OR/AND groups, query language, configurable table, bulk edit with preview |
| Change management (closed loop) | Teamcenter / Polarion | ● (change-order effectivity ○) |
| Item/revision model & maturity | Teamcenter | ● |
| Product structure & BOM | Teamcenter | ● for the engineering BOM (MBOM/BOP —) |
| Variants & configuration | Teamcenter / pure::variants-style | ● |
| Document & file management (vault) | Teamcenter | ● (CAD integrations —, 3D viewer ○) |
| Collaboration & notifications | Polarion / Active Workspace | ● |
| Reporting & dashboards | Polarion LiveReports / Teamcenter reporting | ● |
| Search & saved queries | both | ● query language, saved views with columns |
| Integration & identity | both | ● REST, webhooks, ReqIF, OIDC (OSLC, Jira ○) |
| Localisation | both | ● English and German (interface, model labels, server messages, e-mails, exports) |
| Scale-out & multi-site | Teamcenter | — single site, one app process |

## 13.2 Requirements and live documents

| Capability | Reference expectation | Ariadne | Notes |
|---|---|---|---|
| Documents assembled from individually versioned items | Polarion LiveDoc | ● | Headings, numbering, reorder, inline add/edit, reuse of existing items |
| Rich text: formatting, lists, tables with merged cells, images | LiveDoc editor | ● | One canonical format for editor, Word, PDF, ReqIF, Excel |
| Real-time co-editing with presence | LiveDoc collaboration | ● | Live cursors, block presence, sessions saved as versions with co-authors |
| Configurable item types, fields, link types, workflows | Polarion project templates | ● | YAML process templates, validated against existing data |
| Computed fields | Polarion calculated fields / scripts | ● | Formulas and classification bands, live in forms |
| Word export, PDF export | Polarion export templates | ● | Word in the **customer's corporate template** (placeholders, TOC, styles); PDF in the standard layout |
| Word round trip (review in Word, re-import edits and comments) | Polarion round trip | ● | Edit or comments-only copies, conflict detection |
| ReqIF import/export (OEM/supplier exchange) | Polarion ReqIF | ● | `.reqif`/`.reqifz` with images, mapping wizard, update on re-import |
| Document history, time travel, compare | LiveDoc history/compare | ● | Any change point or baseline; word-level diff; cross-project compare |
| Branch and merge documents | Polarion document branching | ● | Field-level 3-way merge in both directions |
| Threaded comments, resolve, @mentions | LiveDoc comments | ● | Comments in documents and items; mentions notify |
| Recycle bin, collections of document baselines | Polarion collections | ● | |

## 13.3 Traceability and impact

| Capability | Reference expectation | Ariadne | Notes |
|---|---|---|---|
| Typed links with allowed source/target types | both | ● | Cross-project links |
| Suspect links when a linked item changes | Polarion suspect links | ● | Review and confirm |
| Impact analysis | both | ● | Dependents and where-used |
| Traceability matrix and coverage | Polarion | ● | From stakeholder needs to test results |
| Gap queries (unverified, unallocated, unmitigated, unplanned) | Polarion queries | ● | Saved as shared views; export of the current view |

## 13.4 Workflow, review and compliance

| Capability | Reference expectation | Ariadne | Notes |
|---|---|---|---|
| Configurable lifecycles with guards and effects | both | ● | Freeze per state, role per transition |
| Approvals by role, four-eyes principle | Polarion approvals / Teamcenter workflow signoff | ● | N approvers, rejection path, inbox |
| Electronic signatures (password re-entry, meaning) | 21 CFR Part 11 style | ● | |
| Tamper-evident audit trail | both | ● | Hash chain with verification |
| Role-based access | both | ● | Viewer, contributor, reviewer, manager, admin; no per-field ACLs (◐) |
| Process templates for standards (ASPICE, ISO 26262, IEC 62304, IEC 62443) | Polarion solution templates | ◐ | Systems-engineering template; further standard templates are YAML work per customer |

## 13.5 Test management

| Capability | Reference expectation | Ariadne | Notes |
|---|---|---|---|
| Test cases with steps | Polarion test steps | ● | Up to 300 steps, versioned with the case |
| Test runs pinned to versions | Polarion test runs | ● | Re-test detection when a case changes |
| Step-by-step execution with actual results | Polarion execution view | ● | Result derived from the steps |
| Defect from a failed step | Polarion "create defect" | ● | Quotes step, expected, actual; linked and referenced |
| CI results (JUnit) | Polarion importers | ● | |
| Test run templates, parametrised iterations | Polarion | ○ | |

## 13.6 Risk management

| Capability | Reference expectation | Ariadne | Notes |
|---|---|---|---|
| FMEA: severity, occurrence, detection, RPN, level | Polarion FMEA / risk templates | ● | Computed and classified |
| Risk matrix before/after mitigation | risk dashboards | ● | Click-to-filter register |
| Mitigation traceability | both | ● | `mitigated by` → requirements, design, tests (suspect on change) |
| Residual-risk acceptance with e-signature | regulated processes | ● | Approval workflow |
| HARA/ASIL determination tables | ISO 26262 templates | ◐ | Possible with computed fields; lookup-table type ○ |

## 13.7 Planning and work management

| Capability | Reference expectation | Ariadne | Notes |
|---|---|---|---|
| Releases, iterations, milestones as a hierarchy | Polarion Plans | ● | Sub-plan scope rolls up into the release |
| Estimates, capacity and load | Polarion Plans | ● | Estimate field on plannable items, capacity per plan |
| Planning board (backlog ↔ plans) | Polarion planning view | ● | Drag & drop, load per column |
| Progress, schedule status, burn-up and burn-down | Polarion Plans | ● | By items or by estimate |
| Configurable Kanban boards | Polarion boards | ● | Columns/swimlanes by status, owner, plan, type or field; WIP limits; drag & drop runs transitions |
| Gantt timeline with tasks, milestones, dependencies | Teamcenter Schedule Manager | ● | Finish-to-start, start-to-start, finish-to-finish, start-to-finish, lag/lead in working days; drag to reschedule |
| Critical path, slack, scheduling conflicts | Teamcenter Schedule Manager | ● | Working-day slack per dependency type against successors and plan deadlines |
| Auto-scheduling | Teamcenter Schedule Manager, MS Project | ● | Resolve conflicts or as soon as possible; preview; per plan |
| Schedule baseline comparison | Teamcenter Schedule Manager | ● | Baselined dates shown under every bar |
| Time recording, weekly timesheet, spent/remaining effort | Polarion work records, Teamcenter timesheets | ● | Records visible to author and managers, totals to all |
| Resource load per person and week, capacity | Teamcenter resource graph | ● | Hours per day per member; overloads with the tasks behind them |
| Resource levelling | Teamcenter, MS Project | ● | Greedy, keeps dependencies, preview; no skills/calendars per person (◐) |

## 13.8 Change management

| Capability | Reference expectation | Ariadne | Notes |
|---|---|---|---|
| Problem report → change request (CCB) → change order | Teamcenter change management (CMII) | ● | Affected items with actions |
| Revise only under an open change order | Teamcenter | ● | Change-controlled types |
| Release of affected items with the change order | Teamcenter | ● | Blocked while files of affected items are checked out |
| Effectivity on change orders (date/serial) | Teamcenter | ○ | Date effectivity on BOM lines is available |

## 13.9 Product data: items, revisions, BOM, variants

| Capability | Reference expectation | Ariadne | Notes |
|---|---|---|---|
| Item / revision model (A.1 … B.1), maturity states | Teamcenter | ● | Immutable versions, diff, restore |
| Multi-level engineering BOM: quantity, unit, find number | Teamcenter Structure Manager | ● | Rolled-up totals, in-place editing |
| Date effectivity on BOM lines | Teamcenter | ● | "Effective on" view |
| Where-used (also across projects) | Teamcenter | ● | With quantities per parent |
| BOM export | Teamcenter | ● | Excel/CSV with paths and totals |
| Variants: feature model, constraints, 150 % → 100 % | Teamcenter variants / product configurator | ● | Applicability on items and links, configurator, variant documents |
| Baselines (latest / released revision rule) | Teamcenter baselines | ● | Project, document or structure scope; compare |
| Substitutes/alternates, serial/lot effectivity | Teamcenter | ○ | |
| Classification library | Teamcenter Classification | ◐ | Item types and fields; no hierarchical class library |
| Manufacturing BOM, bill of process | Teamcenter Manufacturing | — | Outside an engineering backbone for SMEs |

## 13.10 Document and file management

| Capability | Reference expectation | Ariadne | Notes |
|---|---|---|---|
| Files attached to item revisions | Teamcenter datasets | ● | Content-addressed store, versioned with the item |
| Check-out / check-in (exclusive lock) | Teamcenter | ● | Manager can cancel; audited |
| File revisions with history | Teamcenter | ● | Download any revision |
| No release while checked out | Teamcenter | ● | Review, release and change-order release are blocked |
| Preview | Active Workspace | ● | Images and PDF |
| CAD integrations (NX, SolidWorks, Creo) | Teamcenter integrations | — | External references to CAD/PDM objects (◐) |
| 3D visualisation | JT viewer | ○ | |

## 13.11 Collaboration, reporting, search

| Capability | Reference expectation | Ariadne | Notes |
|---|---|---|---|
| Watch / subscriptions | Polarion watches / Teamcenter subscriptions | ● | Watching a document covers its content |
| Notifications (owner, approval, mention), live and by e-mail | both | ● | Bulk changes collapse into one summary; e-mail digests |
| User-built reports and dashboards | Polarion LiveReports | ● | KPI, chart, table, trend, coverage, matrix, maturity widgets; Excel/PDF |
| Engineering KPIs | | ● | Reuse rate, change lead time, re-test effort, variant ratio |
| Full-text search | both | ● | |
| Query builder with field chips (any field, links, dates, users) | Polarion query builder | ● | *is / is not*, Any/None, periods, link gaps |
| Query language (copy, paste, edit) | Polarion Lucene queries | ● | `field:value`, `OR`/`AND` across fields with parentheses, `NOT` on clauses and groups, ranges, relative dates |
| Configurable table: columns, sorting, preview | Polarion work item table | ● | Custom-field columns, saved with views |
| Bulk edit with preview | Polarion bulk edit | ● | Fields, owner, status, plan, links, watch, delete |
| Workflow viewer | Polarion workflow viewer | ● | Current state, path taken, possible transitions |
| Scheduled report e-mails | both | ○ | |

## 13.12 Integration, identity, operations

| Capability | Reference expectation | Ariadne | Notes |
|---|---|---|---|
| REST API with OpenAPI, API tokens | both | ● | |
| Webhooks in (GitHub, Azure DevOps) and out (signed) | both | ● | Transactional outbox |
| CSV/Excel import/export, project archives | both | ● | Dry run, all-or-nothing |
| Single sign-on | both | ● | OpenID Connect (Entra ID, Keycloak, Okta); LDAP/SAML via an IdP broker (◐) |
| OSLC, Jira/GitLab connectors, SysML v2 API | Polarion/Teamcenter connectors | ○ | Roadmap |
| Localised UI | both | ● | English and German; model labels translated per customer; further languages by adding dictionaries |
| Deployment | server installation | ● | Two containers, automatic migrations, backup/restore |
| High availability, multi-site replication | Teamcenter | — | Single app process per installation |

## 13.13 Positioning

Ariadne covers the daily engineering-backbone work of an SME — requirements and documents, traceability, tests,
risks, plans, boards, schedules, change, BOM, variants and files — in one data model with one history, one audit trail and one user
interface, delivered in two containers. It deliberately leaves out what only large OEM organisations need
(manufacturing planning, CAD-authoring integrations, multi-site replication). Where the enterprise suites
remain the system of record, Ariadne exchanges data through ReqIF, Word, Excel and the REST API.
