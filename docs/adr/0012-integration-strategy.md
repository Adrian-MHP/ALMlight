# ADR-0012 Integration via webhooks, external references and an outbox

**Context.** A digital thread links many tools, each authoritative for its data. Copying data creates drift.

**Decision.** ALMlight links instead of copying: `ExternalRef` records point from items to commits, pull requests,
builds, work items, CAD/PDM documents. Inbound webhooks (GitHub HMAC signature, Azure DevOps shared secret) create
references from item keys mentioned in texts. Domain events are written to an outbox in the same transaction and
delivered to signed outbound webhooks by a background worker. Standard formats (ReqIF, JUnit XML, CSV/Excel) cover
file-based exchange. OSLC and the SysML v2 API are the planned standards-based adapters.

**Consequences.** + Loose coupling, idempotent, no message broker. − Reference metadata (status, titles) is only as
fresh as the last event.
