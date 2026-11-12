import sys
from contextlib import asynccontextmanager
from pathlib import Path

# The API is run with cwd=app/api; the shared `common` package and the flows
# package live at the repository root, so make it importable first.
_REPO_ROOT = str(Path(__file__).resolve().parents[2])
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from common.logger import get_logger
from config.config import settings
from database.config import SQLiteDBConfig
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from middleware.logging import LoggingMiddleware, setup_logging
from pathlib import Path
from routers import auth, documents, issues
from security import users

# Set up logging configuration (console + local file, no cloud export)
setup_logging()

logging = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    SQLiteDBConfig().init_db()
    users.ensure_bootstrap_user()
    if not settings.llm_configured:
        logging.warning(
            "LLM endpoint is not configured (LLM_BASE_URL / LLM_API_KEY / LLM_MODEL). "
            "Health will report degraded; review endpoints will return a clear error."
        )
    logging.info("Application startup complete.")
    yield
    logging.info("Application shutdown.")


app = FastAPI(title="AI Document Review (local)", lifespan=lifespan)

# Middlewares
app.add_middleware(LoggingMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(auth.router)
app.include_router(documents.router)
app.include_router(issues.router)


@app.get(
    "/api/health",
    summary="Health Check",
    response_description="Health status of the API",
)
def health_check():
    llm_ok = settings.llm_configured
    try:
        SQLiteDBConfig().connect().close()
        db_ok = True
    except Exception as e:
        logging.error(f"Database health check failed: {e}")
        db_ok = False
    status = "ok" if (llm_ok and db_ok) else "degraded"
    return {"status": status, "llm_configured": llm_ok, "database": "ok" if db_ok else "error"}


# Mount the UI at the root path (last, so it doesn't interfere with /api routes).
# Tolerant: skip mounting when the built frontend is absent (API-only dev mode).
if settings.serve_static:
    static_path = Path(settings.static_dir)
    if static_path.is_dir():
        app.mount("/", StaticFiles(directory=settings.static_dir, html=True), name="ui")
    else:
        logging.warning(
            f"Static directory '{settings.static_dir}' not found; serving API only."
        )


# Exception handler only for HTTPExceptions
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    logging.error(f"HTTPException occurred: {exc.detail}")
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": "HTTPException", "message": exc.detail},
    )


# Exception handler for general exceptions: never echo internals to clients.
@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    logging.error(f"Unexpected error at {request.url.path}: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "error": "500 Internal Server Error",
            "message": "An unexpected error occurred. Check server logs for details.",
        },
    )
