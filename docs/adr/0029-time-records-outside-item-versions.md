# ADR-0029 Time records are separate facts, not item versions, with restricted visibility

**Context.** Time recording (Polarion work records, Teamcenter timesheets) attaches many small facts to items —
several people, every day. Storing them as item fields would create a new version for every booking, block booking on
frozen or released items and flood the history. Recorded hours of individuals are also personal data that German
works councils typically restrict.

**Decision.** Hours live in their own table (`work_records`: item, user, day, hours, comment) with audit entries but
no item versions; frozen and released items can be booked on. Hours are actuals (today or earlier, ≤ 24 h per person
and day). The timesheet cell sets a person's hours for one item and day (replacing that day's records). Totals
(spent, remaining = estimate − spent) are visible to every member; individual records only to their author and to
project managers, who also manage corrections. Resource load uses remaining work, not the original estimate.

**Consequences.** + Booking never interferes with lifecycle, reviews or baselines. + Privacy by default; tailoring
(e.g. team leads) is a role decision per installation. − Records are not part of baselines; reports on effort read the
records directly.
