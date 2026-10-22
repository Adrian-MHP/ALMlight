# ADR-0002 PostgreSQL as the only stateful service

**Context.** We need flexible custom fields, full-text search, graph queries for traceability and transactional
integrity — without running Elasticsearch, a graph database or a message broker at an SME.

**Decision.** PostgreSQL 16 is the single data store: JSONB for custom fields (GIN index), a generated `tsvector`
column for full-text search (`simple` configuration for mixed German/English text), recursive CTEs for trees,
cycles and impact analysis, partial unique indexes for active links, advisory locks for the audit chain and
`SKIP LOCKED` for the outbox. Files go to a content-addressed volume, not into the database.

**Consequences.** + Two containers in total; backups are `pg_dump` + one volume. − Search is good, not
Google-grade (no stemming across languages); a dedicated search engine can be added later behind the query service.
