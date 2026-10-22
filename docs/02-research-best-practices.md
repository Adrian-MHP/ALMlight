# 2 Research: best practices and future direction

This summarises the research done before designing ALMlight: how leading ALM/PLM suites solve the problems,
which standards matter, where systems engineering is heading, and what integrations an engineering backbone
needs. The rule for the product: **proven practice of the leading suites outranks individual customer wishes**;
customer specifics are then expressed through configuration.

## 2.1 Patterns adopted from leading suites

| Pattern | Seen in | ALMlight implementation |
|---|---|---|
| Typed, configurable work items with custom fields and workflows per type | Polarion, codebeamer | Item types, field definitions and workflows in the project template |
| Live documents: a specification is an ordered view on individually managed items | Polarion LiveDoc | Document item type + ordered structural links; document view with inline editing |
| Suspect links: a link is flagged when the linked item changes | Polarion, DOORS | `suspect_on_target_change` per link type; review & confirm |
| Item / revision semantics; revisions are formal generations, iterations the saves in between | Teamcenter, ENOVIA ("A.1, A.2 … B.1") | Immutable `ItemVersion` with revision letter and iteration |
| Maturity states In Work → Frozen → Released → Obsolete; released content is never edited, it is revised | 3DEXPERIENCE/ENOVIA | `frozen` / `released` state flags; *Revise* starts the next revision |
| Closed-loop change (problem report → change request → change notice/order), certified CMII process; release of solution items via the change | Teamcenter (CMII), ENOVIA Change Action | PR → CR (CCB approval) → CO; change-controlled types can only be revised under an open CO; CO release releases its affected items |
| Project and document baselines; collections of document revisions | Polarion | Baselines of a project or a sub-tree, revision rules *latest* / *released*, compare |
| Branching of documents with "branched from" relations and 3-way merge | Polarion (2310/2404) | Document branches with field-level 3-way merge in both directions (ADR-0011) |
| Variant management with feature/option models and variant conditions on a 150% structure | Teamcenter Product Configurator, Polarion Variants, pure::variants (ISO/IEC 26580) | Feature items, `requires`/`excludes`, variant items, applicability expressions on items and links |
| RFLP (Requirements, Functional, Logical, Physical) | 3DEXPERIENCE CATIA, MBSE practice | Requirements, functions and system elements with `realizes` / `satisfies` links |
| Electronic signatures on approvals | Polarion, Teamcenter (21 CFR Part 11 practice) | Password re-entry with displayed meaning, stored per vote |
| Audit trail / status accounting | All, ISO 10007 | Hash-chained audit log + workflow events |

## 2.2 Standards that shape the model

- **ISO/IEC/IEEE 15288, V-model** — stakeholder → system → subsystem/module requirements, verification on each
  level, validation against stakeholder needs. → requirement levels, `derives_from`, maturity view.
- **ISO 10007 (configuration management)** — configuration identification, change control, status accounting and
  configuration audit. → items/versions/baselines, change process, workflow events, audit trail.
- **CMII** — closed-loop change with impact analysis and verified implementation. → change objects and guards.
- **ReqIF 1.2 (OMG)** — the exchange format of DOORS, Polarion, codebeamer and OEM supplier portals:
  SpecObjects with typed attributes, SpecRelations and Specification hierarchies. → ReqIF export.
- **OSLC (OASIS)** — linked-data integration of lifecycle tools; Core 3.0, Query 3.0 and Change Management 3.0 are
  OASIS Standards (2021), Requirements Management is at 2.1. → future integration adapter (roadmap).
- **SysML v2 and the Systems Modeling API (OMG, adopted 2025)** — a standard REST API to model repositories.
  → future connector to SysML v2 tools (e.g. SysON) to link items with model elements.
- **ISO/IEC 26580 / 26558 (product line engineering)** — feature-based variability linked to engineering assets.
  → feature model + applicability expressions.
- **Functional safety (IEC 61508, ISO 26262)** — bidirectional traceability from requirements to implementation and
  tests, evidence that traces survived changes. → suspect links, verification status pinned to versions, baselines.
  (Tool qualification is out of scope for the MVP; the audit trail and test coverage help a later qualification.)
- **INCOSE Guide to Writing Requirements (v4, 14 characteristics / ~41 rules)** — basis for future automated
  requirement-quality checks.

## 2.3 Where systems engineering is heading

- **Model-based and digitally threaded.** INCOSE's *Systems Engineering Vision 2035* expects model-based practice
  integrated with simulation and analysis to be standard. The digital thread is an unbroken chain of traceability
  across tools, each tool staying the authoritative source for its own data. → ALMlight is the backbone that
  *links* artefacts (external references, webhooks) instead of copying everything.
- **Product platforms and variability.** Companies move from clone & own to platform-based reuse and product line
  engineering; they need to know commonality, variability and the maturity of each reusable module.
  → feature model, reuse strategy per element, maturity per element and variant.
- **Continuous verification.** CI pipelines produce test evidence continuously; traceability must consume it.
  → JUnit import (also callable from CI with an API token).
- **Regulation drives traceability.** The EU *Cyber Resilience Act* requires vulnerability reporting since
  11 September 2026 and SBOMs, secure-by-design evidence and vulnerability handling from 11 December 2027.
  The EU *Digital Product Passport* (ESPR) starts with batteries in 2027, other product groups follow.
  → requirements of type security/regulatory, document items for SBOMs and certificates, baselines as the
  record of what was released; an SBOM connector is on the roadmap.
- **AI with governance.** PLM trend reports for 2026 describe a move from copilots to agentic workflows that propose
  changes and route approvals under human oversight — with traceability as the anchor. → AI features must act
  through the same API, leave audit entries and never bypass approvals (roadmap).

## 2.4 Integration landscape of a typical SME

| Tool class | Typical tools | Integration in ALMlight |
|---|---|---|
| Git hosting / code | GitHub, GitLab, Azure Repos | Inbound webhooks: commits, PRs, builds mentioning item keys → external references |
| Work management | Azure Boards, Jira | Azure DevOps service hooks (work items) → external references; Jira later |
| CI/CD | GitHub Actions, Azure Pipelines, Jenkins | JUnit XML upload via API token → test runs |
| Requirements tools / customers | DOORS, Polarion, OEM portals | ReqIF export (import on the roadmap), CSV/Excel |
| Architecture / MBSE | Enterprise Architect, Capella, SysML v2 tools | External references now; SysML v2 API connector later |
| CAD / PDM | SolidWorks PDM, Creo/Windchill, Inventor Vault | Document items + external references to PDM IDs; attachments for released files |
| ERP | SAP, Business Central | Out of MVP scope; outbound webhooks (released items) as integration hook |
| Notification / chat | Teams, Slack | Outbound webhooks |

## 2.5 Low-cost alternatives reviewed

Open-source and low-cost tools cover parts of the problem (e.g. Tuleap for agile ALM, StrictDoc/Doorstop for
docs-as-code requirements, Capella for MBSE), but none combines configurable items, PLM-style revisions and change
control, variants and verification in one lightweight, self-hostable package for engineering SMEs. That gap is
ALMlight's position.

## Sources

- INCOSE, Systems Engineering Vision 2035 — https://www.incose.org/sevision
- OASIS OSLC Core/Query 3.0 Standards — https://www.oasis-open.org/?p=7646 ; Change Management 3.0 — https://www.oasis-open.org/?p=7129
- OMG SysML v2 news (Systems Modeling API adopted) — https://www.omg.org/sysml/news-articles.htm ; release repo — https://github.com/systems-modeling/sysml-v2-release
- Polarion release notes (baselines, collections, branching, merge) — https://blogs.sw.siemens.com/polarion/polarion-alm-2404-whats-new-and-noteworthy/ , https://blogs.sw.siemens.com/polarion/polarion-alm-2310-whats-new-and-noteworthy/ , https://blogs.sw.siemens.com/polarion/polarion-alm-20-r2-whats-new-and-noteworthy/
- Teamcenter Change Management fact sheet (CMII closed loop) — https://blogs.sw.siemens.com/wp-content/uploads/sites/14/2023/11/Siemens-SW-Teamcenter-Change-Management-Fact-Sheet.pdf
- 3DEXPERIENCE maturity and revisions — https://hawkridgesys.com/blog/maturity-states-in-solidworks-cloud-services-3dexperience , https://www.solidsolutions.co.uk/how-to-revision-solidworks-files-and-release-engineering-data-in-the-3dexperience-platform/
- ISO 10007 overview — https://en.wikipedia.org/wiki/ISO_10007
- ReqIF structure — https://microtool.de/en/knowledge-base/what-is-reqif
- Product line engineering / ISO 26580 context — https://events.3ds.com/mbse-cyber-experience-symposium-europe-2022/holistic-variant-management-day-two-track-three
- Functional safety traceability — https://www.qa-systems.com/solutions/iec-61508/ , https://www.vector.com/en/business-unit/code-testing-and-verification/standards-and-compliance/functional-safety-industry-standards/
- INCOSE Guide to Writing Requirements v4 — https://www.incose.org/docs/default-source/working-groups/requirements-wg/gtwr/incose_rwg_gtwr_v4_040423_final_drafts.pdf
- EU Cyber Resilience Act timeline — https://www.docker.com/blog/eu-cyber-resilience-act-overview/
- EU Digital Product Passport timeline — https://www.ptc.com/en/blogs/retail/digital-product-passport-espr
- PLM trends 2026 (agentic AI, traceability) — https://www.hcltech.com/en-us/trends-and-insights/trends-reshaping-plm-for-2026-and-beyond
- Azure DevOps service hooks — https://learn.microsoft.com/en-us/azure/devops/service-hooks/index
