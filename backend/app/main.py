"""FastAPI application entry point."""
import logging
import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.config import settings
from app.core.exceptions import RAGBaseException
from app.core.logging import RequestIDMiddleware, configure_logging
from app.core.metrics import rag_api_request_duration_seconds, rag_api_requests_total
from app.database import AsyncSessionLocal, engine
from app.retrieval.vector_store import get_vector_store

# Router imports
from app.api.v1 import auth, health

# Placeholder routers for upcoming modules
from app.api.v1 import (
    agentic_rag,
    api_keys,
    chat,
    collaboration,
    config,
    documents,
    eval,
    external,
    groups,
    im_integration,
    keywords,
    knowledge_bases,
    knowledge_graph,
    operations,
    permissions,
    search,
    users,
)

configure_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage external connection lifecycle."""
    # Startup
    try:
        from redis.asyncio import from_url as redis_from_url
        from sqlalchemy import text

        # Verify PostgreSQL connectivity
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))

        # Establish Redis connection
        app.state.redis = redis_from_url(settings.redis_url)
        await app.state.redis.ping()

        # Initialize vector store connection (the store manages its own lifecycle)
        get_vector_store()

        # Load runtime model configuration from database
        from app.core.runtime_config import load_runtime_config

        async with AsyncSessionLocal() as db:
            await load_runtime_config(db)
            await db.close()

        # Load sensitive keywords for stream intercept
        try:
            from app.models.keyword import SensitiveKeyword
            from app.services.generation_service import GenerationService
            from sqlalchemy import select

            async with AsyncSessionLocal() as db:
                result = await db.execute(select(SensitiveKeyword))
                keywords = list(result.scalars().all())
                GenerationService.load_stream_annotator(keywords)
                await db.close()
            logging.info("Stream keyword annotator loaded")
        except Exception as exc:  # noqa: BLE001
            logging.warning("Failed to load stream keyword annotator: %s", exc)

        logging.info("Application startup completed")
    except Exception as exc:  # noqa: BLE001
        logging.warning("Some external connections failed during startup: %s", exc)

    yield

    # Shutdown
    try:
        await engine.dispose()
        if hasattr(app.state, "redis"):
            await app.state.redis.close()
        logging.info("Application shutdown completed")
    except Exception as exc:  # noqa: BLE001
        logging.warning("Error during shutdown: %s", exc)


app = FastAPI(
    title=settings.APP_NAME,
    version="0.1.0",
    lifespan=lifespan,
    redirect_slashes=False,
)


class PrometheusMiddleware(BaseHTTPMiddleware):
    """Emit request count and duration metrics for every non-metrics request."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        method = request.method
        status = 500
        start = time.perf_counter()
        try:
            response = await call_next(request)
            status = response.status_code
            return response
        except Exception:
            status = 500
            raise
        finally:
            duration = time.perf_counter() - start
            route = request.scope.get("route")
            endpoint = getattr(route, "path_format", request.url.path)
            if endpoint != "/metrics":
                rag_api_request_duration_seconds.labels(
                    method=method, endpoint=endpoint
                ).observe(duration)
                rag_api_requests_total.labels(
                    method=method, endpoint=endpoint, status=str(status)
                ).inc()


# Prometheus metrics endpoint
@app.get("/metrics")
async def metrics() -> Response:
    """Expose Prometheus metrics."""
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)

# CORS — never combine allow_origins=["*"] with allow_credentials=True.
# Parse CORS_ORIGINS as a comma-separated list; default to the frontend dev origin.
cors_origins_env = os.environ.get("CORS_ORIGINS", settings.CORS_ORIGINS or "")
if cors_origins_env.strip():
    allow_origins = [origin.strip() for origin in cors_origins_env.split(",") if origin.strip()]
    allow_credentials = settings.CORS_ALLOW_CREDENTIALS
else:
    # No origins explicitly configured: restrict to the default frontend origin.
    allow_origins = ["http://localhost:5173"]
    allow_credentials = True

app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Request ID tracking
app.add_middleware(RequestIDMiddleware)

# Prometheus request metrics
app.add_middleware(PrometheusMiddleware)

# Register API routers
app.include_router(health.router, prefix="/api/v1")
app.include_router(auth.router, prefix="/api/v1")
app.include_router(knowledge_bases.router, prefix="/api/v1")
app.include_router(documents.router, prefix="/api/v1")
app.include_router(search.router, prefix="/api/v1")
app.include_router(chat.router, prefix="/api/v1")
app.include_router(permissions.router, prefix="/api/v1")
app.include_router(keywords.router, prefix="/api/v1")
app.include_router(groups.router, prefix="/api/v1")
app.include_router(users.router, prefix="/api/v1")
app.include_router(config.router, prefix="/api/v1")
app.include_router(eval.router, prefix="/api/v1")
app.include_router(collaboration.router, prefix="/api/v1")
app.include_router(api_keys.router, prefix="/api/v1")
app.include_router(external.router, prefix="/api/v1")
app.include_router(knowledge_graph.router, prefix="/api/v1")
app.include_router(im_integration.router, prefix="/api/v1")
app.include_router(agentic_rag.router, prefix="/api/v1")
app.include_router(operations.router, prefix="/api/v1")


@app.exception_handler(RAGBaseException)
async def rag_exception_handler(request: Request, exc: RAGBaseException):
    logging.warning("RAG exception at %s: %s", request.url.path, exc.message)
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.message},
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logging.exception("Unhandled exception at %s", request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )


@app.get("/")
async def root():
    return {"message": settings.APP_NAME}
