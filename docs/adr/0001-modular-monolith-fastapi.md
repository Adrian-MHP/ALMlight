# ADR-0001 Modular monolith in Python/FastAPI, API-first

**Context.** ALMlight must be simple to run at small customers, maintainable by a small team, API-first and
extensible. Microservices would multiply operating effort; MHP teams and the existing PoCs work in Python.

**Decision.** A single deployable backend (FastAPI, SQLAlchemy 2, Pydantic 2, Alembic) structured into domain
modules (`projects, identity, items, links, workflow, baselines, variants, verification, io, integrations, audit`),
each with models, services and routers. The REST API (OpenAPI generated) is the only interface of the frontend and of
integrations. Synchronous SQLAlchemy sessions, one transaction per request.

**Consequences.** + One process to deploy, debug and back up; strong consistency across modules; OpenAPI docs for
free. − Module boundaries are enforced by convention, not by process isolation; a module could be extracted later
because services only talk to each other through functions with explicit parameters.
