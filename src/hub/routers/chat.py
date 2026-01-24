"""Chat/inference endpoints - OpenAI compatible.

Routes LLM requests through TensorZero embedded gateway with fallback support.
When enable_tools=true, Hub runs the agent loop and executes tools.
When enable_tools=false (default for Spoke pass-through), Hub just returns LLM response.

File Summary:
- ChatCompletionRequest: Request model with enable_tools parameter
- chat_completions: Main endpoint that routes to agent loop or pass-through
- _run_agent_loop: Executes tools and continues conversation until done
- _call_tensorzero: Simple pass-through to LLM (no tool execution)
"""

import json
import logging
import time
import uuid
from typing import Any, AsyncIterator, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import get_current_device
from ..config import settings
from ..database import Device, get_db
from ..tensorzero_gateway import inference as tz_inference
from shared.normalization import normalize_device_name

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["chat"])


class ChatMessage(BaseModel):
    """A single chat message."""
    role: Literal["system", "user", "assistant", "tool"]
    content: str
    tool_call_id: Optional[str] = None
    name: Optional[str] = None


class ChatCompletionRequest(BaseModel):
    """OpenAI-compatible chat completion request with tool execution control.
    
    Attributes:
        enable_tools: If True, Hub runs agent loop and executes tools.
                     If False, Hub just passes through to LLM (Spoke handles tools).
    """
    model: str = "gpt-4o-mini"
    messages: List[ChatMessage]
    temperature: Optional[float] = 0.7
    max_tokens: Optional[int] = None
    stream: bool = False
    enable_tools: bool = False


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


def _normalize_messages(
    messages: List[ChatMessage],
    include_tool_call_id: bool = False,
) -> list[dict[str, Any]]:
    """Normalize chat messages for TensorZero input.

    Args:
        messages: The incoming chat messages in OpenAI-compatible format.
        include_tool_call_id: Whether to include tool_call_id metadata in tool
            result prefixes.

    Returns:
        Normalized message dictionaries compatible with TensorZero input.
    """
    normalized: list[dict[str, Any]] = []

    for message in messages:
        if message.role in ("user", "assistant"):
            normalized.append({"role": message.role, "content": message.content})
            continue

        if message.role == "system":
            # Preserve system prompt content but avoid `system` role.
            normalized.append({"role": "user", "content": message.content})
            continue

        if message.role == "tool":
            # OpenAI tool-result messages include tool_call_id and optionally name.
            prefix_parts = ["[Tool Result]"]
            if message.name:
                prefix_parts.append(f"name={message.name}")
            if include_tool_call_id and message.tool_call_id:
                prefix_parts.append(f"tool_call_id={message.tool_call_id}")
            prefix = " ".join(prefix_parts)
            normalized.append({"role": "user", "content": f"{prefix}\n{message.content}"})

    return normalized


@router.post("/v1/chat/completions")
async def chat_completions(
    request: ChatCompletionRequest,
    device: Device = Depends(get_current_device),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """OpenAI-compatible chat completions endpoint.
    
    Routes requests through TensorZero embedded gateway with automatic
    fallback between configured providers.
    
    When enable_tools=True, Hub runs the agent loop and executes tools.
    When enable_tools=False (default), Hub just passes through to LLM.
    """
    logger.info(
        "[Chat] Received request: enable_tools=%s stream=%s messages=%s",
        request.enable_tools,
        request.stream,
        len(request.messages),
    )

    if request.stream:
        stream_iter = _stream_chat_completions(request=request, device=device, db=db)
        return StreamingResponse(stream_iter, media_type="text/event-stream")

    if request.enable_tools:
        logger.info("[Chat] Routing to agent loop (enable_tools=True)")
        return await _run_agent_loop(request, device, db)
    logger.info("[Chat] Routing to pass-through (enable_tools=False)")
    return await _call_tensorzero(request, use_tools=False)


def _sse(data: dict[str, Any]) -> str:
    """Format a single Server-Sent Event payload.

    Args:
        data: JSON-serializable object.

    Returns:
        SSE-formatted string.
    """
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


def _get_content_blocks(response: Any) -> list[Any]:
    """Return TensorZero content blocks from either object or dict responses.

    TensorZero's Python SDK has returned different shapes across versions:
    - an object with a `.content` attribute containing block objects
    - a plain dict with a `content` list containing dict blocks

    Args:
        response: The raw inference response.

    Returns:
        A list of content blocks (object or dict).
    """
    if hasattr(response, "content"):
        blocks = getattr(response, "content", None) or []
        if isinstance(blocks, list):
            return blocks
        return list(blocks)

    if isinstance(response, dict):
        blocks = response.get("content") or []
        return blocks if isinstance(blocks, list) else []

    return []


def _extract_text_from_block(block: Any) -> str:
    """Extract text from a single content block."""
    if hasattr(block, "text"):
        text = getattr(block, "text", "")
        return str(text) if text else ""
    if isinstance(block, dict) and block.get("type") == "text":
        text = block.get("text", "")
        return str(text) if text else ""
    return ""


def _extract_tool_call_from_block(block: Any) -> Optional[dict[str, Any]]:
    """Extract a tool call dict from a content block, if present."""
    # Object-style blocks (tests + some SDK versions)
    if hasattr(block, "type") and getattr(block, "type", None) == "tool_call":
        name = getattr(block, "name", None) or getattr(block, "raw_name", None)
        arguments: Any = getattr(block, "arguments", None)
        if not isinstance(arguments, dict):
            raw_args = getattr(block, "raw_arguments", None)
            if raw_args and isinstance(raw_args, str):
                try:
                    arguments = json.loads(raw_args)
                except json.JSONDecodeError:
                    arguments = {}
            else:
                arguments = {}
        return {
            "id": str(getattr(block, "id", "") or ""),
            "name": str(name) if name else "",
            "arguments": arguments,
        }

    # Dict-style blocks (observed in some gateway returns)
    if isinstance(block, dict) and block.get("type") == "tool_call":
        name = block.get("name") or block.get("raw_name") or ""
        arguments: Any = block.get("arguments")
        if not isinstance(arguments, dict):
            raw_args = block.get("raw_arguments")
            if raw_args and isinstance(raw_args, str):
                try:
                    arguments = json.loads(raw_args)
                except json.JSONDecodeError:
                    arguments = {}
            else:
                arguments = {}
        return {
            "id": str(block.get("id") or ""),
            "name": str(name),
            "arguments": arguments,
        }

    return None


async def _stream_chat_completions(
    request: ChatCompletionRequest,
    device: Device,
    db: AsyncSession,
) -> AsyncIterator[str]:
    """Stream a chat completion response as SSE events.

    This is *not* token streaming from the model. Instead, it streams:
    - tool_call_started
    - tool_call_result
    - final assistant_message

    Args:
        request: Chat completion request.
        device: Authenticated device.
        db: Database session.

    Yields:
        SSE data frames.
    """
    try:
        if request.enable_tools:
            async for event in _agent_loop_events(request=request, device=device, db=db):
                yield _sse(event)
        else:
            # Pass-through: single response.
            response = await _call_tensorzero(request, use_tools=False)
            content = response.choices[0].message.content
            yield _sse({"type": "assistant_message", "content": content})
        yield _sse({"type": "done"})
    except HTTPException as e:
        yield _sse({"type": "error", "error": str(e.detail)})
    except Exception as e:
        logger.exception("[Chat Stream] Streaming failed")
        yield _sse({"type": "error", "error": str(e)})


async def _agent_loop_events(
    request: ChatCompletionRequest,
    device: Device,
    db: AsyncSession,
) -> AsyncIterator[dict[str, Any]]:
    """Run agent loop and yield structured events.

    This is the shared implementation used by both:
    - streaming SSE responses
    - classic JSON responses (non-streaming)
    """
    from .websocket import connection_manager
    from ..skill_service import HubSkillService

    skill_service = HubSkillService(
        db=db,
        user_id=device.user_id,
        connection_manager=connection_manager,
    )

    messages: List[Dict[str, Any]] = []
    system_prompt = await skill_service.get_system_prompt(
        requesting_device_key=normalize_device_name(device.name or "")
    )
    messages.extend(_normalize_messages(request.messages, include_tool_call_id=False))
    max_iterations = settings.agent_max_iterations

    final_content = ""
    model_used = "unknown"
    had_any_tool_execution = False
    did_empty_text_retry = False
    repeated_across_iterations: dict[str, int] = {}

    for iteration in range(max_iterations):
        _ = iteration
        response = await tz_inference(
            messages=messages,
            function_name="chat",
            system=system_prompt,
        )

        content = ""
        tool_calls: list[dict[str, Any]] = []

        blocks = _get_content_blocks(response)
        block_types: list[str] = []
        for block in blocks:
            if hasattr(block, "type"):
                block_types.append(str(getattr(block, "type") or "unknown"))
            elif isinstance(block, dict):
                block_types.append(str(block.get("type") or "unknown"))
            else:
                block_types.append(type(block).__name__)

        for block in blocks:
            content += _extract_text_from_block(block)
            tc = _extract_tool_call_from_block(block)
            if tc and tc.get("name"):
                tool_calls.append(tc)

        model_used = _extract_model(response)

        if not content.strip() and not tool_calls:
            logger.warning(
                "[Agent Loop] Empty model step. variant=%s iteration=%s blocks=%s",
                model_used,
                iteration,
                block_types,
            )

        if not tool_calls:
            if had_any_tool_execution and not content.strip() and not did_empty_text_retry:
                # Some providers occasionally return no text content blocks after tool results.
                # Nudge once to request a natural-language response.
                did_empty_text_retry = True
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "[System Note] The previous response contained no text. "
                            "Do NOT call tools again. Respond now in natural language using the tool results above."
                        ),
                    }
                )
                continue

            final_content = content
            break

        # Execute tool calls.
        tool_results: list[str] = []
        seen_execution_keys: set[str] = set()

        for tc in tool_calls:
            tool_call_id = str(tc.get("id") or "")
            yield {
                "type": "tool_call_started",
                "tool_call_id": tool_call_id,
                "tool_name": tc.get("name") or "",
                "arguments": tc.get("arguments") or {},
            }

            execution_key = f"{tc['name']}:{json.dumps(tc['arguments'] or {}, sort_keys=True, default=str)}"
            if execution_key in seen_execution_keys:
                logger.warning(
                    "[Agent Loop] Duplicate tool call in single response; skipping. tool=%s args=%s",
                    tc.get("name"),
                    tc.get("arguments"),
                )
                result = {"result": "(duplicate tool call skipped)"}
            else:
                seen_execution_keys.add(execution_key)
                repeated_across_iterations[execution_key] = (
                    repeated_across_iterations.get(execution_key, 0) + 1
                )
                if repeated_across_iterations[execution_key] > 1:
                    logger.warning(
                        "[Agent Loop] Tool call repeated across iterations. iteration=%s count=%s tool=%s args=%s",
                        iteration,
                        repeated_across_iterations[execution_key],
                        tc.get("name"),
                        tc.get("arguments"),
                    )
                result = await skill_service.execute_tool(tc["name"], tc["arguments"])
                had_any_tool_execution = True

            success = "result" in result
            result_str = str(result.get("result", "")) if success else None
            error_str = str(result.get("error", "")) if not success else None

            if success and (result_str is None or not result_str.strip()):
                # Many tools (notably python_exec) succeed but produce no stdout.
                # If we propagate an empty string, models often repeat the same call
                # indefinitely. Make the empty output explicit.
                result_str = "(no output)"
            if (not success) and (error_str is None or not error_str.strip()):
                error_str = "(unknown error)"

            yield {
                "type": "tool_call_result",
                "tool_call_id": tool_call_id,
                "tool_name": tc.get("name") or "",
                "success": success,
                "result": result_str,
                "error": error_str,
            }

            if success:
                tool_results.append(f"Tool {tc['name']}: {result_str}")
            else:
                tool_results.append(f"Tool {tc['name']} error: {error_str}")

        messages.append({"role": "assistant", "content": content})
        tool_output = "\n".join(tool_results)

        messages.append(
            {
                "role": "user",
                "content": (
                    f"[Tool Results]\n{tool_output}\n\n"
                    "[Now respond naturally to the user based on these results.]"
                ),
            }
        )
        final_content = content

    if not (final_content or "").strip():
        logger.warning(
            "[Agent Loop] Empty model response after tool execution loop. variant=%s",
            model_used,
        )
        final_content = (
            "I didn't get a usable response from the model (empty content blocks). "
            "Please try again."
        )

    yield {
        "type": "assistant_message",
        "content": final_content,
        "model": model_used,
        "usage": {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        },
    }


async def _run_agent_loop(
    request: ChatCompletionRequest,
    device: Device,
    db: AsyncSession,
) -> ChatCompletionResponse:
    """Run agent loop with tool execution.
    
    This is used when enable_tools=True (Hub executes tools).
    """
    # Consume the shared generator and construct the classic JSON response.
    final_content: Optional[str] = None
    model_used = "unknown"
    usage: dict[str, Any] = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

    async for event in _agent_loop_events(request=request, device=device, db=db):
        if not isinstance(event, dict):
            continue
        if str(event.get("type") or "") == "assistant_message":
            final_content = str(event.get("content") or "")
            model_used = str(event.get("model") or model_used)
            incoming_usage = event.get("usage")
            if isinstance(incoming_usage, dict):
                usage = incoming_usage

    if not (final_content or "").strip():
        final_content = (
            "I didn't get a usable response from the model (empty content blocks). "
            "Please try again."
        )

    return ChatCompletionResponse(
        id=f"chatcmpl-{uuid.uuid4().hex[:8]}",
        created=int(time.time()),
        model=model_used,
        choices=[
            ChatChoice(
                index=0,
                message=ChatMessage(role="assistant", content=final_content),
                finish_reason="stop",
            )
        ],
        usage=usage,
    )


async def _call_tensorzero(
    request: ChatCompletionRequest,
    use_tools: bool = False,
) -> ChatCompletionResponse:
    """Route request through TensorZero embedded gateway.
    
    TensorZero handles provider selection and fallback automatically.
    
    Args:
        request: The chat completion request
        use_tools: If False, uses chat_no_tools function (Spoke handles tools)
    """
    # Convert messages to TensorZero format.
    # Hub's embedded TensorZero function input expects message roles to be
    # compatible with its internal schema (commonly user/assistant). TensorZero
    # tool-calling flows can introduce roles like `system` and `tool`, so we
    # normalize those into `user` messages while preserving order.
    messages = _normalize_messages(request.messages, include_tool_call_id=True)
    
    # Choose function based on whether tools are enabled
    function_name = "chat" if use_tools else "chat_no_tools"
    
    try:
        response = await tz_inference(
            messages=messages,
            function_name=function_name,
        )
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=f"LLM inference failed: {e}",
        )
    
    # Extract content from TensorZero response
    content = _extract_content(response)
    if not (content or "").strip():
        model_used = _extract_model(response)
        raise HTTPException(
            status_code=502,
            detail=(
                "LLM returned an empty response (no content blocks). "
                f"variant={model_used}"
            ),
        )
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
    parts: list[str] = []
    for block in _get_content_blocks(response):
        text = _extract_text_from_block(block)
        if text:
            parts.append(text)
    return "".join(parts)


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

