# ADR-0006 Baselines as explicit snapshots with revision rules

**Context.** Alternatives: a baseline as a timestamp (state "as of"), or explicit copies of item-version pointers.

**Decision.** A baseline stores rows `(item → version, state)` and copies of the links, for the whole project or a
structural sub-tree. Revision rules *latest* and *released* select the version per item (Teamcenter-style revision
rules). Baselines are immutable; compare works baseline↔baseline and baseline↔current.

**Consequences.** + Exact, self-contained, fast to compare, independent of later data repairs; scoped baselines for
documents. − Storage per baseline is proportional to the number of items (small for SME projects).
