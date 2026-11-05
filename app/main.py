from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.engine import Engine

from app.api import admin, assets, auth, tickets
from app.core.config import settings
from app.db.base import Base
from app.db.seed import seed_initial_data
from app.db.session import SessionLocal, engine
from app.models import models  # noqa: F401

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FRONTEND_DIR = PROJECT_ROOT / "frontend"


def create_app(database_engine: Engine = engine, seed_data: bool = True) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_: FastAPI):
        Base.metadata.create_all(bind=database_engine)
        if seed_data and database_engine is engine:
            with SessionLocal() as db:
                seed_initial_data(db)
        yield

    application = FastAPI(
        title=settings.app_name,
        description="Enterprise IT service management and incident tracking.",
        version="1.0.0",
        lifespan=lifespan,
    )
    application.include_router(auth.router, prefix=settings.api_prefix)
    application.include_router(tickets.router, prefix=settings.api_prefix)
    application.include_router(admin.router, prefix=settings.api_prefix)
    application.include_router(assets.router, prefix=settings.api_prefix)
    application.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

    @application.get("/", include_in_schema=False)
    def serve_frontend():
        return FileResponse(
            FRONTEND_DIR / "index.html",
            headers={"Cache-Control": "no-store"},
        )

    @application.get("/health", tags=["health"])
    def health():
        return {"status": "ok", "service": settings.app_name}

    return application


app = create_app()
