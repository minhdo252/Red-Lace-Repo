from typing import Any

from pydantic import BaseModel


class ChatMessage(BaseModel):
    role: str
    content: Any


class ImagePayload(BaseModel):
    """One image attached to a /chat turn. mode picks the read_image()
    prompt (see app/modules/image_reader.py) — e.g. mode="page_transparency"
    for module 2.2 signal 2. The orchestrator reads these itself before the
    model sees the turn; a model can't be handed raw image bytes back as a
    tool-call argument it never actually received as text."""

    mode: str
    image_base64: str


class ChatRequest(BaseModel):
    session_id: str
    text: str
    history: list[ChatMessage] = []
    images: list[ImagePayload] = []


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
