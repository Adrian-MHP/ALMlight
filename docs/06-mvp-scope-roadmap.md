# 6 MVP scope and roadmap

## 6.1 Implemented (v0.1 MVP, 0.2 – 0.5 increments)

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

**Branching & merging (0.2)**: branch a document (sub-tree copy with outline and traces), field-level 3-way merge
preview against a git-like merge base, merge into the source or update the branch from the source, conflict
resolution per field, new branch items created in the source, lifecycle rules enforced

**Variants**: feature model (mandatory/optional, alternative/or groups), requires/excludes, variants with validation,
applicability expressions on items and links, configurator (150% → 100%)

**Verification**: test runs and records pinned to versions, JUnit XML import from CI, verification status with
re-test detection, maturity per element (specified / realised / verified / validated)

**Integration & exchange**: REST API with OpenAPI docs, personal API tokens, GitHub and Azure DevOps inbound
webhooks, manual external references (CAD/PDM/URL), outbound signed webhooks via transactional outbox,
CSV/Excel export and import (dry run, all-or-nothing), ReqIF 1.2 export, full project archive (export/import)

**Reports & KPIs (0.2)**: user-built reports from widgets (KPI with target, chart, table, trend, coverage,
traceability matrix, maturity, text) with live preview, shared or private, templates, Excel export and print/PDF;
engineering KPIs: reuse rate per module, change lead time (incl. end-to-end request → release), re-test effort per
variant, module variants vs. offered variants; KPI JSON endpoints for BI tools

**Document output & ReqIF import (0.2)**: Word and PDF export of documents (live or from a baseline) with title page,
table of contents, attributes and traces; ReqIF import (.reqif/.reqifz) with mapping analysis, DOORS-style headings,
enumeration mapping, relations, and update-on-reimport identity (incl. round trips of own exports)

**Live documents (0.3)**: document history and time travel (open any change point or baseline, read-only, exact),
item version view, document comparison (revisions, baselines, branches, other documents, cross-project; word-level
diff, moves), Word round trip (review copy edit/comments-only, re-import with conflict detection and Word comments),
ReqIF export with partner identifiers, threaded document comments with resolve, document filter and variant
specifications, automatic heading numbering, reuse of existing items, recycle bin, collections of document baselines
(close/reopen, zip export). See [10-live-documents](10-live-documents.md).

**Collaboration & rich text (0.4)**: rich-text editor (formatting, lists, tables with merge/split, images by upload,
paste or drag & drop, `#` item references), real-time co-editing with live cursors, presence per document/item/block,
live refresh and change notifications, sessions saved as versions with co-authors (explicit, on leave, idle; crash-safe
drafts), rich text in Word/PDF/ReqIF (`.reqifz` with images)/Excel/archives, product name Ariadne with an industrial
design language (app launcher, workspace home, object headers). See [11-rich-text-and-co-editing](11-rich-text-and-co-editing.md).

**Engineering backbone (0.5)**: notifications (watch items and documents, owner, approval, @mentions; live toasts;
bulk changes collapse; e-mail digests), saved and shared views with traceability-gap filters and export of the current
view, computed fields (formulas, classification bands, bounds), test steps with step-wise execution and defects from
failed steps, risk management (FMEA, risk matrix before/after mitigation, mitigation links, acceptance with
e-signature), release planning (timeline, progress, schedule status, burn-up), multi-level BOM (quantities, units,
find numbers, date effectivity, roll-up, Excel/CSV) and where-used, file check-out/check-in with file revisions,
history and preview, Word export in customer templates, single sign-on via OIDC, additive template updates for
existing projects. See [12-engineering-backbone](12-engineering-backbone.md), the
[feature catalogue](13-feature-catalogue.md) and the [beta test report](14-beta-test-report.md).

**Operations**: two containers, automatic migrations, bootstrap admin, demo data switch, health check, SMTP and OIDC
configuration

## 6.2 Prepared but not built (extension points)

| Topic | Extension point |
|---|---|
| New item types / fields / workflows | Template YAML; `semantics` for engine features |
| New guards / effects | `KNOWN_GUARDS` / `KNOWN_EFFECTS` in the metamodel + engine functions |
| New inbound integrations | `integrations/service.py` handler + router endpoint; `ExternalRef` model |
| Outbound consumers | Outbox events (`item.*`, `link.*`, `approval.requested`, `baseline.created`) |
| File storage backends | `items/storage.py` (store / blob_path / exists) |
| Authentication | `identity/oidc.py` (further claims → roles mapping) |

## 6.3 Roadmap

**Next increment (0.6) — scale and comfort**
- Live sessions across several app processes (shared bus), comments anchored to text ranges
- German user interface (i18n of the whole UI), visual template editor, template versioning
- Effectivity on change orders (date / serial number), BOM substitutes and alternates
- Parametrised test runs and test run templates; capacity and effort planning
- Lookup-table computed fields (e.g. ISO 26262 ASIL determination); group → project role mapping for SSO
- Scheduled report e-mails; S3-compatible file storage; scheduled backups; PDF export in customer templates

**0.7 — digital thread**
- SysML v2 API connector (link items to model elements, e.g. SysON)
- GitLab and Jira connectors; PDM/CAD connector (metadata sync of released documents)
- OSLC provider for requirements and change requests
- SBOM import (CycloneDX/SPDX) as document items for CRA evidence

**0.8 — assisted engineering (governed AI)**
- Requirement quality checks (INCOSE rules), duplicate detection, test case suggestions
- Change impact summaries — always as proposals through the API, with audit entries and normal approvals
