# ADR-0011 Branching: change-scoped revisions plus document branches with 3-way merge

**Context.** "Branching and merging where useful." In PLM, parallel work on released data is normally handled by
revisions under change control, while ALM tools (Polarion) branch *documents* for variant-specific or release-specific
specifications and merge changes back with a 3-way merge.

**Decision.** Two mechanisms:

1. *Revisions under change control* cover parallel work on released data: the released revision stays the valid
   configuration while the next revision is worked on under a change order; baselines freeze any state.
2. *Document branches* (implemented in 0.2) cover variant- or release-specific specifications: branching a document
   copies its structural sub-tree (in reading order) into new items, re-creating the outline and the outgoing traces.
   A `branch_items` table pairs each copy with its source and records the **merge base** — a version of either side,
   git-like: initially the copied source version, after a merge into the source the merged branch version, after an
   update from the source the source version. The merge preview compares base, source and branch **field by field**
   (only-source / only-branch / same / conflict). Merges run in both directions, can be limited to selected items,
   need explicit resolutions for conflicts, create items added in the branch below the matching source parent, and
   write new versions through the item service — so frozen or change-controlled targets must be revised first. A merge
   is all-or-nothing.

The branch relationship is engine data, not a configurable link type, so it works with every process template.

**Consequences.** + No general-purpose branching of the whole database (avoids complexity that SMEs rarely need).
+ Variant-specific documents can be handled either by applicability (one 150% document) or by branches (separate
documents that sync). − Structural moves and deletions inside a branch are reported, not merged automatically.
