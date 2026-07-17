from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.db.postgres import close_pool, ensure_runtime_schema, init_pool
from app.db.qdrant import ensure_collections
from app.routers import chat, health, sessions, sos


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_pool()
    await ensure_runtime_schema()
    await ensure_collections()
    yield
    await close_pool()


app = FastAPI(title="AITravelMate", lifespan=lifespan)

app.include_router(health.router)
app.include_router(sessions.router)
app.include_router(chat.router)
app.include_router(sos.router)
