# 6 MVP scope and roadmap

## 6.1 Implemented in the MVP (v0.1)

**Core engine**
- Projects from process templates (*Systems Engineering*, *Lean Requirements & Test*); information model editable
  as JSON with validation and compatibility checks against existing data
- Items of configurable types with typed custom fields, Markdown descriptions, owners, keys per prefix
- Immutable versions (revision.iteration), diff between any versions, restore, complete timeline
- Revise released items; change-controlled types only under an open change order
- Attachments versioned with the item (content-addressed SHA-256 store), comments

**Traceability**
- Typed links with source/target rules, attributes, applicability, cycle prevention, cross-project links
- Suspect links on target change, review & confirm; suspect list
- Impact analysis (dependents + where-used), traceability matrix, coverage per requirement type

**Documents & structure**
- Live documents: ordered outline of items with headings, inline add/edit/reorder, release guard
- Product/system structure with levels, reuse strategy, quantities, variant filter, maturity indicators

**Workflow & compliance**
- Configurable workflows with role checks, comments, guards, effects
- Approvals with N approvers by role, four-eyes principle, e-signature with meaning, rejection path
- Approval inbox across projects; status accounting (workflow events)
- Hash-chained audit trail with verification

**Change management**
- Problem report → change request (CCB approval) → change order; affected items with actions;
  release of all affected items through the change order

**Baselines**: project or sub-tree, revision rule latest/released, compare with baseline or current state

**Variants**: feature model (mandatory/optional, alternative/or groups), requires/excludes, variants with validation,
applicability expressions on items and links, configurator (150% → 100%)

**Verification**: test runs and records pinned to versions, JUnit XML import from CI, verification status with
re-test detection, maturity per element (specified / realised / verified / validated)

**Integration & exchange**: REST API with OpenAPI docs, personal API tokens, GitHub and Azure DevOps inbound
webhooks, manual external references (CAD/PDM/URL), outbound signed webhooks via transactional outbox,
CSV/Excel export and import (dry run, all-or-nothing), ReqIF 1.2 export, full project archive (export/import)

**Operations**: two containers, automatic migrations, bootstrap admin, demo data switch, health check

## 6.2 Prepared but not built (extension points)

| Topic | Extension point |
|---|---|
| New item types / fields / workflows | Template YAML; `semantics` for engine features |
| New guards / effects | `KNOWN_GUARDS` / `KNOWN_EFFECTS` in the metamodel + engine functions |
| New inbound integrations | `integrations/service.py` handler + router endpoint; `ExternalRef` model |
| Outbound consumers | Outbox events (`item.*`, `link.*`, `approval.requested`, `baseline.created`) |
| File storage backends | `items/storage.py` (store / blob_path / exists) |
| Authentication | `core/deps.py` (add OIDC provider resolving to `User`) |

## 6.3 Roadmap

**Next increment (0.2) — collaboration & exchange**
- Document branches with "branched from" links and 3-way merge (ADR-0011)
- ReqIF import with attribute mapping; Word/PDF export of documents
- Saved queries and dashboards per project; KPI reports (reuse rate per module, re-test effort, change lead time)
- E-mail notifications (assignments, approvals)

**0.3 — enterprise readiness for SMEs**
- SSO via OIDC (Microsoft Entra ID, Keycloak), groups → roles
- Effectivity on change orders (date / serial number)
- Visual template editor; template versioning and migration helpers
- S3-compatible file storage; scheduled backups

**0.4 — digital thread**
- SysML v2 API connector (link items to model elements, e.g. SysON)
- GitLab and Jira connectors; PDM/CAD connector (metadata sync of released documents)
- OSLC provider for requirements and change requests
- SBOM import (CycloneDX/SPDX) as document items for CRA evidence

**0.5 — assisted engineering (governed AI)**
- Requirement quality checks (INCOSE rules), duplicate detection, test case suggestions
- Change impact summaries — always as proposals through the API, with audit entries and normal approvals
