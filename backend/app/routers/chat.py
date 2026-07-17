from fastapi import APIRouter

from app.agent.orchestrator import handle_turn
from app.schemas.chat import ChatRequest, ChatResponse

router = APIRouter()


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    history = [m.model_dump() for m in request.history]
    result = await handle_turn(request.text, history=history)
    return ChatResponse(**result)
