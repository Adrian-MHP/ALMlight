# ADR-0026 Structured query conditions with a Polarion-like query language

**Context.** Users expect to filter on any field — custom fields, links, dates, users, plans — and to share queries as
text, as in Polarion's Lucene-based query bar. Options: expose a raw query language parsed into SQL (powerful, but
error-prone and hard to build a UI on), a search engine index (another stateful service), or a structured condition
model with a readable text form.

**Decision.** A query is free text plus a list of conditions `{field, op, values, not}` (operators `in`,
`contains`, `between`, `exists`, `is`). Fields are built-ins, `link.<type>.out|in`, `release` and `field.<key>` for
custom fields; the server validates fields against the project's information model and translates each condition
into SQL on PostgreSQL (JSONB operators with type-aware casts, `coalesce` so that negations include items without a
value). A small query language is a lossless text form of the same model (`type:x state:(a OR b) NOT
link.verifies.in:* updated:[-30d TO *]`), parsed and formatted on the server (`/query/parse`, `/query/format`); the
query builder edits conditions, the text box edits the language. The same conditions drive the item list, export,
saved views, boards and bulk edit. Sorting by custom fields is type-aware.

**Consequences.** + One model for UI, API, saved views, boards and bulk edit; validated, explainable errors. + No
search engine to run. − No top-level `OR` across fields (values only); full-text relevance ranking is limited to
PostgreSQL text search. − Large JSONB filters rely on sequential scans in very large projects (indexes can be added
per customer for hot fields).
