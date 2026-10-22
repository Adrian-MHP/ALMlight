# ADR-0008 Variants: features as items, applicability expressions

**Context.** Product platforms need commonality/variability transparency and configured views (150% → 100%).

**Decision.** Features and variants are items (versioned, traceable, with lifecycle). The feature tree uses the
structural link type with mandatory/optional features and alternative/or groups; `requires`/`excludes` links express
constraints. Items and links can carry boolean applicability expressions over feature codes, parsed by a small
recursive-descent parser (never `eval`). Resolving a selection filters items and links; variants are validated.

**Consequences.** + Variability on requirements, tests and structure in one mechanism; no extra tooling.
− No SAT solving for large feature models (validation checks a given selection; generation of valid
configurations is out of scope).
