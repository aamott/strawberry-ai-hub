"""Pydantic models for the chat router.

OpenAI-compatible request/response models and shared helpers.
"""

import time
import uuid
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel


class ChatMessage(BaseModel):
    """A single chat message."""

    role: Literal["system", "user", "assistant", "tool"]
    content: str
    tool_call_id: Optional[str] = None
    name: Optional[str] = None


_VALID_TOOL_MODES = {"python_exec", "native"}


class ChatCompletionRequest(BaseModel):
    """OpenAI-compatible chat completion request with tool execution control.

    Attributes:
        enable_tools: If True, Hub runs agent loop and executes tools.
                     If False, Hub just passes through to LLM (Spoke handles tools).
        tool_mode: ``"python_exec"`` (default) or ``"native"``.
            Locked after the first message in a session.
    """

    model: str = "gpt-4o-mini"
    messages: List[ChatMessage]
    temperature: Optional[float] = 0.7
    max_tokens: Optional[int] = None
    stream: bool = False
    enable_tools: bool = False
    session_id: Optional[str] = None
    tool_mode: Optional[str] = None


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


def build_chat_response(
    content: str,
    model: str = "unknown",
    usage: Optional[Dict[str, Any]] = None,
) -> ChatCompletionResponse:
    """Build a standard ChatCompletionResponse.

    Centralises the response construction used by both
    ``_run_agent_loop`` and ``_call_tensorzero``.

    Args:
        content: The assistant's text response.
        model: Model/variant name.
        usage: Token usage dict.

    Returns:
        A populated ChatCompletionResponse.
    """
    return ChatCompletionResponse(
        id=f"chatcmpl-{uuid.uuid4().hex[:8]}",
        created=int(time.time()),
        model=model,
        choices=[
            ChatChoice(
                index=0,
                message=ChatMessage(
                    role="assistant", content=content,
                ),
                finish_reason="stop",
            )
        ],
        usage=usage or {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        },
    )
