# ADR-0007 CMII-light change management; release via change order

**Context.** SMEs often lack any controlled change process; enterprise CMII implementations are too heavy.

**Decision.** Change objects are ordinary items (problem report, change request, change order) with workflows.
`affects` links list affected items with an action (revise/add/obsolete/review). Item types can be
*change-controlled*: their released revisions can only be revised under a change order in an
`implementation_open` state that lists them. Guards check that all affected items were revised before approval; the
effect `release_affected_items` releases (or obsoletes) them when the change order is released, so one CCB approval
covers the whole change.

**Consequences.** + Closed loop from problem to released solution with full traceability and impact analysis.
+ Teams can start without change control and switch it on per type. − No effectivity (date/serial) yet.
