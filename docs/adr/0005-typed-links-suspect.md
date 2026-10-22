# ADR-0005 Typed links owned by the source; suspect on target change

**Context.** Traceability is the core value; it must stay trustworthy when things change (safety standards demand
evidence that traces survived changes).

**Decision.** Links are typed, directed and validated against allowed source/target types; the convention is
"source depends on target". A link belongs to its source: a frozen source cannot change its links (configurable per
link type). When a target's content changes, links of types with `suspect_on_target_change` are flagged suspect until
someone confirms them. Structural links are ordered (float positions) and may form a DAG (reuse), cycles are
prevented for acyclic types. Links are soft-deleted and copied into baselines.

**Consequences.** + Impact analysis and re-test detection fall out of the same graph. − Users must learn the
direction convention; the UI always shows the reverse label on the target side.
