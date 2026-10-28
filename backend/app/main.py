import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.health import router as health_router
from app.core.config import settings
from app.services.waymark_worker import serving_worker_owner


@asynccontextmanager
async def lifespan(app):
    owner_context = serving_worker_owner()
    owner_context.__enter__()
    try:
        yield
    finally:
        await asyncio.to_thread(owner_context.__exit__, None, None, None)


def create_app() -> FastAPI:
    app = FastAPI(title=settings.app_name, lifespan=lifespan)
    app.include_router(health_router)
    return app


app = create_app()

