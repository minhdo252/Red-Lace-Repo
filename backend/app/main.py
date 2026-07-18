from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.ai.client import ai_client
from app.db.postgres import close_pool, ensure_runtime_schema, init_pool
from app.db.qdrant import close_client as close_qdrant_client
from app.db.qdrant import ensure_collections
from app.routers import chat, health, sessions, sos


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        await init_pool()
        await ensure_runtime_schema()
        await ensure_collections()
        yield
    finally:
        try:
            await ai_client.close()
        finally:
            try:
                await close_qdrant_client()
            finally:
                await close_pool()


app = FastAPI(title="AITravelMate", lifespan=lifespan)

app.include_router(health.router)
app.include_router(sessions.router)
app.include_router(chat.router)
app.include_router(sos.router)
