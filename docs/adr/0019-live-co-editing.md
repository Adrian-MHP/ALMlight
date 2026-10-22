# ADR-0019 Live co-editing with a server-held Yjs document per item

**Context.** Several engineers should edit the same text at the same time (as in modern office tools), see each other
and never lose work — without giving up the ALM guarantees: immutable versions, frozen lifecycle states, approvals and
an audit trail. Options were pessimistic locking per item (simple, but blocks people), operational transformation
(needs a central sequencer and per-format transforms) and CRDTs (Yjs) with a relay server.

**Decision.** One CRDT document (Yjs) per item, held by the server ("room", pycrdt) and synchronised with the browsers
over the standard y-websocket protocol; the editor (TipTap/ProseMirror) binds to it. The server is authoritative: it
drops updates from read-only participants, stamps presence with the authenticated user, persists drafts every two
seconds and converts the shared document into canonical rich text when saving — through the normal item service, so
saving produces an ordinary version (with co-authors in the change note). Saving happens explicitly, when the last
editor leaves (grace period) or after an idle period, never per keystroke. Clients seed an empty room
deterministically (client id derived from the content hash) so concurrent seeds merge. Changes from outside a session
first save it, then restart it; transitions save it before the state changes. A separate live channel pushes change
events (after commit) and presence.

**Consequences.** + Real-time co-editing with cursors, no locks, no lost keystrokes, crash safety, and unchanged
version/audit semantics. + Standard protocol: any Yjs client can participate. − Sessions live in the application
process: one app process (scaling out needs a shared bus for rooms and presence). − Two WebSocket endpoints to allow
in reverse proxies.
