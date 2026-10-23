# ADR-0027 Bulk edit, boards and the timeline change items only through the normal services

**Context.** Bulk edit, drag & drop on boards and planning boards, and rescheduling on the timeline are fast ways to
change many items. A shortcut (direct SQL updates, special endpoints) would bypass versions, lifecycle locks,
transitions with comments or signatures, suspect links, audit entries and notifications.

**Decision.** All of them use the existing services: bulk edit runs each item through `update_item`,
`execute_transition`, link creation/deletion or deletion in its **own savepoint**, so one blocked item (frozen,
missing field, impossible transition, permission) is skipped with its reason while the others proceed; a **dry run**
executes everything and rolls the transaction back to produce the preview. An e-signature for a bulk transition is
verified once. Board moves call the transition endpoint (with the prompt for comment or signature when required) or
item updates; plan moves call bulk `plan` with `from_release`; timeline drags patch the date fields. While a drag is
in progress the client keeps its card list and row order fixed, so live refreshes cannot interrupt the gesture.
Commit hooks (live events, notification flush) run only when the outermost transaction commits — SQLAlchemy also
reports savepoint commits — so dry runs publish nothing and bulk runs notify once.

**Consequences.** + Identical rules and history for single and bulk changes; no special cases in the audit trail.
+ Previews are exact because they run the real code. − A bulk run of 1,000 items creates 1,000 versions and audit
entries (by design) and takes seconds rather than milliseconds.
