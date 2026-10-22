# Architecture decision records

| # | Decision | Status |
|---|---|---|
| [0001](0001-modular-monolith-fastapi.md) | Modular monolith in Python/FastAPI, API-first | accepted |
| [0002](0002-postgresql-only.md) | PostgreSQL as the only stateful service | accepted |
| [0003](0003-immutable-item-versions.md) | Immutable item versions with revision and iteration | accepted |
| [0004](0004-configurable-metamodel.md) | Configurable information model as data (process templates) | accepted |
| [0005](0005-typed-links-suspect.md) | Typed links owned by the source; suspect on target change | accepted |
| [0006](0006-baselines-as-snapshots.md) | Baselines as explicit snapshots with revision rules | accepted |
| [0007](0007-cmii-light-change.md) | CMII-light change management; release via change order | accepted |
| [0008](0008-variants-150-model.md) | Variants: features as items, applicability expressions | accepted |
| [0009](0009-single-image-delivery.md) | One container image, SPA served by the API, Docker-only toolchain | accepted |
| [0010](0010-authentication.md) | Local accounts, cookie sessions, API tokens; OIDC later | accepted |
| [0011](0011-branching-strategy.md) | Branching: change-scoped revisions plus document branches with 3-way merge | accepted |
| [0012](0012-integration-strategy.md) | Integration via webhooks, external references and an outbox | accepted |
| [0013](0013-hash-chained-audit.md) | Hash-chained, append-only audit trail | accepted |
| [0014](0014-user-defined-reports.md) | User-defined reports as widget lists evaluated on the server | accepted |
| [0015](0015-document-rendering-and-reqif-import.md) | Document rendering (Word/PDF) and ReqIF import identity | accepted |
| [0016](0016-document-time-travel.md) | Exact document time travel through versioned links | accepted |
| [0017](0017-word-round-trip.md) | Word round trip with content controls and 3-way detection | accepted |

Format: context → decision → consequences. New decisions get the next number; superseded ones stay with a note.
