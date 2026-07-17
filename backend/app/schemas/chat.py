from typing import Any

from pydantic import BaseModel


class ChatMessage(BaseModel):
    role: str
    content: Any


class ChatRequest(BaseModel):
    session_id: str
    text: str
    history: list[ChatMessage] = []


class ChatResponse(BaseModel):
    reply: str
    tools_invoked: list[dict[str, Any]] = []
    critic: dict[str, Any] | None = None


class SosRequest(BaseModel):
    session_id: str
    region: str
    nationality: str


class SosResponse(BaseModel):
    hotlines: list[dict[str, Any]]
    embassy: dict[str, Any] | None
