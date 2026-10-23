"""Application factory: REST API under /api/v1, OpenAPI docs, and the single-page frontend."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from almlight import PRODUCT, __version__
from almlight.core.config import get_settings
from almlight.core.db import session_factory
from almlight.core.errors import install_error_handlers
from almlight.modules.baselines.router import router as baselines_router
from almlight.modules.boards.router import router as boards_router
from almlight.modules.bom.router import router as bom_router
from almlight.modules.branches.router import router as branches_router
from almlight.modules.collab import router as collab
from almlight.modules.doc_collections.router import router as collections_router
from almlight.modules.doctemplates.router import router as doctemplates_router
from almlight.modules.documents.router import router as documents_router
from almlight.modules.files.router import router as files_router
from almlight.modules.identity.oidc import router as oidc_router
from almlight.modules.identity.router import router as identity_router
from almlight.modules.identity.service import ensure_bootstrap_admin
from almlight.modules.images.router import router as images_router
from almlight.modules.integrations.router import router as integrations_router
from almlight.modules.integrations.service import OutboxWorker
from almlight.modules.io.router import router as io_router
from almlight.modules.items.router import router as items_router
from almlight.modules.links.router import router as links_router
from almlight.modules.live.router import router as live_router
from almlight.modules.notifications.router import router as notifications_router
from almlight.modules.planning.router import router as planning_router
from almlight.modules.projects.router import router as projects_router
from almlight.modules.queries.router import router as queries_router
from almlight.modules.reports.router import router as reports_router
from almlight.modules.risks.router import router as risks_router
from almlight.modules.variants.router import router as variants_router
from almlight.modules.verification.router import router as verification_router
from almlight.modules.workflow.router import router as workflow_router

log = logging.getLogger("almlight")
API_PREFIX = "/api/v1"

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "same-origin",
}
CSP = ("default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; script-src 'self'; "
       "font-src 'self' data:; connect-src 'self' {ws}; frame-ancestors 'none'; base-uri 'self'; form-action 'self'")


def _csp(request: Request) -> str:
    """Live editing uses WebSockets to this same origin; name it exactly (not every browser maps 'self' to ws:)."""
    host = (request.headers.get("x-forwarded-host") or request.headers.get("host") or "").split(",")[0].strip()
    ws = f"ws://{host} wss://{host}" if host and all(c.isalnum() or c in ".-:[]" for c in host) else ""
    return CSP.format(ws=ws)


@asynccontextmanager
async def lifespan(app: FastAPI):
    import asyncio

    from almlight.core.events import bus
    from almlight.modules.collab.rooms import manager, recover_drafts

    settings = get_settings()
    bus.bind(asyncio.get_running_loop())
    manager.bind()
    logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    with session_factory()() as db:
        ensure_bootstrap_admin(db)
        if settings.demo_data:
            from almlight.seed.demo import seed_demo

            seed_demo(db)
    recovered = recover_drafts()
    if recovered:
        log.warning("Saved %d live editing session(s) interrupted by the last shutdown", recovered)
    worker = None
    if settings.outbox_worker:
        worker = OutboxWorker()
        worker.start()
    log.info("%s %s started", PRODUCT, __version__)
    yield
    if worker:
        worker.stop()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=f"{PRODUCT} API",
        version=__version__,
        description=(
            "Lightweight engineering backbone: configurable items with full version history, traceability, "
            "workflows and approvals, baselines, change management, variants and verification."
        ),
        docs_url=f"{API_PREFIX}/docs",
        redoc_url=f"{API_PREFIX}/redoc",
        openapi_url=f"{API_PREFIX}/openapi.json",
        lifespan=lifespan,
    )
    install_error_handlers(app)
    if settings.cors_origins:
        app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=True,
                           allow_methods=["*"], allow_headers=["*"])

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        path = request.url.path
        for k, v in SECURITY_HEADERS.items():
            response.headers.setdefault(k, v)
        if not path.startswith(f"{API_PREFIX}/docs"):  # Swagger UI loads its assets from a CDN
            response.headers.setdefault("Content-Security-Policy", _csp(request))
        if path.startswith(API_PREFIX):
            response.headers.setdefault("Cache-Control", "no-store")
        return response

    for r in (identity_router, oidc_router, projects_router, items_router, links_router, workflow_router,
              baselines_router, variants_router, verification_router, io_router, integrations_router, branches_router,
              reports_router, documents_router, collections_router, images_router, collab.router, live_router,
              risks_router, bom_router, planning_router, notifications_router, queries_router, files_router,
              doctemplates_router, boards_router):
        app.include_router(r, prefix=API_PREFIX)
    collab.install()

    @app.get(f"{API_PREFIX}/health", tags=["system"])
    def health() -> dict:
        with session_factory()() as db:
            db.execute(text("SELECT 1"))
        return {"status": "ok", "version": __version__}

    @app.api_route(f"{API_PREFIX}/{{path:path}}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
                   include_in_schema=False)
    def api_not_found(path: str) -> JSONResponse:
        return JSONResponse(status_code=404, content={"error": {"code": "not_found",
                                                                "message": f"No endpoint /{path}", "details": {}}})

    _mount_frontend(app, settings.static_dir)
    return app


def _mount_frontend(app: FastAPI, static_dir: Path | None) -> None:
    if not static_dir or not (static_dir / "index.html").exists():
        return
    if (static_dir / "assets").exists():
        app.mount("/assets", StaticFiles(directory=static_dir / "assets"), name="assets")
    index = static_dir / "index.html"

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> FileResponse:
        candidate = (static_dir / path).resolve()
        if path and candidate.is_file() and static_dir.resolve() in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(index, headers={"Cache-Control": "no-cache"})


app = create_app()
