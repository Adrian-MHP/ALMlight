# ADR-0016 Exact document time travel through versioned links

**Context.** Users must be able to open a document (and any item) as it was at any earlier point, compare such states
and export them — the way enterprise live documents show any revision. Item contents and lifecycle states were already
immutable (`ItemVersion`, `WorkflowEvent`), but structural links were updated in place (position, attributes), so past
outlines could not be reconstructed exactly.

**Decision.** Links are versioned like items: changing position, attributes or applicability closes the current row
(`deleted_at`) and inserts a successor; deletes are soft. A single snapshot builder produces a document tree from one of
three sources — *live*, *as of instant T* (latest version ≤ T, last workflow event ≤ T, links valid at T) or *baseline*
— with variant filtering and automatic heading numbering. The document history is the audit trail filtered to every
item that was ever part of the document (structural links of all times). Comparison pairs the items of two snapshots by
identity, branch relation, ReqIF identity or title, detects moves with a longest increasing subsequence and produces
word-level diffs.

**Consequences.** + Opening, comparing and exporting past states is exact and uses one code path for UI, Word and PDF.
+ No separate revision store. − Link ids change when a link is edited (the PATCH response returns the new id);
link tables grow with structural edits (small for SME volumes).
