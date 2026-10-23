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
| CSV / Excel | export (optionally filtered like the item list: `q`, `state`, `link_type`/`link_dir`/`link_exists`, `planned_in`), import (dry run, all-or-nothing, update by key, parent and link columns) | `/projects/{k}/export.csv`, `/export.xlsx`, `POST /projects/{k}/import` |
| ReqIF 1.2 | export (project requirements or a specification sub-tree) | `/projects/{k}/reqif`, `/projects/{k}/items/{key}/reqif` |
| Project archive (JSON) | export / import with history, links, baselines | `/projects/{k}/archive`, `POST /projects/import-archive` |
| ReqIF 1.x | import with mapping (dry run by default, `.reqif` / `.reqifz`) | `POST /projects/{k}/import-reqif` |
| Word / PDF | export of a document, live or from a baseline (`?baseline=<id>&fields=&links=`); Word in a customer template (`&template=<id>`) | `/projects/{k}/items/{key}/export.docx`, `/export.pdf` |
| BOM | multi-level bill of materials as CSV/Excel (`?effective=YYYY-MM-DD`) | `/projects/{k}/items/{key}/bom.csv`, `/bom.xlsx` |
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

## 9.12 Engineering backbone (0.5)

See [12-engineering-backbone](12-engineering-backbone.md) for the behaviour behind these endpoints.

```bash
# traceability gaps: system requirements without a verifying test (also: derives_from/out, satisfies/in, mitigated_by/out, planned_in/out)
curl -H "Authorization: Bearer $TOKEN" "$ALM/projects/DEMO/items?type=system_requirement&link_type=verifies&link_dir=in&link_exists=false"

# step-wise test result and a defect from step 3
curl -X PATCH -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' "$ALM/projects/DEMO/test-runs/TR-2/records/<record id>" \
  -d '{"step_results": [{"result": "passed"}, {"result": "passed", "actual": "0.12 %"}, {"result": "failed", "actual": "0.6 %"}]}'
curl -X POST -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' "$ALM/projects/DEMO/test-runs/TR-2/records/<record id>/defect" -d '{"step": 3}'

# check out a file, check in a new revision, history
curl -X POST -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' "$ALM/projects/DEMO/items/SE-10/attachments/<id>/checkout" -d '{"note": "M20 thread"}'
curl -X POST -H "Authorization: Bearer $TOKEN" -F file=@housing.step -F comment="M20 thread" "$ALM/projects/DEMO/items/SE-10/attachments/<id>/revisions"
curl -H "Authorization: Bearer $TOKEN" "$ALM/projects/DEMO/items/SE-10/attachments/<id>/history"
```

| Area | Endpoints |
|---|---|
| Notifications | `GET /notifications`, `POST /notifications/read` (`{"ids": […]}` or `{"all": true}`), `PUT /notifications/preferences` (`email`) |
| Watching | `GET /subscriptions`; `GET`/`PUT`/`DELETE /projects/{k}/items/{key}/watch` |
| Saved views | `GET`/`POST /projects/{k}/queries`, `PUT`/`DELETE /projects/{k}/queries/{id}` (query keys as in the item list; `count` and `can_edit` in the list) |
| Test execution | `PATCH /projects/{k}/test-runs/{run}/records/{id}` (`result` or `step_results`, `comment`), `POST …/records/{id}/defect` (`step`, `title`, `description`; one per record) |
| Risks | `GET /projects/{k}/risks` — matrix before/after mitigation, register, summary |
| Plans | `GET /projects/{k}/plans`, `GET /projects/{k}/plans/{release}` — progress, status, burn-up, planned items; plan with `POST /links` (`planned_in`) |
| BOM | `GET /projects/{k}/items/{key}/bom?effective=`, `/bom.csv`, `/bom.xlsx`, `GET /projects/{k}/items/{key}/where-used`; edit quantities with `PATCH /projects/{k}/links/{id}` (`attributes`) |
| Files | `POST`/`DELETE …/attachments/{id}/checkout`, `POST …/attachments/{id}/revisions` (multipart `file`, `comment`), `GET …/attachments/{id}/history`, `GET …/attachments/{id}?inline=true` (images, PDF), `GET /checkouts/mine` |
| Word templates | `GET`/`POST /projects/{k}/doc-templates` (multipart `file`, `name`; manager), `GET …/doc-templates/{id}/download`, `DELETE …/doc-templates/{id}`, `GET …/doc-templates/sample.docx` |
| Template updates | `GET`/`POST /projects/{k}/template-updates` (manager) |
| Single sign-on | `GET /auth/oidc/config`, `GET /auth/oidc/login?next=/`, `GET /auth/oidc/callback` |

## 9.13 Queries, bulk edit, boards, plans and timeline (0.6)

See [15-work-management](15-work-management.md).

```bash
# query language or JSON conditions on the item list (and on export.csv / export.xlsx); sort by custom fields
curl -H "Authorization: Bearer $TOKEN" "$ALM/projects/DEMO/items" -G \
  --data-urlencode 'ql=type:system_requirement priority:(must OR should) NOT link.verifies.in:*' --data-urlencode 'sort=-field.estimate'
curl -H "Authorization: Bearer $TOKEN" "$ALM/projects/DEMO/items" -G \
  --data-urlencode 'cond=[{"field":"field.rpn","op":"between","values":[100,null]},{"field":"owner","op":"in","values":["me"]}]'

# bulk edit: dry run (default) shows per item ok / unchanged / skipped; dry_run=false applies
curl -X POST -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' "$ALM/projects/DEMO/items/bulk" \
  -d '{"query": {"ql": "type:system_requirement state:draft"}, "action": "transition", "transition": "submit", "dry_run": false}'
```

| Area | Endpoints |
|---|---|
| Item queries | `GET /projects/{k}/items?ql=…` or `?cond=<JSON>`; `sort=field.<key>` / `-field.<key>`; `POST /projects/{k}/query/parse` (`{text}` → `{q, conditions}`), `POST /projects/{k}/query/format` |
| Bulk edit | `POST /projects/{k}/items/bulk` — `keys` or `query` (`q`, `types`, `conditions`, `ql`); `action` = `update` (`fields`, `owner_id`+`set_owner`, `applicability`+`set_applicability`), `transition` (`transition`, `comment`, `password`), `plan`/`unplan` (`release`, `from_release`), `link` (`link_type`, `link_dir`, `target`), `watch`, `unwatch`, `delete`; `dry_run` (default `true`); max 1,000 items |
| Boards | `GET`/`POST /projects/{k}/boards`, `GET`/`PUT`/`DELETE /projects/{k}/boards/{id}` — config: `types`, `q`, `conditions`, `columns_by` / `swimlanes_by` (`state`, `owner`, `release`, `type`, `field.<key>`), `hidden_columns`, `column_order`, `wip`, `card_fields` |
| Plans | `GET /projects/{k}/plans` (hierarchy `parent`/`children`, `estimate`, `capacity`, `load`), `GET /projects/{k}/plans/{key}` (`items` with `plan` and `estimate`, `child_plans`, `burnup` with `remaining` and estimate series) |
| Timeline | `GET /projects/{k}/timeline?baseline=<id>` — rows (plans, tasks, milestones) with dates, progress, `parent`, `depends_on`, `slack` (working days), `critical`, `baseline` dates; `conflicts` |

