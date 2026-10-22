# 9 API and integrations

Everything the UI does goes through the REST API — interactive documentation at `/api/v1/docs`
(OpenAPI at `/api/v1/openapi.json`).

## 9.1 Authentication

Create a personal access token under *Account → API tokens* and send it as a bearer token. It acts with the
permissions of its owner.

```bash
export ALM=http://localhost:48080/api/v1
export TOKEN=alm_...
curl -H "Authorization: Bearer $TOKEN" $ALM/projects
```

## 9.2 Common calls

```bash
# list / search items (custom fields: field.<key>=<value>)
curl -H "Authorization: Bearer $TOKEN" "$ALM/projects/DEMO/items?type=system_requirement&q=pressure&field.priority=must"

# create an item below a document heading
curl -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" $ALM/projects/DEMO/items \
  -d '{"type":"system_requirement","title":"Report diagnostics","fields":{"priority":"must"},"parent":"H-1"}'

# edit with optimistic locking (version_no from the last read)
curl -X PATCH ... $ALM/projects/DEMO/items/SYS-8 -d '{"title":"…","expected_version":1}'

# link: test case verifies requirement
curl -X POST ... $ALM/projects/DEMO/links -d '{"type":"verifies","source":"TC-1","target":"SYS-8"}'

# lifecycle
curl ... $ALM/projects/DEMO/items/SYS-8/transitions                    # what is possible now
curl -X POST ... $ALM/projects/DEMO/items/SYS-8/transitions/submit -d '{}'

# impact analysis, coverage, baselines
curl ... $ALM/projects/DEMO/items/STK-1/impact
curl ... "$ALM/projects/DEMO/coverage?type=system_requirement"
curl -X POST ... $ALM/projects/DEMO/baselines -d '{"name":"Design review","revision_rule":"released"}'
```

Errors use one format: `{"error": {"code": "locked", "message": "…", "details": {…}}}` with HTTP 401/403/404/
409 (conflict, blocked transition), 422 (validation) and 423 (frozen by lifecycle).

## 9.3 CI/CD: test results

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  -F file=@build/test-results.xml -F build=$CI_COMMIT_SHA -F environment=CI -F variant=VAR-2 \
  $ALM/projects/DEMO/test-runs/import-junit
```

Results are matched to test cases by the field *Automation ID* (`classname.name` or `name`) or by an item key in the
test name (`test_TC-12_range`). The run is created, filled and completed automatically.

## 9.4 GitHub

*Settings → Integrations → GitHub* (manager): enable → copy endpoint and secret (shown once).
In GitHub: *Repository → Settings → Webhooks → Add webhook*: payload URL = endpoint, content type `application/json`,
secret = shared secret, events: *pushes, pull requests, workflow runs*.

Commits, PRs (title, body, branch) and builds that mention an item key (`SYS-12`) become external references on
that item (idempotent on redelivery).

## 9.5 Azure DevOps

*Settings → Integrations → Azure DevOps*: enable → endpoint + secret. In Azure DevOps:
*Project settings → Service hooks → Web Hooks*: URL = endpoint, basic authentication with any user name and the
shared secret as password (or header `X-ALMlight-Token`). Events: *Code pushed*, *Pull request created/updated*,
*Work item created/updated*. Work items, commits and PRs mentioning item keys are linked.

## 9.6 Outbound webhooks

*Settings → Integrations → Outbound webhooks*: URL + events (`*` or e.g. `item.transitioned`). Each delivery:

```http
POST /your/endpoint
Content-Type: application/json
X-ALMlight-Event: item.transitioned
X-ALMlight-Delivery: 1234
X-ALMlight-Signature: sha256=<HMAC-SHA256(secret, body)>

{"id":1234,"event":"item.transitioned","created_at":"…","data":{"project":"DEMO","item":"SYS-4","from":"in_review","to":"approved"}}
```

Events are written in the same transaction as the change (outbox) and delivered asynchronously with up to three
attempts. Deliveries are logged per webhook.

## 9.7 Exchange formats

| Format | Direction | Endpoint |
|---|---|---|
| CSV / Excel | export, import (dry run, all-or-nothing, update by key, parent and link columns) | `/projects/{k}/export.csv`, `/export.xlsx`, `POST /projects/{k}/import` |
| ReqIF 1.2 | export (project requirements or a specification sub-tree) | `/projects/{k}/reqif`, `/projects/{k}/items/{key}/reqif` |
| Project archive (JSON) | export / import with history, links, baselines | `/projects/{k}/archive`, `POST /projects/import-archive` |
| ReqIF 1.x | import with mapping (dry run by default, `.reqif` / `.reqifz`) | `POST /projects/{k}/import-reqif` |
| Word / PDF | export of a document, live or from a baseline (`?baseline=<id>&fields=&links=`) | `/projects/{k}/items/{key}/export.docx`, `/export.pdf` |
| JUnit XML | import | `POST /projects/{k}/test-runs/import-junit` |

## 9.8 Reports and KPIs

Reports are lists of widgets evaluated on the server (`GET /projects/{k}/reports/{id}/data`, Excel:
`/reports/{id}/export.xlsx`). BI tools (Power BI, Excel Power Query, Grafana JSON) can read the engineering KPIs directly:

```bash
curl -H "Authorization: Bearer $TOKEN" $ALM/projects/DEMO/kpis/reuse            # products per module, reuse rate
curl -H "Authorization: Bearer $TOKEN" $ALM/projects/DEMO/kpis/change-lead-time # lead time per change type, trend
curl -H "Authorization: Bearer $TOKEN" $ALM/projects/DEMO/kpis/retest-effort    # per variant
curl -H "Authorization: Bearer $TOKEN" $ALM/projects/DEMO/kpis/variant-ratio    # modules vs. offered variants
```

ReqIF import with an explicit mapping:

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" -F file=@customer.reqifz -F dry_run=false \
  -F 'mapping={"types":{"Customer Requirement":"stakeholder_requirement"},"relations":{"refines":"relates_to"}}' \
  $ALM/projects/DEMO/import-reqif
```

## 9.9 Live documents

```bash
# a document live, as of a point in time, from a baseline, for a variant
curl ... "$ALM/projects/DEMO/items/SPEC-2/document?at=2026-10-22T12:00:00Z"
curl ... "$ALM/projects/DEMO/items/SPEC-2/document?baseline=<id>&variant=VAR-2"
curl ... $ALM/projects/DEMO/items/SPEC-2/document-history

# compare two states (also another document / project)
curl -X POST ... $ALM/projects/DEMO/compare-documents \
  -d '{"left":{"document":"SPEC-2","baseline":"<id>"},"right":{"document":"SPEC-2"}}'

# Word round trip
curl ... "$ALM/projects/DEMO/items/SPEC-2/export.docx?roundtrip=edit" -o review.docx
curl -X POST ... -F file=@review.docx -F dry_run=false $ALM/projects/DEMO/items/SPEC-2/import-docx

# collections
curl -X POST ... $ALM/projects/DEMO/collections -d '{"name":"Release 2.0"}'
curl -X POST ... $ALM/projects/DEMO/collections/<id>/documents -d '{"document":"SPEC-2"}'   # new baseline
curl -X POST ... $ALM/projects/DEMO/collections/<id>/status -d '{"status":"closed"}'
```

Note: links are versioned — `PATCH /links/{id}` returns the id of the new link version.

## 9.10 Rich text and images

`description` is rich text. Requests may send HTML (it is sanitised and normalised) or Markdown/plain text (it is
converted); responses always return canonical HTML. Pasted `data:` images in HTML are stored automatically.

```bash
# upload an image (contributor) and reference it in a text
curl -F file=@plot.png $ALM/projects/DEMO/images          # -> {"url": "/api/v1/images/<sha256>", ...}
curl -X PATCH ... $ALM/projects/DEMO/items/SYS-7 \
  -d '{"description": "<p>See the plot:</p><img src=\"/api/v1/images/<sha256>\" alt=\"plot\">"}'
curl ... $ALM/images/<sha256>                              # members of a project using the image only
```

Diffs (`GET …/diff`, document compare) include `html_diff` with `<ins>`/`<del>` next to the plain-text diff.
ReqIF exports become `.reqifz` archives when they contain images (`?format=reqif|reqifz|auto`).

## 9.11 Live editing and the live channel

| Endpoint | Purpose |
|---|---|
| `WS /api/v1/collab/items/{item id}?base=<content_hash>` | Yjs co-editing session (standard y-websocket protocol; documents `body` and `title`) |
| `GET /api/v1/projects/{k}/items/{key}/collab` | Session status: participants, unsaved changes |
| `POST /api/v1/projects/{k}/items/{key}/collab/save` | Save the session as a new version now |
| `WS /api/v1/live` | JSON: `subscribe` / `presence` from the client; `change` (audit events after commit), `presence` from the server |

Authentication: the session cookie (browsers) or `?token=<API token>`. Close codes: `4001` the text changed
elsewhere (reload), `4409` the start state is outdated (reload), `4401` not authenticated / cross-site, `4404` not found.
`content_hash` is part of every item and document node response.
