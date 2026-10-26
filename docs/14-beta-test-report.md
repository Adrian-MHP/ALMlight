# 14 Beta test report (0.4 → 0.7)

Two beta rounds were run against the complete application in Docker (`compose.test.yaml`: PostgreSQL 16, the
production image with demo data, Playwright/Chromium), in addition to the automated suites. Round 1 finalised 0.4
(rich text, co-editing, new UI); round 2 tested the engineering-backbone features of 0.5; round 3 the
work-management features of 0.6 (query builder, bulk edit, boards, plans, timeline, workflow viewer); round 4 the
0.7 additions (boolean queries, dependency types and auto-scheduling, time recording, resources and levelling,
German user interface).

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

## 14.5 Round 3 — work management (0.6)

**Crawler**: 249 page states (incl. boards, timeline, task lists; dark theme; phone), 0 JavaScript errors.

| # | Finding | Kind | Fix |
|---|---|---|---|
| 1 | SQLAlchemy reports savepoint commits as commits: live events were published before the real commit and the notification buffer was lost in bulk runs | bug (latent since 0.4) | Commit hooks act only on the outermost commit; test for dry runs publishing nothing |
| 2 | Board configs stored with fewer keys crashed the board view | bug | API returns normalised configs; the board merges defaults; route-level error boundary keeps the shell usable |
| 3 | Timeline re-sorted rows while a bar was dragged; the moved DOM node lost the pointer and the drag ended | bug | Row order fixed during drags |
| 4 | A live refresh during a card drag could reset the board under the pointer | robustness | Card list frozen while dragging |
| 5 | Dropping a card on a column without transition did nothing visible | UI | Invalid columns dimmed while dragging; a drop explains why nothing happens |
| 6 | Progress by estimate showed 100 % when unestimated items were open | logic | Estimates count only when every planned item is estimated, otherwise items |
| 7 | Calendar-day slack hid the critical path across weekends | logic | Slack in working days |
| 8 | Timeline opened at the earliest date, not around today | UI | Opens around today |
| 9 | Workflow diagram too small in the side column; labels clipped | UI | Main column, natural size |
| 10 | Dragging selected page text | UI | Cards not selectable |

**Load test (1,561-item project)**

| Operation | Result |
|---|---|
| Query: type + priority + verification gap / text + period | 8 ms / 7 ms |
| Sort 1,500 requirements by a custom field | 6 ms |
| Board data, 1,000 cards | 25 ms |
| Export of a query result, 1,000 rows | 129 ms |
| Bulk edit of 500 items: preview / apply | 1.4 s / 1.2 s |
| Import of 200 tasks with 199 dependencies | 1.0 s |
| Timeline with 210 rows incl. critical path | 73 ms |

**Automated tests at the end of round 3**: 163 backend tests, 46 browser E2E tests (new: query builder and query
language, columns and sorting, bulk edit with preview, board drag & drop with transitions and comment prompt,
planning board, timeline with baseline, rescheduling and dependencies, workflow viewer).

## 14.6 Round 4 — scheduling, time, resources and German (0.7)

**Crawler**: all pages and tabs as manager, contributor and viewer; dark theme; a phone pass in **German**; plus a
German screenshot review of 15 main pages on desktop and phone — 0 JavaScript errors.

| # | Finding | Kind | Fix |
|---|---|---|---|
| 1 | After *OR …* turned a chip into a group, reopening the group showed the member editor instead of the member list | bug | The editor focus is reset whenever the chip closes |
| 2 | The automated marking of interface texts also caught identifiers (a co-editing field name, an editor node group, three comparisons, colour names, a test id) | review | Restored; the extraction rules exclude such positions; a build check now lists every text and its translation |
| 3 | Load test: every task of unplanned chains was critical — each chain was measured against its own finish | logic | Unplanned tasks are measured against the project finish (latest finish of all dated work), plan tasks against the plan due date, as in Schedule Manager/MS Project |
| 4 | German workflow diagram clipped longer transition labels ("Zur Prüfung einreichen") | UI | State boxes and gaps are sized from the labels |
| 5 | Resource heatmap: the colours for ≤ 60 % and ≤ 90 % looked the same | UI | Distinct shades |
| 6 | Hours shown as "32.5 h" in German; hour inputs used a decimal point | UI | Number format and decimal comma follow the language |
| 7 | Readers (viewer role) appeared as empty resource rows | UI | Only members who can do work are resources (readers only when they own tasks) |
| 8 | Item picker placeholder cut off in the timesheet | UI | Wider field |

**Permission matrix (0.7 endpoints)**

| Action | Viewer | Non-member | Contributor | Reviewer | Manager |
|---|---|---|---|---|---|
| Read item time (totals) | 200 | 404 | 200 | 200 | 200 |
| Record time | 403 | 404 | 201 | 201 | 201 |
| Change another person's record | 403 | 404 | 200 (own) | 403 | 200 |
| Own timesheet / set a cell | 200 / 403 | 404 | 200 | 200 | 200 |
| Another person's timesheet | 403 | 404 | 200 (own) | 403 | 200 |
| Resource load | 200 | 404 | 200 | 200 | 200 |
| Levelling / auto-schedule preview | 403 | 404 | 200 | 200 | 200 |
| Change a dependency type | 403 | 404 | 200 | 200 | 200 |
| Hours per day of a member | 403 | 404 | 403 | 403 | 200 |
| Query with OR group | 200 | 404 | 200 | 200 | 200 |
| Set own language | 200 | 200 | 200 | 200 | 200 |

65 checks, **0 unexpected**.

**Load test** (600 tasks in 30 chains with 570 dependencies — some start-to-start/finish-to-finish with lag —, 25
people, 1,500 requirements, 3,000 time records)

| Operation | Result |
|---|---|
| Timeline with 600 tasks (dependency types, slack, critical path) | 25 ms |
| Auto-schedule preview: resolve conflicts (434 moves) / as soon as possible (504 moves) | 1.1 s / 1.0 s |
| Resource load, 12 / 26 weeks | 32 ms / 56 ms |
| Levelling preview / apply (583 moves) | 2.1 s / 2.1 s |
| Record a time entry | 4.8 ms |
| Item time tab / resource load with actuals | 5 ms / 33 ms |
| Query with OR across fields / nested groups (1,500 requirements) | 9 ms / 8 ms |
| Activity in German (100 entries translated) | 12 ms |

Previews of auto-scheduling and levelling run the real changes and roll them back (ADR-0027), hence seconds for
hundreds of moves.

**Automated tests at the end of round 4**: 173 backend tests (new: boolean queries, dependency types, slack and
auto-schedule, working-day calendar, time records and privacy, timesheet, resources and levelling, message catalogue
completeness, German errors/activity/notifications/document export/e-mail digest, user language, model translations
in template updates), 48 browser E2E tests (new: OR group built with chips and the query text, typed dependency with
label, auto-schedule, time recording, timesheet, resource heatmap and levelling, German user interface following the
user), translation check in the frontend build (1,440 texts).

## 14.7 Round 5 — Git interface and connectors (0.8)

**Method**: the 50 browser E2E tests on a fresh stack, 81 hostile-input and permission checks against the running
application (repository URLs, paths, revisions, branch names, uploads, roles), a live connection of a public GitHub
repository and of a SysON server, and the connector round trips in the backend tests.

| # | Finding | Kind | Fix |
|---|---|---|---|
| 1 | Imports without the *dry_run* form field applied the data: the API framework reads a missing boolean form field as false | bug | Upload endpoints read the field themselves and default to the preview (also ReqIF, CSV/Excel and Word imports); regression test |
| 2 | HARA export and re-import created a second safety goal | bug | The export writes the medini IDs kept with the items |
| 3 | Connecting a repository while the background fetch picked it up indexed the commits twice — the connect request failed | bug | One sync per repository at a time (row lock): a request waits and indexes only what is still new, the background fetch skips a busy repository; regression test |
| 4 | A path with a control character (NUL) gave a server error in the repository browser | bug | Paths with control characters are rejected |
| 5 | A missing folder showed as an empty folder; an extensionless file (e.g. `CHANGES`) opened as a folder | UI | Missing folders give "not found"; the browser marks folders itself instead of guessing from the name |
| 6 | Paths were read as Git pathspecs (`:(exclude)…` changed the meaning of a filter) | hardening | Literal pathspecs only |
| 7 | Uploaded EA model files are SQLite databases: a crafted file (endless view, huge tables, odd column names) could keep the server busy | hardening | Time limit, row limit and size limit for the write-back copy; column names quoted; no trusted schema |
| 8 | Imported parts and functions were placed into the requirements document along with the requirements | logic | Only requirement types go into the document; other elements keep their package path as reference |

**Hostile input** (all rejected with a message, none reached Git or the file system): SSH and `git@` URLs, `file://`,
`ext::`, option-like URLs (`--upload-pack=…`), paths outside the permitted folder; `..`, absolute and NUL paths;
option-like and shell-like revisions (`--output=…`, `$(id)`, `HEAD;id`); invalid branch names (`../x`, `--force`,
`a..b`, `x~1`); XML external entities and entity expansion in XMI; non-EA SQLite files; SysML server URLs other than
HTTP(S). Tokens never appear in an answer; downloads carry a sandboxing Content-Security-Policy.

**Permission matrix (0.8 endpoints)**

| Action | Viewer | Non-member | Contributor | Reviewer | Manager |
|---|---|---|---|---|---|
| Read repositories, commits, files, linked revisions | 200 | 404 | 200 | 200 | 200 |
| Connect, change, disconnect a repository | 403 | 404 | 403 | 403 | 201/200 |
| Fetch now, create a branch, link a revision | 403 | 404 | 200/201 | 200/201 | 200/201 |
| Import (EA, medini, SysML v2) | 403 | 404 | 200 | 200 | 200 |
| Export (EA XMI, HARA, FMEA) | 200 | 404 | 200 | 200 | 200 |
| Write back into a .qea | 403 | 404 | 200 | 200 | 200 |
| Configure the SysML v2 server | 403 | 404 | 403 | 403 | 200 |

**Live checks**: the public repository of this product connected without a token (15 commits, branches, the pull
request check of GitHub) in about three seconds; SysON reached from the container (`host.docker.internal`) with
the import preview of a drone architecture (requirements, parts, part decomposition).

**Automated tests at the end of round 5**: 183 backend tests (new: repositories, sync and linked revisions,
browsing and branches, pull requests and push webhook, concurrent syncs, EA import/identity/conflicts, XMI round
trip, write-back, hostile model files, medini HARA and FMEA, SysML v2, preview default of uploads), 50 browser E2E
tests (new: Code page with commit, diff and linked items, linked revisions and branch of an item, EA import wizard,
medini HARA import).

## 14.8 Round 6 — hardening for the first public deployment (0.8.1 … 0.8.3)

**Method**: review of the sign-in, session, WebSocket, upload and concurrency paths before the application was put
on an internet-facing address (Azure Container Apps, [18](18-azure-container-apps.md)); every fix with a backend test;
live checks against the running test stack (sign-in limit, forged `X-Forwarded-For`, eight rounds of two parallel
saves of one item); the 81 hostile-input checks of round 5 repeated; the browser tests on a fresh stack.

| # | Finding | Kind | Fix |
|---|---|---|---|
| 1 | Nothing limited password guessing (sign-in and "current password" when changing it) | security | Failed attempts are counted per user name and per client address in a sliding window; further attempts get 429 with `Retry-After` — also with the right password, also for guessed names; a success clears the counter. `ALMLIGHT_LOGIN_MAX_FAILURES`, `ALMLIGHT_LOGIN_WINDOW_SECONDS` |
| 2 | Unknown user names were answered faster than wrong passwords (no Argon2 work), which reveals which names exist | security | Unknown and inactive users cost the same effort |
| 3 | Failed sign-ins left no trace | audit | Failures of existing users and the block are in the audit trail (guessed names only in the server log, so they cannot fill the trail) |
| 4 | Entra ID sends the user principal name in any case; single-sign-on users were matched case-sensitively and could be created twice | bug | User names are lower case, existing mixed-case accounts are still found |
| 5 | Two people saving the same version of an item at once: the second got a database error (500) | bug | The item's row lock is taken first, so the version check sees the other change (409); attachments and revisions likewise; database conflicts (unique, foreign key, deadlock) answer 409 in any case |
| 6 | Unexpected faults answered as plain text | quality | JSON error body like every other error |
| 7 | The connected Git repository was not visible under *Settings → Integrations* and only as one line of text on *Connectors* | UI | Repository list with state (in sync, error, not fetched, disabled) in both places |
| 8 | The demo dataset on a reachable server would have created users with the published password `demo1234`, and no colleague could open the example project without being added one by one | security / usability | `ALMLIGHT_DEMO_SIGN_IN=false` gives the demo users random passwords (their approvals are signed with it during the load); a project can carry an **open role** that every signed-in user holds (`ALMLIGHT_DEMO_OPEN_ROLE`, or *Settings → Members → Everyone who signs in*) |
| 9 | The demo firmware repository lives below the data directory; after a container restart it would report a fetch error | bug | Written again at start with the same commit hashes (dates are anchored at the first load) |
| 10 | Found by the test of finding 9: the fetch lock reloaded the repository object and discarded changes not yet written | bug | Changes are written before the reload |
| 11 | Connecting a repository: the browser offered the saved Ariadne login for *Name* + *Access token*, and the wrong token made GitHub refuse a **public** repository ("could not read Username…") | bug | Fields that hold a foreign credential refuse autofill (`autocomplete`, password-manager attributes), the token field says it is a token of the Git server and that public repositories need none, and a refused or unreachable repository now gets a message that says what to do instead of the raw Git output |
| 12 | A revision was linked by typing a commit hash, so people copied links out of the Git provider into *Other references* | usability | The *Revision to link* list picks commits of the repository (server-side search over message, author and hash, with author and age in the list), *Branch or tag* narrows it to one release, and commits already linked cannot be picked twice |

**Live checks**: after ten wrong guesses the eleventh attempt is refused whatever `X-Forwarded-For` says (the per-user
limit does not depend on the address); another user can sign in; five failures followed by the right password sign
in; 16 parallel saves in eight rounds ended with exactly one 200 and one 409 each, never a 5xx. Without the row lock the
test of finding 5 fails with the unique-constraint error of the old code.

**Automated tests at the end of round 6**: 196 backend tests (new: sign-in limit and audit, address limit and reset, the
current-password limit, the window and its memory bound, single-sign-on user names, the concurrent save, conflict and
fault answers, open projects for every role and path, the demo for a reachable server, the repository written again, the
messages for a refused or unreachable repository), 53 browser E2E tests (new: repositories under Integrations and Connectors, the blocked sign-in message, a manager opening
a project to everyone, picking a revision from the repository and from one release).

## 14.9 Known limitations

- Live editing sessions and live updates run in one application process (single app container).
- Two interface languages (English, German); request-validation details from the API framework stay English.
- PDF export uses the standard layout; corporate templates apply to Word.
- E-mail digests were tested with a simulated SMTP server, single sign-on with a simulated identity provider
  (discovery, JWKS, signed tokens, PKCE) — a check against the customer's mail server and Entra ID/Keycloak tenant
  belongs to the installation.
- The demo data is created in one go, so the demo burn-up shows a single step.
- Scheduling uses one calendar (Mon–Fri) without holidays or personal absences; levelling moves tasks but does not
  split or stretch them, so a task needing more hours per day than its owner has stays overloaded (it is listed).
- Single-sign-on users cannot give electronic signatures (they check the user's own password): approvals with a
  signature need a local account until signing through the identity provider or a signing password is added.
- Sign-in limits are kept in memory of the one application process (a restart clears them); behind a proxy the client
  address is only as reliable as `X-Forwarded-For`, so the per-user-name limit is the dependable one.
- Git over HTTPS only (no SSH); pull requests are read from GitHub (GitLab/Bitbucket/Azure Repos: commits, branches
  and links, no merge requests yet).
- The EA write-back was checked against the EA 16 database layout in tests, not yet by opening the result in an EA
  installation; `.eap`/`.eapx` files have to be saved as `.qea` first. medini analyze is connected through its
  Excel/CSV and ReqIF exchange, not through its API.
- Out of scope by design: manufacturing BOM/bill of process, CAD-authoring integrations, multi-site replication.
