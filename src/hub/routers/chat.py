"""Chat/inference endpoints - OpenAI compatible."""

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
import httpx

from ..config import settings
from ..database import Device
from ..auth import get_current_device

router = APIRouter(tags=["chat"])


class ChatMessage(BaseModel):
    """A single chat message."""
    role: str  # system, user, assistant
    content: str


class ChatCompletionRequest(BaseModel):
    """OpenAI-compatible chat completion request."""
    model: str = "gpt-4o-mini"
    messages: List[ChatMessage]
    temperature: Optional[float] = 0.7
    max_tokens: Optional[int] = None
    stream: bool = False


class ChatChoice(BaseModel):
    """A single completion choice."""
    index: int
    message: ChatMessage
    finish_reason: str


class ChatCompletionResponse(BaseModel):
    """OpenAI-compatible chat completion response."""
    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: List[ChatChoice]


@router.post("/v1/chat/completions", response_model=ChatCompletionResponse)
async def chat_completions(
    request: ChatCompletionRequest,
    device: Device = Depends(get_current_device),
):
    """OpenAI-compatible chat completions endpoint.
    
    Routes requests to the configured LLM provider.
    """
    # Determine which API to use
    if settings.google_ai_studio_api_key:
        return await _call_google_ai(request)
    elif settings.openai_api_key:
        return await _call_openai(request)
    else:
        raise HTTPException(
            status_code=500,
            detail="No LLM API key configured",
        )


async def _call_openai(request: ChatCompletionRequest) -> ChatCompletionResponse:
    """Call OpenAI API."""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{settings.openai_base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {settings.openai_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": request.model or settings.default_model,
                "messages": [m.model_dump() for m in request.messages],
                "temperature": request.temperature,
                "max_tokens": request.max_tokens,
            },
            timeout=60.0,
        )
        
        if response.status_code != 200:
            raise HTTPException(
                status_code=response.status_code,
                detail=f"OpenAI API error: {response.text}",
            )
        
        return ChatCompletionResponse(**response.json())


async def _call_google_ai(request: ChatCompletionRequest) -> ChatCompletionResponse:
    """Call Google AI Studio (Gemini) API.
    
    Converts OpenAI format to Gemini format and back.
    """
    import time
    import uuid
    
    # Convert messages to Gemini format
    gemini_contents = []
    system_instruction = None
    
    for msg in request.messages:
        if msg.role == "system":
            system_instruction = msg.content
        elif msg.role == "user":
            gemini_contents.append({
                "role": "user",
                "parts": [{"text": msg.content}]
            })
        elif msg.role == "assistant":
            gemini_contents.append({
                "role": "model",
                "parts": [{"text": msg.content}]
            })
    
    # Build request body
    body = {
        "contents": gemini_contents,
        "generationConfig": {
            "temperature": request.temperature or 0.7,
        }
    }
    
    if system_instruction:
        body["systemInstruction"] = {
            "parts": [{"text": system_instruction}]
        }
    
    if request.max_tokens:
        body["generationConfig"]["maxOutputTokens"] = request.max_tokens
    
    # Call Gemini API
    model = "gemini-2.0-flash"  # Default Gemini model
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    
    async with httpx.AsyncClient() as client:
        response = await client.post(
            url,
            params={"key": settings.google_ai_studio_api_key},
            json=body,
            timeout=60.0,
        )
        
        if response.status_code != 200:
            raise HTTPException(
                status_code=response.status_code,
                detail=f"Gemini API error: {response.text}",
            )
        
        data = response.json()
    
    # Convert response to OpenAI format
    try:
        candidate = data["candidates"][0]
        content = candidate["content"]["parts"][0]["text"]
        finish_reason = candidate.get("finishReason", "stop").lower()
    except (KeyError, IndexError) as e:
        raise HTTPException(
            status_code=500,
            detail=f"Unexpected Gemini response format: {e}",
        )
    
    return ChatCompletionResponse(
        id=f"chatcmpl-{uuid.uuid4().hex[:8]}",
        created=int(time.time()),
        model=model,
        choices=[
            ChatChoice(
                index=0,
                message=ChatMessage(role="assistant", content=content),
                finish_reason=finish_reason,
            )
        ],
    )


# Also expose as /inference for TensorZero compatibility
@router.post("/inference")
async def inference(
    request: ChatCompletionRequest,
    device: Device = Depends(get_current_device),
):
    """TensorZero-style inference endpoint."""
    return await chat_completions(request, device)

