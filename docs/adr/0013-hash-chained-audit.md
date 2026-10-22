# ADR-0013 Hash-chained, append-only audit trail

**Context.** Audits (ISO 9001, functional safety, customer audits) need a trustworthy record of who changed what.

**Decision.** Every mutation writes an audit entry in the same transaction. Each entry stores the SHA-256 of its
canonical JSON content plus the previous entry's hash; writers serialise with a PostgreSQL advisory lock. An endpoint
recomputes the chain and reports the first broken entry. Item histories are queries on the audit trail
(`related_ids` GIN index).

**Consequences.** + Tamper evidence without external infrastructure. − Serialised audit writes cap write throughput
(ample for SME use); a database administrator could rewrite the whole chain — anchoring the head hash externally
(e.g. in backups or a timestamping service) is a possible extension.
