# 5 Architecture

## 5.1 Context

```mermaid
flowchart LR
    U[Engineers, reviewers, managers<br/>browser] --> A
    CI[CI/CD pipelines<br/>API token] -->|JUnit XML, REST| A
    GH[GitHub / GitLab] -->|webhooks| A
    ADO[Azure DevOps] -->|service hooks| A
    A[Ariadne] -->|signed webhooks| EXT[Teams, ERP, custom systems]
    A -->|ReqIF, CSV, Excel| PART[Customers / suppliers / other ALM tools]
    A --- DB[(PostgreSQL)]
    A --- FS[(File store volume)]
```

## 5.2 Runtime view

One application container (Python, FastAPI) serves the REST API under `/api/v1`, the OpenAPI documentation and the
single-page frontend; a PostgreSQL container stores all data. Files live in a content-addressed volume.

```
┌──────────────────────── app container ────────────────────────┐
│  Uvicorn / FastAPI                                             │
│   ├─ /api/v1/*      REST API (OpenAPI at /api/v1/docs)          │
│   ├─ /hooks/*       inbound integrations (shared-secret auth)   │
│   ├─ /*             React SPA (static build)                    │
│   └─ outbox worker  delivers domain events to webhooks          │
└─────────────────┬──────────────────────────────┬──────────────┘
                  │ SQLAlchemy (psycopg 3)        │ /data volume
           ┌──────▼──────┐                 ┌──────▼──────┐
           │ PostgreSQL  │                 │ files/ab/cd │
           └─────────────┘                 └─────────────┘
```

Start-up: wait for the database → `alembic upgrade head` → bootstrap the first administrator → (optional demo data)
→ start the outbox worker and the Git sync worker.

**Deployment topologies.** The same image runs either with Docker Compose on a machine of your own (PostgreSQL as a
second container, `/data` as a volume, TLS from a reverse proxy) or as a single managed container with a managed
database and a mounted attachment directory — on Azure Container Apps with Entra ID sign-on, pinned to one replica
([ADR-0033](adr/0033-managed-hosting-on-container-apps.md), [18](18-azure-container-apps.md), and the deployment
architecture section of the README). Only `/data/files` has to be durable; Git mirrors, the connector cache and
temporary uploads are rebuilt.

## 5.3 Building blocks (modular monolith)

```
backend/almlight/
  core/            config, database, errors, security, auth dependencies, shared schemas, i18n (server texts)
  modules/
    projects/      projects, members, roles, information model (metamodel + templates)
    identity/      users, sessions, API tokens, bootstrap admin
    items/         items, versions, revisions, fields, attachments, comments, search
    links/         links, suspect propagation, structure, impact analysis, trace matrix
    workflow/      workflow engine, guards, effects, approvals, e-signatures
    baselines/     snapshots, compare
    variants/      expressions (parser), feature model, validation, 150% resolve
    verification/  test records, JUnit import, verification status, coverage, maturity
    io/            CSV/Excel, ReqIF export/import, Word/PDF rendering, project archive
    reports/       user-defined reports (widgets), KPI calculations, templates
    branches/      document branches and 3-way merge
    integrations/  external refs, GitHub / Azure DevOps hooks, outbound webhooks, outbox
    audit/         hash-chained audit trail
    notifications/ watching, recipients from audit entries, per-transaction buffer, e-mail digests
    queries/       saved (shared) views over the item list
    boards/        Kanban board definitions (items via the query engine in items/query.py)
    risks/         risk matrix and register (FMEA) over risk items
    planning/      plan hierarchy, capacity, burn-up/down; timeline (schedule.py: calendar, dependency types, slack,
                   auto-scheduling, levelling); resource load
    worklog/       time records, timesheet, spent/remaining effort
    vcs/           Git repositories: bare mirrors (git CLI), commit index, linked revisions, browsing, branches
    connectors/    connector framework (neutral model + import pipeline): Enterprise Architect, medini analyze,
                   SysML v2 API
    bom/           multi-level BOM, effectivity, roll-up, exports, where-used
    files/         file check-out / check-in locks
    doctemplates/  customer Word templates (storage; rendering in io/word_template.py)
    collab/, live/ co-editing rooms (Yjs) and the live channel (changes, presence, notifications)
  locales/         server message catalogues (de.json)
  seed/            demo dataset
frontend/src/      React + TypeScript (Mantine UI, TanStack Query); lib/i18n.ts + locales/ for the interface language
```

Each module has `models.py` (SQLAlchemy), `service.py` (domain logic, transactions boundaries are the request),
`router.py` (HTTP + Pydantic schemas). Routers call services; services call other modules' services, never their
routers. Every mutation writes its audit entry and outbox event **in the same transaction**.

## 5.4 Key technical decisions

See the [ADRs](adr/). In short:

| Topic | Decision |
|---|---|
| Style | Modular monolith, API-first ([ADR-0001](adr/0001-modular-monolith-fastapi.md)) |
| Storage | PostgreSQL only: JSONB fields, full-text search, recursive queries ([ADR-0002](adr/0002-postgresql-only.md)) |
| Versioning | Immutable item versions with revision/iteration ([ADR-0003](adr/0003-immutable-item-versions.md)) |
| Configuration | Process templates as data + semantics ([ADR-0004](adr/0004-configurable-metamodel.md)) |
| Traceability | Typed links owned by the source, suspect on target change ([ADR-0005](adr/0005-typed-links-suspect.md)) |
| Baselines | Explicit snapshots with revision rules ([ADR-0006](adr/0006-baselines-as-snapshots.md)) |
| Change | CMII-light, release via change order ([ADR-0007](adr/0007-cmii-light-change.md)) |
| Variants | Features as items + applicability expressions ([ADR-0008](adr/0008-variants-150-model.md)) |
| Delivery | One image, SPA served by the API, Docker-only toolchain ([ADR-0009](adr/0009-single-image-delivery.md)) |
| Hosting | Compose on your own machine, or one managed container (one replica) with managed PostgreSQL ([ADR-0033](adr/0033-managed-hosting-on-container-apps.md)) |
| Security | Local users, cookie sessions, API tokens, OIDC single sign-on ([ADR-0010](adr/0010-authentication.md), [ADR-0024](adr/0024-single-sign-on-oidc.md)) |
| Branching | Change-scoped revisions now; document branches later ([ADR-0011](adr/0011-branching-strategy.md)) |
| Integration | Webhooks in/out, external refs, outbox ([ADR-0012](adr/0012-integration-strategy.md)) |
| Audit | Hash-chained audit trail ([ADR-0013](adr/0013-hash-chained-audit.md)) |
| Reports | Widget lists evaluated on the server, KPI module ([ADR-0014](adr/0014-user-defined-reports.md)) |
| Documents & ReqIF | python-docx/ReportLab rendering, ReqIF import identity ([ADR-0015](adr/0015-document-rendering-and-reqif-import.md)) |

## 5.5 Security

- Passwords hashed with Argon2; minimum length; same error and same effort for unknown user and wrong password;
  failed sign-ins are limited per user name and client address, recorded in the audit trail and answered with 429.
- Browser sessions: signed JWT in an httpOnly, SameSite=Lax cookie (`Secure` behind HTTPS); API: personal access
  tokens (`Bearer alm_…`), stored as SHA-256 hashes, revocable, expiring.
- Authorisation: project membership with roles viewer < contributor < reviewer < manager; administrators act as
  managers. Non-members get 404 (projects are not enumerable).
- Security headers on every response (CSP `default-src 'self'`, `frame-ancestors 'none'`, nosniff, referrer policy);
  `Cache-Control: no-store` on the API.
- Rich text is sanitised to one canonical HTML model (no XSS through descriptions); uploaded files are served as
  attachments — only raster images (sandboxed CSP) and PDFs can be shown inline; SVG always downloads.
- Single sign-on: OIDC code flow with PKCE, ID token verified against the issuer's JWKS (signature, issuer, audience,
  expiry, nonce). Word templates are size/zip-bomb checked; macro-enabled files are refused.
- Inbound webhooks: HMAC-SHA256 signature (GitHub) or shared secret (Azure DevOps), constant-time comparison.
  Outbound webhooks are signed with a per-hook secret. Secrets are generated by the server and shown once.
- XML input (JUnit) is parsed with `defusedxml`; uploads are size-limited and streamed.
- No secrets in the repository: configuration via environment variables / `.env` (gitignored); the session key is
  generated and persisted in the data volume if not supplied.

## 5.6 Quality and testing

- Backend: 190+ pytest tests against a real PostgreSQL (migrations applied by Alembic), covering API flows and
  negative cases (permissions, frozen states, validation, conflicts, signature failures, tampering detection).
- Frontend: strict TypeScript; Playwright browser tests (login, item lifecycle, approvals with e-signature,
  traceability, documents, structure, variants, baselines, permissions) run against a fresh stack with demo data.
- Lint: ruff. Everything runs in Docker (`compose.test.yaml`).

## 5.7 Scalability and limits

The MVP targets teams of up to a few dozen users and tens of thousands of items per installation:

- Audit writes are serialised by an advisory lock (linear hash chain) — fine for SME write volumes.
- Recursive queries (impact, trees, cycles) are bounded by depth and use indexed link columns.
- Horizontal scaling is possible (stateless app; the outbox worker uses `SKIP LOCKED`), but not needed initially.
- Files are de-duplicated by content hash; large binary CAD data should stay in the PDM system and be referenced.
