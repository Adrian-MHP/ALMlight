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

![Query builder, bulk edit and preview pane](docs/images/query.png)

![Kanban board: drag a card to run the workflow transition](docs/images/board.png)

![Timeline with critical path, conflict and schedule baseline](docs/images/timeline.png)

![Risk matrix and FMEA register](docs/images/risks.png)

![Multi-level bill of materials with effectivity](docs/images/bom.png)

![Planning board: backlog and iterations with capacity](docs/images/planning.png)

![Resource load per person and week, with levelling](docs/images/resources.png)

![German user interface](docs/images/german.png)

![Code: a commit linked to its requirement, with the diff](docs/images/code.png)

![Enterprise Architect import: mapping wizard with preview](docs/images/connectors.png)

## Highlights

- **Live co-editing**: several people edit the same text at the same time with live cursors and names; presence
  shows who is in a document and who edits which block; pages refresh themselves when others save. Sessions are
  saved as ordinary versions with co-authors (explicitly, when the last editor leaves, or after idle time).
- **Rich text**: formatting, headings, lists, quotes, code, links, tables (merge/split cells), images by upload, paste
  or drag & drop, and `#` item references — identical in the editor, Word, PDF, ReqIF (`.reqifz`) and Excel.
- **Configurable information model**: item types, fields (also computed: formulas and classification bands), link
  types and workflows are defined in process templates (YAML), so each customer gets their own model without code
  changes; new template capabilities are taken over into existing projects additively.
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
- **Verification**: test cases with steps, step-by-step execution with actual results, defects from failed steps,
  test runs pinned to versions, JUnit import from CI, re-test detection, and maturity per system element
  (specified / realised / verified / validated).
- **Risk management (FMEA)**: severity, occurrence, detection, computed RPN and risk level, risk matrix before and
  after mitigation, mitigation traceability and residual-risk acceptance with e-signature.
- **Queries like Polarion**: query builder with chips for any field, link, date, user or plan (*is / is not*,
  Any/None, periods), OR/AND groups across fields with NOT, a query language to copy, paste and edit, configurable
  columns incl. custom fields, sorting, a preview pane, and saved views with their columns.
- **Bulk edit**: select rows or the whole result and edit fields or owner, change the status, plan, link, watch or
  delete — with a per-item preview of what will change and what is skipped and why.
- **Kanban boards**: any items, columns and swimlanes by status, owner, plan, type or field, WIP limits; dragging a
  card runs the real workflow transition (with comment or e-signature when required).
- **Plans**: releases with iterations and milestones, estimates against capacity, burn-up and burn-down, and a
  planning board to drag work from the backlog into iterations.
- **Timeline (Gantt)**: tasks, milestones and plans with finish-to-start, start-to-start, finish-to-finish and
  start-to-finish dependencies with lag, critical path, scheduling conflicts and schedule-baseline comparison; drag
  bars to reschedule, or auto-schedule along the dependencies with a preview.
- **Time and resources**: record hours on items, a weekly timesheet with spent and remaining effort, resource load
  per person and week against capacity, and resource levelling with a preview.
- **Code (Git) like Polarion**: connect GitHub, GitLab, Bitbucket, Azure Repos or any Git server; commits that
  mention an item key become linked revisions of the item (or are linked by hand); a repository browser with
  commits, diffs, files and branches; GitHub pull requests; a branch per item in one click.
- **Connectors**: Enterprise Architect (import `.qea`/XMI with mapping and GUID identity, export EA XMI, write back
  into the `.qea`), medini analyze (HARA with ISO 26262 ASIL and FMEA both ways, safety requirements via ReqIF) and
  SysML v2 servers (SysON, Cameo) — every import previewed, repeatable, conflicts reported instead of overwritten.
- **English and German**: the whole interface, the labels of the information model (translated per customer),
  server messages, notifications, e-mail digests and document exports follow the user's language.
- **Workflow viewer**: every item shows its state diagram with the path taken and the transitions possible now.
- **Bill of materials**: multi-level BOM with quantities, units, find numbers, date effectivity, rolled-up totals,
  Excel/CSV export and where-used across projects.
- **File management**: check-out/check-in with file revisions, revision history and preview; items with
  checked-out files cannot be released.
- **Notifications**: watch items and documents, @mentions, owner and approval notifications, live toasts and e-mail
  digests; bulk changes collapse into one summary.
- **Saved views**: personal and shared filters, traceability-gap filters (unverified, unallocated, unmitigated,
  unplanned) and export of exactly the current view.
- **Reports & KPIs**: end users build their own reports from KPI, chart, table, trend, coverage, matrix and
  maturity widgets, plus engineering KPIs: reuse rate per module, change lead time, re-test effort per variant and
  module variants vs. offered variants. Reports export to Excel and print to PDF; KPIs are also available as JSON.
- **Documents out & in**: Word and PDF export of documents, either live or exactly as frozen in a baseline, Word
  also in the customer's own corporate template. ReqIF import with a mapping wizard; re-importing an updated file
  updates the existing items instead of duplicating them.
- **Integration**: REST API (OpenAPI), API tokens, GitHub and Azure DevOps webhooks, signed outbound webhooks,
  CSV/Excel import/export, ReqIF export/import, and full project archives.
- **Compliance & identity**: hash-chained audit trail with verification, role-based access, single sign-on via
  OpenID Connect (Microsoft Entra ID, Keycloak), and secure defaults.

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

## Deployment architecture

Ariadne ships as **one image**: the Dockerfile builds the React bundle with Node and copies it into the Python
image, so a single container serves the REST API, the OpenAPI documentation, the WebSocket endpoints and the
single-page frontend. It runs as a non-root user (uid 10001) and listens on port 8000. Only two things live
outside it: **PostgreSQL** and a **directory for attachments**. Everything below follows from that.

### On your own infrastructure

`docker compose up -d` starts the app container plus PostgreSQL 16 and keeps `/data` in a named volume. For
production put a reverse proxy with TLS in front (Traefik, nginx, Caddy, IIS/ARR); it has to forward the WebSocket
upgrade and the original host — see [operations](docs/08-operations.md) §8.8.

### On Azure (Container Apps)

The managed alternative, used for the first shared installation. Step-by-step commands:
[Azure Container Apps](docs/18-azure-container-apps.md).

```
                         Entra ID (OpenID Connect, assignment required)
                              ▲ code flow with PKCE, ID token via JWKS
                              │
Browser ──https (443)──▶ Container Apps ingress ──http (8000)──▶ ariadne container  ◀── image: Container Registry
  REST · WebSockets        TLS terminated here,                  1 replica (min=max=1)        (built from this repo)
                           X-Forwarded-* added                   0.5 vCPU / 1 GiB
                                                                     │        │
                                        SQLAlchemy (psycopg 3)       │        │  SMB mount
                                        sslmode=require              ▼        ▼
                                              ┌──────────────────────────┐  ┌──────────────────────┐
                                              │ PostgreSQL Flexible      │  │ Azure Files share    │
                                              │ Server (B1ms, "almlight")│  │ mounted /data/files  │
                                              └──────────────────────────┘  └──────────────────────┘
                 outbound: Git over HTTPS · GitHub API · SysML v2 server · SMTP · signed webhooks
                 logs: Log Analytics workspace of the Container Apps environment
```

**Resources and why each one is there**

| Resource | SKU in the first installation | Role |
|---|---|---|
| Container Apps environment + app | Consumption, 0.5 vCPU / 1 GiB, 1 replica | Runs the image, terminates TLS, gives the `https://<app>.<env>.<region>.azurecontainerapps.io` name |
| PostgreSQL Flexible Server | Burstable B1ms, 32 GB | All data: items, versions, links, audit trail, commit index, co-editing drafts |
| Storage account + file share | Standard_LRS, 20 GB | Attachments and file revisions, mounted at `/data/files` |
| Container Registry | Basic | The image; `az acr build` builds it in Azure from the public repository (no local Docker, no ARM/x86 problem) |
| Entra ID app registration | — | Single sign-on; *Assignment required* decides who may sign in |
| Log Analytics workspace | created with the environment | Container logs (`az containerapp logs show`) |

**The request path.** The ingress terminates TLS with its own certificate and forwards to port 8000. Uvicorn runs
with `--proxy-headers`, so the application reads scheme and host from `X-Forwarded-*`: session cookies are marked
`Secure` (`ALMLIGHT_COOKIE_SECURE=true`), the single-sign-on redirect uses `ALMLIGHT_PUBLIC_URL`, and the
Content-Security-Policy names the public host for the two WebSocket endpoints (`/api/v1/live` for change events and
presence, `/api/v1/collab/items/{id}` for co-editing). Container Apps passes WebSockets through; the browser pings
every 25 s to keep idle connections open. Cross-site WebSocket connections are refused by comparing the `Origin`
header with the forwarded host.

**Why exactly one replica.** Live co-editing rooms, presence and the two background workers (outbound webhooks and
e-mail digests, Git fetch every `ALMLIGHT_GIT_SYNC_MINUTES`) all run inside the application process. A second
replica would hold a second set of editing rooms, and scaling to zero would stop the workers. The app is
otherwise stateless — sessions are signed JWTs in a cookie, not a server-side store, so a restart does not sign
anyone out as long as `ALMLIGHT_SECRET_KEY` stays the same.

**What lives where**

| Place | Content | After a restart |
|---|---|---|
| PostgreSQL | Items, versions, links, baselines, audit trail, indexed commits, unsaved co-editing drafts | Kept; `alembic upgrade head` runs at every start, and interrupted editing sessions are saved as versions |
| `/data/files` (Azure Files) | Attachments and file revisions, content-addressed as `files/ab/cd/<sha256>` | Kept — this is the one directory that must be mounted |
| `/data/vcs` | Bare Git mirrors of connected repositories | Fetched again (the commit index in the database stays) |
| `/data/repos-local` | The demo firmware repository | Written again at start with identical commit hashes |
| `/data/connector-cache`, `/data/tmp` | SysML model cache (1 h), uploaded EA models while parsing | Rebuilt on demand |
| `/data/secret_key` | Generated session key when `ALMLIGHT_SECRET_KEY` is unset | **Set the variable instead** — the key also encrypts stored Git and SysML tokens |
| Process memory | Editing rooms, presence, failed-sign-in counters | Lost by design |

**Identity and secrets.** Colleagues sign in with their company account through Entra ID (OIDC code flow with
PKCE, ID token verified against the issuer's JWKS); local accounts keep working, with sign-in attempts limited per
user name and client address. The database URL, session key, administrator password and the OIDC client secret are
Container Apps secrets referenced as `secretref:`; nothing sensitive is in the image or this repository. Tokens for
Git and SysML servers are entered in the application and stored encrypted with the session key.

**Limits to plan around.** The ingress ends a request after about four minutes, so very large imports can fail
there; attachments sit on an SMB share, not on Blob storage; the database firewall starts open to Azure services
and should be narrowed before sensitive project data arrives; and electronic signatures still need a local account
(they verify the user's own password). Rough cost of the setup above: 35–50 € per month — check the Azure price
calculator.

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
| [Engineering backbone](docs/12-engineering-backbone.md) | Notifications, views, computed fields, tests, risks, plans, BOM, files, Word templates, SSO |
| [Work management](docs/15-work-management.md) | Query builder and language, bulk edit, boards, plans, timeline, workflow viewer |
| [Feature catalogue](docs/13-feature-catalogue.md) | Ariadne compared with Polarion/Teamcenter capability areas |
| [Beta test report](docs/14-beta-test-report.md) | Method, findings and fixes, permission matrix, load test |
| [Languages](docs/16-languages.md) | German and English interface, translated models, server texts |
| [Code and connectors](docs/17-code-and-connectors.md) | Git repositories, linked revisions, Enterprise Architect, medini analyze, SysML v2 |
| [Azure Container Apps](docs/18-azure-container-apps.md) | Running Ariadne in an Azure resource group with company sign-in |
| [Architecture decisions](docs/adr/README.md) | ADR-0001 … ADR-0033 |

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
docker compose -f compose.test.yaml run --rm backend-tests                      # 195 API/unit tests
docker compose -f compose.test.yaml up -d --build app && \
docker compose -f compose.test.yaml run --rm e2e                                 # 53 browser E2E tests
docker compose -f compose.test.yaml down
```

## Status

Version 0.8 (0.8.1/0.8.2: sign-in protection, projects open to every signed-in user, running on Azure Container Apps — [guide](docs/18-azure-container-apps.md)): Git interface (linked revisions, repository browser) and connectors to Enterprise Architect, medini
analyze and SysML v2 servers ([guide](docs/17-code-and-connectors.md), sample files in `samples/`) — on top of 0.7
(boolean queries, dependency types and auto-scheduling, time recording, resources and levelling, German user
interface), 0.6 (query builder and
query language, bulk edit, Kanban boards, plans with capacity, Gantt timeline with critical path, workflow viewer),
0.5 (tests, risks, BOM, files, notifications, Word templates, SSO)
and 0.4 (rich text, real-time co-editing, live documents with time travel, branches, reports, Word/ReqIF round trips).
How it compares with Polarion and Teamcenter: [feature catalogue](docs/13-feature-catalogue.md). Next increments:
[roadmap](docs/06-mvp-scope-roadmap.md).
