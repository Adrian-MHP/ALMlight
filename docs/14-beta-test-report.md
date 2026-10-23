# 14 Beta test report (0.4 → 0.5)

Two beta rounds were run against the complete application in Docker (`compose.test.yaml`: PostgreSQL 16, the
production image with demo data, Playwright/Chromium), in addition to the automated suites. Round 1 finalised 0.4
(rich text, co-editing, new UI); round 2 tested the engineering-backbone features of 0.5.

## 14.1 Method

| Technique | What was done |
|---|---|
| Page crawler | Every page and every tab, opened as manager, contributor, reviewer, viewer and administrator; light and dark theme; desktop (1440×900) and phone (390×844, touch); dialogs, drawers and menus opened; console errors, page errors and failed HTTP calls recorded; full-page screenshots reviewed by hand |
| Journeys | Scripted end-to-end flows per persona (engineer, reviewer, manager, viewer) — kept as the E2E suite |
| Permission matrix | 20 actions of the new features × 5 roles (viewer, non-member, contributor, reviewer, manager) against the running server |
| Load test | Project with a 1,561-item specification, 300 risks, 10 releases × 150 planned items, a 541-line multi-level BOM with a part used in 20 assemblies, a watcher on the large specification |
| Interoperability | Word exports (standard layout, corporate template, round-trip review copy) opened and converted by LibreOffice 7.4 headless; rendered pages checked |
| Automated suites | Backend API/unit tests against PostgreSQL and the browser E2E suite after every fix |

## 14.2 Round 1 — 0.4 finalisation

- **Crawler**: 128 page states, 0 JavaScript errors (only intended 404s).
- **UI findings fixed**: header overflow on phones, Kanban columns cut off, document page too wide on phones,
  unclear error for a baseline without the document, indentation of nested blocks growing quadratically.
- **Performance** (1,560 items, before → after batch loading of snapshots and lighter rendering):

| Operation | Before | After |
|---|---|---|
| Document snapshot | 1,047 ms | 127 ms |
| Baseline snapshot | 341 ms | 91 ms |
| Compare baseline ↔ live | 944 ms | 337 ms |
| Document render in the browser | 3.2 s | 0.55 s |
| CSV import of 1,561 items | – | 5.4 s |

## 14.3 Round 2 — engineering backbone (0.5)

### Crawler

235 page states (5 roles, dark theme, phone), **0 JavaScript errors**; the only failed requests were the intended
404s (a baseline that does not contain the opened document, a project that does not exist).

### Findings and fixes

| # | Finding | Kind | Fix |
|---|---|---|---|
| 1 | A @mention made inside a document opened the document instead of the commented requirement | bug | Notifications point to the changed item, else the first related item |
| 2 | A test record accepted several "create defect" calls, creating duplicates | bug | One defect per record (409 with the existing key); UI unchanged |
| 3 | Import that only added links reported the rows as *unchanged* | bug | Rows count as *updated*; summary shows the number of links |
| 4 | SSO users with e-mail-like names (Entra ID UPN) could not be @mentioned | bug | Mention syntax accepts `@name@domain` |
| 5 | Status badges truncated to "MITIG…", "ON T…" in narrow tables and cards | UI | Badges keep their width in tables; release cards re-arranged |
| 6 | Wide tables (risk register, BOM, files, plan items, test steps, records) clipped on phones | UI | Horizontal scrolling inside the card |
| 7 | Timeline month labels overlapping on phones; no month axis on desktop | UI | Month axis, labels thinned to the measured width |
| 8 | Read-only test execution looked like disabled inputs without explanation | UI | Plain values and a reason ("The run is completed — its results are locked") |
| 9 | Risk matrix colour ignored detection (an RPN-high risk sat in a yellow cell) | UI | Count bubble coloured by the worst RPN level in the cell |
| 10 | Burn-up without legend and today marker | UI | Legend and today line |
| 11 | Where-used quantity placed after the parent (ambiguous) | UI | Quantity shown before the child, with tooltip |
| 12 | Item export always exported the whole type, not the filtered list | gap | Export delivers the current view (all pages) |
| 13 | Defect raised before saving the step results lacked the actual result | UI | Results are stored first, then the defect is created |
| 14 | Planning picker offered already planned items | UI | Excluded |

### Permission matrix

| Action | Viewer | Non-member | Contributor | Reviewer | Manager |
|---|---|---|---|---|---|
| Read risks, plans, BOM, where-used, file history, templates | 200 | 404 | 200 | 200 | 200 |
| Export current view, BOM CSV | 200 | 404 | 200 | 200 | 200 |
| Edit BOM quantity | 403 | 404 | 200 | 200 | 200 |
| Plan an item into a release | 403 | 404 | 201 | 409 (already planned) | 409 |
| Record step results | 403 | 404 | 200 | 200 | 200 |
| Raise a defect (once per record) | 403 | 404 | 201 | 409 | 409 |
| Check out a file held by someone else | 403 | 404 | 200 (holder) | 409 | 409 |
| Cancel someone else's check-out | 403 | 404 | – | 403 | 200 |
| Upload a Word template | 403 | 404 | 403 | 403 | 201 |
| Share a saved view | 403 | 404 | 201 | 201 | 201 |
| Watch an item | 200 | 404 | 200 | 200 | 200 |
| Take over template updates | 403 | 404 | 403 | 403 | 200 |

100 checks, **0 unexpected** (after fix #2).

### Load test

| Operation | Result |
|---|---|
| Import 300 risks with mitigation links | 1.0 s |
| Plan 1,500 items into 10 releases (one import; large spec watched) | 3.2 s — the watcher received **one** summary notification instead of 1,500 |
| Import a 522-element BOM | 2.3 s |
| Risk register with matrix (300 risks) | 7 ms |
| Plans overview (10 releases) / plan detail with burn-up (150 items) | 21 ms / 7 ms |
| Multi-level BOM, 541 lines / as Excel | 138 ms / 156 ms |
| Where-used of a part in 20 assemblies | 14 ms |
| Gap filter (unverified / unplanned requirements) | 5 ms |
| Export current view, 1,500 rows CSV | 130 ms |
| Document snapshot, 1,561 items | 135 ms |
| Word export, 1,561 items: standard / corporate template | 4.0 s / 3.9 s |
| PDF export, 1,561 items | 4.0 s |

### Interoperability

LibreOffice converted the standard export, the corporate-template export and the round-trip review copy without
errors. The template export shows the cover page without header, the template's header and footer with project,
title, version, state, date and page number, the table of contents and the document content at the marker.

## 14.4 Automated tests at the end of round 2

| Suite | Result |
|---|---|
| Backend API/unit tests (PostgreSQL) | 153 passed, lint clean |
| Browser E2E (Playwright) | 40 passed — incl. notifications, mentions, saved views, export, test execution with defect, risks with live RPN, plans, BOM with effectivity and export, where-used, file check-out/check-in, Word templates, SSO visibility |
| Smoke crawl in the E2E suite | all pages and tabs, three roles, dark and phone |

## 14.5 Known limitations

- Live editing sessions and live updates run in one application process (single app container).
- The user interface is in English; German is on the roadmap.
- PDF export uses the standard layout; corporate templates apply to Word.
- E-mail digests were tested with a simulated SMTP server, single sign-on with a simulated identity provider
  (discovery, JWKS, signed tokens, PKCE) — a check against the customer's mail server and Entra ID/Keycloak tenant
  belongs to the installation.
- The demo data is created in one go, so the demo burn-up shows a single step.
- Out of scope by design: manufacturing BOM/bill of process, CAD-authoring integrations, multi-site replication.
