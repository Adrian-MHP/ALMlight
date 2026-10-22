# ADR-0011 Branching: change-scoped revisions now, document branches later

**Context.** "Branching and merging where useful." In PLM, parallel work on released data is normally handled by
revisions under change control, while ALM tools (Polarion) branch *documents* for variant-specific or release-specific
specifications and merge changes back with a 3-way merge.

**Decision.** The MVP covers the core need with revisions: the released revision stays the valid configuration while
the next revision is worked on under a change order; baselines freeze any state. Document branches are the next
increment: branching a specification copies its sub-tree into new items linked by a `branched_from` link that records
the base version; a merge preview classifies each pair (unchanged / changed in branch / changed in master / conflict)
using the base version for a field-level 3-way merge; applying a merge creates new versions in the target (respecting
lifecycle and change control). The data model already supports this (immutable versions to compute the base).

**Consequences.** + No general-purpose branching of the whole database (avoids complexity that SMEs rarely need).
− Variant-specific specifications use applicability expressions until document branches exist.
