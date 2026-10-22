# ADR-0009 One container image, SPA served by the API, Docker-only toolchain

**Context.** Customers should run Ariadne with minimal effort; developer machines may lack Node or a current Python.

**Decision.** A multi-stage Dockerfile builds the React frontend (Node) and the Python runtime into one image; the
API serves the static SPA with a fallback to `index.html`. Compose runs `app` + `db`; a separate `compose.test.yaml`
runs backend tests, the app with demo data and Playwright E2E tests. Dependencies are pinned
(`requirements.txt`, `package-lock.json`).

**Consequences.** + `docker compose up -d` is the whole installation; same artefact in test and production.
− Frontend hot reload needs a Node container during development.
