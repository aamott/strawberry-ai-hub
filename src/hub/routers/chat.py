"""Chat/inference endpoints - OpenAI compatible.

Routes LLM requests through TensorZero embedded gateway with fallback support.
"""

import time
import uuid
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..auth import get_current_device
from ..database import Device
from ..tensorzero_gateway import inference as tz_inference

router = APIRouter(prefix="/api", tags=["chat"])


class ChatMessage(BaseModel):
    """A single chat message."""
    role: Literal["system", "user", "assistant", "tool"]
    content: str
    tool_call_id: Optional[str] = None
    name: Optional[str] = None


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
    usage: Optional[Dict[str, Any]] = None


@router.post("/v1/chat/completions", response_model=ChatCompletionResponse)
async def chat_completions(
    request: ChatCompletionRequest,
    device: Device = Depends(get_current_device),
) -> ChatCompletionResponse:
    """OpenAI-compatible chat completions endpoint.
    
    Routes requests through TensorZero embedded gateway with automatic
    fallback between configured providers (OpenAI -> Gemini).
    """
    return await _call_tensorzero(request)


async def _call_tensorzero(request: ChatCompletionRequest) -> ChatCompletionResponse:
    """Route request through TensorZero embedded gateway.
    
    TensorZero handles provider selection and fallback automatically.
    """
    # Convert messages to TensorZero format.
    # Hub's embedded TensorZero function input expects message roles to be
    # compatible with its internal schema (commonly user/assistant). TensorZero
    # tool-calling flows can introduce roles like `system` and `tool`, so we
    # normalize those into `user` messages while preserving order.
    messages: list[dict[str, Any]] = []
    for m in request.messages:
        if m.role in ("user", "assistant"):
            messages.append({"role": m.role, "content": m.content})
            continue

        if m.role == "system":
            # Preserve system prompt content but avoid `system` role.
            messages.append({"role": "user", "content": m.content})
            continue

        if m.role == "tool":
            # OpenAI tool-result messages include `tool_call_id` and sometimes `name`.
            # Preserve the information in-band so the model can continue.
            prefix_parts = ["[Tool Result]"]
            if m.name:
                prefix_parts.append(f"name={m.name}")
            if m.tool_call_id:
                prefix_parts.append(f"tool_call_id={m.tool_call_id}")
            prefix = " ".join(prefix_parts)
            messages.append({"role": "user", "content": f"{prefix}\n{m.content}"})
            continue
    
    try:
        response = await tz_inference(
            messages=messages,
            function_name="chat",
        )
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=f"LLM inference failed: {e}",
        )
    
    # Extract content from TensorZero response
    content = _extract_content(response)
    model_used = _extract_model(response)
    
    return ChatCompletionResponse(
        id=f"chatcmpl-{uuid.uuid4().hex[:8]}",
        created=int(time.time()),
        model=model_used,
        choices=[
            ChatChoice(
                index=0,
                message=ChatMessage(role="assistant", content=content),
                finish_reason="stop",
            )
        ],
        usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    )


def _extract_content(response: Any) -> str:
    """Extract text content from TensorZero inference response."""
    # TensorZero returns response with content attribute
    if hasattr(response, "content"):
        # Content is a list of ContentBlock objects
        content_blocks = response.content
        if content_blocks:
            # Get text from first block
            block = content_blocks[0]
            if hasattr(block, "text"):
                return block.text
    
    # Fallback: try dict access
    if isinstance(response, dict):
        content = response.get("content", [])
        if content and isinstance(content[0], dict):
            return content[0].get("text", "")
    
    return str(response)


def _extract_model(response: Any) -> str:
    """Extract model name from TensorZero inference response."""
    if hasattr(response, "variant_name"):
        return response.variant_name
    if isinstance(response, dict):
        return response.get("variant_name", "unknown")
    return "unknown"


# Also expose as /inference for TensorZero compatibility
@router.post("/inference")
async def inference(
    request: ChatCompletionRequest,
    device: Device = Depends(get_current_device),
) -> ChatCompletionResponse:
    """TensorZero-style inference endpoint."""
    return await chat_completions(request, device)

