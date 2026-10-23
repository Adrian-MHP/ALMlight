# ADR-0028 Scheduling on a working-day calendar with typed dependencies, auto-scheduling and levelling

**Context.** Finish-to-start dependencies alone cannot express common engineering schedules (a report written
alongside a qualification, two activities that must finish together), and users expect the scheduling aids of
Teamcenter Schedule Manager and MS Project: lag and lead, a forward pass that resolves conflicts, and resource
levelling. Scheduling logic easily becomes a second source of truth next to the items.

**Decision.** Dependencies stay ordinary `depends_on` links; their *type* (`fs`, `ss`, `ff`, `sf`) and *lag* (working
days) are link attributes of the information model, so they are versioned, audited and tailorable, and old links mean
finish-to-start. One pure module (`planning/schedule.py`) holds the calendar (Mon–Fri, inclusive dates), the rule of
each type, slack, the forward pass and greedy levelling; the timeline, auto-scheduling and levelling all use it.
Auto-scheduling and levelling only *propose* moves: a dry run returns them, applying saves each move through
`update_item` in its own savepoint (ADR-0027), and plans, frozen, started and finished items are never moved. Levelling
only delays work and keeps every dependency. Personal calendars, skills and partial assignments are not modelled.

**Consequences.** + One rule set for drawing, conflicts, critical path and the scheduling aids; results are previewed
and every move is an auditable item change. + Works on existing projects after a template update. − No calendar per
person or holidays yet; estimates of tasks must be in hours for meaningful resource load.
