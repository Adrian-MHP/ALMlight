# ADR-0021 Notifications from the audit stream, buffered per transaction

**Context.** Engineers need to know when watched items, their own items or approvals change, and when someone mentions
them — in the app, live, and optionally by e-mail. Every relevant change is already audited (ADR-0013). Risks: noisy
bulk operations (imports, merges, change-order releases), notifications for changes that are rolled back (dry runs,
failed imports), and coupling every service to a notification API.

**Decision.** Notifications are derived from audit entries: `audit.record` offers each entry to the notification
service, which determines recipients (watchers of the item or of any document/structure containing it, owners,
approvers by role, @mentioned members; never the actor) and **buffers** them in the session. Just before commit the
buffer is written: duplicates dropped, more than five ordinary notifications for one person in one transaction
collapse into one summary; mentions and approvals always stay individual. Savepoint rollbacks remove their part of
the buffer (the same mechanism that drops live events of dry runs). After commit the new notifications are pushed
over the live channel to the recipient's browsers (`user:<id>` channel). E-mail digests are sent by the existing
background worker for notifications that are unread after 30 seconds, one mail per user.

**Consequences.** + No service needs to know about notifications; new audited actions notify automatically. + Bulk
changes and dry runs behave correctly by construction. + Read-before-mail avoids duplicate attention. − Recipient
rules live in one module and must be extended for new action families. − Watching a document resolves containment
per change (recursive query only when the project has watchers).
