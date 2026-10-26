# 17 Code (Git) and connectors to engineering tools (0.8)

Version 0.8 connects Ariadne to the tools around it: Git repositories the way Polarion integrates them (linked
revisions, repository browser), and connectors to **Enterprise Architect**, **medini analyze** and **SysML v2**
servers. Every connector imports with a preview and a mapping onto the project's information model, keeps the
identity of each source element, and can be repeated; the exports go back in the formats the tools read.

| | Where | Direction | Formats |
|---|---|---|---|
| [Git](#171-git-repositories-and-linked-revisions) | Code page, item → Development | read (and create branches) | HTTPS clone URL: GitHub, GitLab, Bitbucket, Azure Repos, any Git server |
| [Enterprise Architect](#172-enterprise-architect) | Connectors | import, export, write-back | `.qea`/`.qeax` (EA 16+), XMI 2.1 |
| [medini analyze](#173-medini-analyze) | Connectors | import, export | HARA and FMEA as `.xlsx`/`.csv`, safety requirements as ReqIF |
| [SysML v2](#174-sysml-v2-api) | Connectors | import | OMG Systems Modeling API (SysON, Cameo, …) |
| ReqIF | Settings → Import / Export | import, export | `.reqif`, `.reqifz` (DOORS, Polarion, codebeamer, OEM portals) |

## 17.1 Git repositories and linked revisions

**Connect** (managers, Code page → *Connect repository*): the HTTPS clone URL, optionally an access token. Without a
token, public repositories are read; private repositories need a token with read access, creating branches one with
write access. The token is stored encrypted with the installation's secret key and never shown again. Local
repositories on the server can be connected by path below `<data dir>/repos-local` (the demo uses this).

**Sync**: the server keeps a bare, read-only mirror (branches and tags) and fetches it every
`ALMLIGHT_GIT_SYNC_MINUTES` (default 10) or on *Fetch now*; a push webhook (Settings → Integrations → GitHub) makes it
fetch at once. New commits are indexed (author, date, message, files with added/removed lines); a first sync reads at
most the latest 5,000 commits. A repository is fetched by one sync at a time (a second request waits and
indexes only what is still new).

**Linked revisions** (Polarion): a commit whose message mentions an item key — `SYS-12: add range check`,
`Fix drift, closes PR-3` — is linked to that item. The item's *Development* tab lists its linked revisions (commit,
title, repository, author, date, link to the provider), the **branches** whose names contain its key and, for GitHub,
the **pull requests** mentioning it. A commit can also be linked **by picking it**: the *Revision to link* list
searches the repository's indexed commits by message, author or hash (the server searches, the list shows the short
hash, the subject, the author, the age and the items the commit is already linked to); *Branch or tag* narrows it to
one branch or release, so the newest entry is the tagged commit — the way to point a requirement at a concrete
software version. Commits already linked to this item are shown but cannot be picked twice. Manual links can be
removed, links from the message stay. Artefacts of other systems (CAD, PDM, builds, work items) stay in *Other
references* as before. *Create branch* proposes `feature/<KEY>-<title>` and creates it in the remote
repository (needs a write token; otherwise the `git checkout -b …` command is offered to copy).

**Code page** (repository browser):

- *Commits*: search by message, author or hash, filter by branch or tag, the items each commit is linked to.
- *Commit*: message, author, parents, branches containing it, linked items (add or remove links), and the diff of
  every changed file.
- *Files*: the tree at any branch, tag or commit, file view with line numbers, history of the file, download.
- *Branches & tags*: last commit and the items named in the branch.

**Query**: `commits:true` (items with linked commits), `NOT commits:true` (implementation gap), `commit:4a7d9af`
(items linked to a commit); also in the query builder (*Code* group).

Security: only HTTPS (and permitted local paths); no prompts or credential helpers; credentials are passed to Git in
the environment, never on the command line; every Git call has a timeout; the mirror is bare (no hooks, no checkout);
paths and revisions are validated; files are downloaded with a sandboxing Content-Security-Policy.

## 17.2 Enterprise Architect

**Import** (Connectors → Enterprise Architect → *Import model…*): an EA 16+ model file (`.qea`/`.qeax`, read
directly — no EA needed on the server) or an XMI 2.1 export. Read are elements with name, notes (formatting kept),
alias, status, version, author, stereotype and tagged values, the package hierarchy, and connectors. `.eap`/`.eapx`
(Microsoft Access) are not readable on the server — save them as `.qea` in EA or export XMI.

The wizard lists the element types and connector types of the file with counts and proposes the mapping:

| In EA | Default in Ariadne |
|---|---|
| Requirement (any stereotype) | System requirement (stakeholder requirement for «stakeholder…»/«business…») |
| Class «block», Component, Part, Node | System element |
| Activity, Action | Function |
| Interface, Port | Interface |
| Use case | Stakeholder requirement |
| «testCase» | Test case |
| Issue / Change / Feature | Problem report / change request / feature |
| «satisfy», «deriveReqt», «verify» | satisfies, derives from, verifies |
| Realisation | realizes |
| Aggregation / Composition | contains (reversed: the whole contains the part) |
| «trace», «refine», Dependency, Abstraction | relates to |

Tagged values and EA properties map onto fields of the same name (e.g. *Priority* → priority). Optionally, new
requirements go into a document with a heading per EA package. Elements are identified by their **EA GUID**: a
re-import updates the same items (new versions only where the model changed). If an item was changed in Ariadne
*and* in EA since the last import, the model is not applied to it — the preview lists the conflict.

**Export XMI**: requirements, elements, functions, interfaces, tests and their links as XMI 2.1 in EA's structure
(UML part plus the "Enterprise Architect" extension with element types, notes, alias, status, stereotypes, tagged
values *Ariadne key*, state and fields, and connectors with stereotypes). Items imported from EA keep their GUIDs;
new items get a stable GUID derived from the item, so a later import maps them back.

**Write back into .qea**: upload the model, choose the package for new elements (and optionally a query): Ariadne
writes into a copy — elements known by GUID are updated (name, notes, alias = key, version, status), new items become
elements of the matching EA type in that package (with the tagged value *Ariadne key*), links between elements
become connectors. New rows are cloned from existing ones of the model, so all EA columns keep valid values. The
original file is never changed on the server.

## 17.3 medini analyze

**HARA** (Excel/CSV, the layout medini analyze exports; English or German column names, a title row above the
header is fine): each hazardous event becomes a **hazard** item with malfunction, operational situation, hazardous
event and S/E/C. The **ASIL is computed** from S, E and C as in ISO 26262-3 (the table is equivalent to S + E + C:
10 = D, 9 = C, 8 = B, 7 = A, otherwise QM; any class 0 gives QM); an ASIL in the file that differs is reported.
Safety goals become requirements (safety relevant, kind *safety*) with ASIL — the highest of their hazardous events —,
safe state and FTTI, linked to the hazards by *mitigated by*.

**FMEA** (Excel/CSV): function/element, failure mode, effect, cause, severity, occurrence, detection, prevention and
detection controls, recommended actions → **risk** items (RPN and risk level computed); item keys mentioned in the
actions (e.g. `SYS-12`) become *mitigated by* links.

**Export**: *Export HARA* and *Export FMEA* write the tables in the same column layout (with the medini IDs kept), so
they go back into medini analyze; re-importing them changes nothing. **Safety requirements** go both ways as ReqIF
(Settings → Import / Export): attributes *ASIL*, *Safe state* and *FTTI* map onto the fields of the same names.

The template (version 5) adds the hazard type with S/E/C and the computed ASIL, and ASIL, safe state and FTTI on
system and subsystem requirements; existing projects take them over as template updates.

## 17.4 SysML v2 API

**Connect** (managers): the base URL of the SysML v2 server (from the Docker container, a server on the host is
`http://host.docker.internal:8080`), optionally a token; choose the project. **Import** reads the latest commit:
requirement and concern definitions/usages (name, short name/requirement id, text and documentation), parts,
actions, interfaces, ports, use cases and verification cases; relations: *satisfy* (`SatisfyRequirementUsage` —
satisfying feature or owning part → requirement), part decomposition and sub-requirements. Default mapping:
requirements → system requirements, parts → system elements, actions → functions, interfaces/ports → interfaces,
use cases → stakeholder requirements, verification cases → test cases; satisfy → satisfies, part of → contains,
sub-requirement → derives from. Elements are identified by their element id; the fetched model is cached for an hour
(large models take minutes on some servers), *Read again* bypasses the cache. Tested with SysON.

## 17.5 Common rules

- Imports need the contributor role, configuration (repositories, SysML server) the manager role; exports are
  available to every member.
- Every import first runs as a **preview** (the real import inside a transaction that is rolled back), then
  applies; each created or changed item gets a normal version with the change note "<tool> import (<source>)";
  the audit trail records the run.
- Source identities are external references of the items (Development tab), so the item shows where it came from.
- Messages and warnings follow the user's language.
- Sample files: `samples/` in the repository.
