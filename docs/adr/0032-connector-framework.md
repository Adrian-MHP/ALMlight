# ADR-0032 Connectors share one neutral model and one import pipeline

**Context.** Customers model in Enterprise Architect, analyse safety in medini analyze, move to SysML v2 tools —
and expect round trips, not one-off copies. Each tool has its own format; writing a separate importer per tool would
duplicate mapping, identity, versioning and preview logic.

**Decision.** A connector only translates its source into a neutral model of objects (stable source id, kind, name,
text, attributes, package path) and relations; one pipeline maps kinds onto item and link types (with
connector-specific suggestions and user overrides), stores each source id as an external reference of the item, and
creates or updates items through the normal services — so versions, audit, suspect links and notifications behave as
for manual edits. A preview runs the real import and rolls it back. Re-imports apply only changed objects; an item
changed in Ariadne and in the source since the last import is reported as a conflict instead of being overwritten.
Exports and write-backs are connector-specific (EA XMI/`.qea`, medini Excel layouts, ReqIF) and keep the source ids.

**Consequences.** + A new connector is a parser (and optionally an exporter); mapping, identity and safety rules come
for free. + Round trips are possible because identities survive both directions. − Tool-specific semantics beyond
objects and relations (diagrams, EA's behavioural models, medini fault trees) are not transferred.
