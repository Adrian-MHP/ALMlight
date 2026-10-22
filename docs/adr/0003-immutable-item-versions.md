# ADR-0003 Immutable item versions with revision and iteration

**Context.** Complete change history, baselines, diffs, re-test detection and audits all need exact previous
states. PLM suites distinguish formal *revisions* (A, B, C) from working *iterations/versions* (A.1, A.2).

**Decision.** Every content change appends an immutable `ItemVersion` (title, description, fields, applicability,
attachment list, state at creation, author, note, change order). The `items` row holds a denormalised copy of the
head for listing and search. Labels are `revision.iteration`; *Revise* starts the next revision in the initial state.
Lifecycle state changes are recorded as workflow events, not as versions. Optimistic locking via `version_no`.

**Consequences.** + History, diff, restore, baselines and test pinning are trivial and exact. + Storage grows
linearly with edits (text is small; files are de-duplicated by hash). − Two places hold the current content; the item
service is the only writer, which keeps them consistent.
