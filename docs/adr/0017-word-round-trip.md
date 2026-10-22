# ADR-0017 Word round trip with content controls and 3-way detection

**Context.** External reviewers (customers, suppliers, management) often work only in Word. Enterprise ALM tools offer
a round trip: export, review in Word, import edits and comments back into the tool and its history.

**Decision.** The round-trip export wraps each item's title and text in Word *content controls* tagged
`alm:<item id>:<version no>:<part>`; the document carries its origin in the core property *identifier*. Two modes:
*edit* (texts editable inside the controls) and *comments* (Word document protection: comments only). The import reads
the controls, converts Word content to Markdown with the same converter that is applied to the exported version (so
untouched text is never a change), and applies a 3-way rule against the exported version: apply if ALMlight did not
change that part meanwhile, otherwise report a conflict; frozen items are reported. Word comments — with replies and
resolved state (`commentsExtended.xml`) — become document comments on the item they were made on; a second import of
the same file adds no duplicates. Dry run first, all changes go through the item service (versions, audit, suspect links).

**Consequences.** + Reviewers need nothing but Word; their input lands in the history with full traceability.
+ Conflicts are never silently overwritten. − Structural edits in Word (new or deleted requirements outside the
controls) are not imported; formatting is limited to what Markdown represents (emphasis, lists, tables).
