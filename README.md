# Ariadne

**The engineering thread for small and medium-sized engineering companies — a configurable ALM/PLM backbone for
requirements, architecture, verification, documents, variants and change.**

Ariadne connects requirements, architecture, verification, documents, variants and changes in one versioned,
traceable and auditable system. It adopts the proven concepts of enterprise suites (live documents, suspect links,
revisions and maturity states, closed-loop change management, baselines, feature-based variants) and delivers
them in two containers, without enterprise licence and operating costs. *(Repository and technical code name:
ALMlight.)*

![Workspace home](docs/images/home.png)

![Two engineers editing the same requirement live](docs/images/coediting.png)

![Live document](docs/images/document.png)

![Compare a baseline with the live document](docs/images/compare.png)

## Highlights

- **Live co-editing**: several people edit the same text at the same time with live cursors and names; presence
  shows who is in a document and who edits which block; pages refresh themselves when others save. Sessions are
  saved as ordinary versions with co-authors (explicitly, when the last editor leaves, or after idle time).
- **Rich text**: formatting, headings, lists, quotes, code, links, tables (merge/split cells), images by upload, paste
  or drag & drop, and `#` item references — identical in the editor, Word, PDF, ReqIF (`.reqifz`) and Excel.
- **Configurable information model**: item types, fields, link types and workflows are defined in process templates
  (YAML), so each customer gets their own model without code changes.
- **Full history**: immutable versions (`A.1, A.2 … B.1`), diff and restore. Released revisions are frozen and
  changed through *Revise*.
- **Traceability**: typed links with rules, suspect links when a linked item changes, impact analysis, a trace
  matrix and coverage from stakeholder needs to test results.
- **Live documents**: specifications assembled from individually versioned items, with a release guard.
- **Workflows and approvals**: configurable lifecycles, approvals by role with the four-eyes rule and electronic
  signatures, and an approval inbox.
- **Change management**: problem report → change request (CCB) → change order. Change-controlled revisions, and
  releasing the change order releases its affected items.
- **Baselines**: of a whole project or one document or structure, using latest or released revisions, with compare.
- **Branching & merging**: branch a document for a variant or release and merge it back with a field-level 3-way
  merge in either direction.
- **Live documents with time travel**: open any document exactly as it was at any change point or baseline, open any
  item version, and compare revisions, baselines, branches or other documents side by side with word-level
  differences. Also: Word round trip (reviewers edit and comment in Word, changes and comments come back), threaded
  comments, variant-specific views, automatic numbering, reuse, recycle bin and release collections.
- **Variants**: feature model with constraints, product variants, and applicability expressions on items and links,
  plus a configurator.
- **Verification**: test runs pinned to versions, JUnit import from CI, re-test detection, and maturity per system
  element (specified / realised / verified / validated).
- **Reports & KPIs**: end users build their own reports from KPI, chart, table, trend, coverage, matrix and
  maturity widgets, plus engineering KPIs: reuse rate per module, change lead time, re-test effort per variant and
  module variants vs. offered variants. Reports export to Excel and print to PDF; KPIs are also available as JSON.
- **Documents out & in**: Word and PDF export of documents, either live or exactly as frozen in a baseline. ReqIF
  import with a mapping wizard; re-importing an updated file updates the existing items instead of duplicating them.
- **Integration**: REST API (OpenAPI), API tokens, GitHub and Azure DevOps webhooks, signed outbound webhooks,
  CSV/Excel import/export, ReqIF export/import, and full project archives.
- **Compliance**: hash-chained audit trail with verification, role-based access, and secure defaults.

## Quick start

Requirements: Docker with Compose.

```bash
cp .env.example .env            # set POSTGRES_PASSWORD, ALMLIGHT_ADMIN_PASSWORD; ALMLIGHT_DEMO_DATA=true for the demo
docker compose up -d --build
```

Open <http://localhost:48080>. Sign in as `admin` with the password from `.env`; if it was left empty, the
generated password is in `docker compose logs app`. With demo data enabled, the users `alex` (contributor),
`rita` (reviewer) and `max` (manager) share the password `demo1234` and work in the project **DEMO**, a generic
smart-sensor product platform.

API documentation: <http://localhost:48080/api/v1/docs>

## Documentation

| | |
|---|---|
| [Product concept](docs/01-product-concept.md) | Vision, delivery model, users, capability map |
| [Research & best practices](docs/02-research-best-practices.md) | How leading suites and standards solve it; where SE is heading |
| [Reference input analysis](docs/03-reference-input-analysis.md) | Generic conclusions from the first customer workshop |
| [Domain model](docs/04-domain-model.md) | Items, versions, links, lifecycle, change, baselines, variants, verification |
| [Architecture](docs/05-architecture.md) | Building blocks, runtime, security, quality |
| [MVP scope & roadmap](docs/06-mvp-scope-roadmap.md) | What is built, what is prepared, what comes next |
| [Configuration guide](docs/07-configuration-guide.md) | Tailoring process templates per customer |
| [Operations](docs/08-operations.md) | Install, configure, back up, upgrade, develop |
| [API & integrations](docs/09-api-and-integrations.md) | REST API, CI, GitHub, Azure DevOps, webhooks, formats |
| [Live documents](docs/10-live-documents.md) | Feature parity with enterprise live documents, time travel |
| [Rich text & co-editing](docs/11-rich-text-and-co-editing.md) | Editor, images, live sessions, saving, formats, operation |
| [Architecture decisions](docs/adr/README.md) | ADR-0001 … ADR-0020 |

## Technology

Python 3.12 · FastAPI · SQLAlchemy 2 · Alembic · PostgreSQL 16 · pycrdt (Yjs) · React 19 · TypeScript · Mantine ·
TipTap · Yjs · TanStack Query · Vite · Docker. All dependencies are permissively licensed.

```
backend/   API, domain modules, migrations, tests (pytest against PostgreSQL)
frontend/  single-page application
e2e/       browser tests (Playwright)
docs/      concept, architecture, guides, ADRs
```

## Tests

```bash
docker compose -f compose.test.yaml run --rm backend-tests                      # 130 API/unit tests
docker compose -f compose.test.yaml up -d --build app && \
docker compose -f compose.test.yaml run --rm e2e                                 # browser E2E tests
docker compose -f compose.test.yaml down
```

## Status

Version 0.4: the MVP foundation plus document branches, reports & KPIs, Word/PDF export, ReqIF and Word round trips,
live documents with history, time travel, comparison, comments and collections, and now rich text, real-time
co-editing, presence and the Ariadne workspace UI. See the [roadmap](docs/06-mvp-scope-roadmap.md) for planned
increments.
