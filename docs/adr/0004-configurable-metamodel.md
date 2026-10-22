# ADR-0004 Configurable information model as data (process templates)

**Context.** MHP tailors ALMlight per customer. Hard-coding types such as "requirement" would lead to forks.

**Decision.** Item types, fields, link types and workflows are defined in YAML process templates and validated by
Pydantic models (`metamodel.py`). Each project stores its own JSON copy with a version counter, so projects keep
working when shipped templates evolve. Engine features that need specific types (change control, verification,
variants, maturity) are bound through a `semantics` section with sensible defaults. Configuration changes are
checked for compatibility with existing data.

**Consequences.** + Customer tailoring without code; customer labels in any language. + Templates are reviewable
artefacts of the consulting work ("information model second"). − The UI must be generic (dynamic forms, generic
lists); some conventions remain (feature `code`, element `level`) and are documented in the configuration guide.
