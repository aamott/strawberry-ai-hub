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
import re as _re
import time
import uuid
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import get_current_device
from ..config import settings
from ..database import Device, Message, Session, get_db
from ..tensorzero_gateway import inference as tz_inference
from ..tensorzero_gateway import inference_stream as tz_inference_stream
from ..utils import normalize_device_name
from .websocket import ConnectionManager, get_connection_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["chat"])


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


async def _get_session_for_user(
    db: AsyncSession,
    session_id: str,
    user_id: str,
) -> Session:
    """Load a session scoped to the current user.

    Args:
        db: Active database session.
        session_id: Identifier for the session.
        user_id: User identifier for access control.

    Returns:
        The matching Session row.

    Raises:
        HTTPException: If the session does not exist for the user.
    """
    result = await db.execute(
        select(Session).where(
            Session.id == session_id,
            Session.user_id == user_id,
        )
    )
    session = result.scalar_one_or_none()

    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    return session


def _resolve_tool_mode(
    request: ChatCompletionRequest,
    session: Optional[Session],
) -> str:
    """Determine the effective tool mode for this request.

    If the session already has a locked ``tool_mode``, that wins.
    Otherwise the request's ``tool_mode`` is used (defaulting to
    ``"python_exec"``).  The resolved mode is written back onto
    the session so subsequent messages are locked in.

    Returns:
        ``"python_exec"`` or ``"native"``.
    """
    if session and session.tool_mode:
        return session.tool_mode

    requested = request.tool_mode or "python_exec"
    if requested not in _VALID_TOOL_MODES:
        requested = "python_exec"

    # Lock the mode onto the session
    if session is not None:
        session.tool_mode = requested

    return requested


def _extract_latest_user_message(
    messages: List[ChatMessage],
) -> Optional[str]:
    """Extract the latest user message content from a chat request."""
    for message in reversed(messages):
        if message.role == "user" and message.content.strip():
            return message.content
    return None


async def _append_session_message(
    db: AsyncSession,
    session: Session,
    role: str,
    content: str,
) -> None:
    """Append a message to a session and update cached session metadata."""
    now = datetime.now(timezone.utc)
    message = Message(
        session_id=session.id,
        role=role,
        content=content,
        created_at=now,
    )
    db.add(message)

    session.last_activity = now
    session.message_count += 1

    if session.title is None and role == "user":
        session.title = content[:50] + ("..." if len(content) > 50 else "")

    await db.commit()


@router.post("/v1/chat/completions")
async def chat_completions(
    request: ChatCompletionRequest,
    device: Device = Depends(get_current_device),
    db: AsyncSession = Depends(get_db),
    manager: ConnectionManager = Depends(get_connection_manager),
) -> Any:
    """OpenAI-compatible chat completions endpoint.

    Routes requests through TensorZero embedded gateway with automatic
    fallback between configured providers.

    When enable_tools=True, Hub runs the agent loop and executes tools.
    When enable_tools=False (default), Hub just passes through to LLM.
    """
    logger.info(
        "[Chat] Received request: enable_tools=%s stream=%s messages=%s tool_mode=%s",
        request.enable_tools,
        request.stream,
        len(request.messages),
        request.tool_mode,
    )

    session: Optional[Session] = None
    if request.session_id:
        session = await _get_session_for_user(
            db, request.session_id, device.user_id
        )

        latest_user_message = _extract_latest_user_message(
            request.messages
        )
        if latest_user_message:
            await _append_session_message(
                db, session, "user", latest_user_message
            )

    # Resolve and lock tool mode for this session
    tool_mode = _resolve_tool_mode(request, session)
    if session and session.tool_mode:
        await db.commit()

    if request.stream:
        stream_iter = _stream_chat_completions(
            request=request,
            device=device,
            db=db,
            manager=manager,
            session=session,
            tool_mode=tool_mode,
        )
        return StreamingResponse(
            stream_iter, media_type="text/event-stream"
        )

    if request.enable_tools:
        logger.info(
            "[Chat] Routing to agent loop (enable_tools=True, tool_mode=%s)",
            tool_mode,
        )
        response = await _run_agent_loop(
            request, device, db, manager, tool_mode=tool_mode
        )
    else:
        logger.info("[Chat] Routing to pass-through (enable_tools=False)")
        response = await _call_tensorzero(request, use_tools=False)

    if session is not None:
        assistant_content = response.choices[0].message.content
        if assistant_content.strip():
            await _append_session_message(db, session, "assistant", assistant_content)

    return response


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
    manager: ConnectionManager,
    session: Optional[Session] = None,
    tool_mode: str = "python_exec",
) -> AsyncIterator[str]:
    """Stream a chat completion response as SSE events.

    Streams token-level ``content_delta`` events for the final LLM
    response so the UI can display text as it is generated.  Tool call
    events (``tool_call_started``, ``tool_call_result``) are emitted
    non-streaming since we need the full response to detect tool calls.

    Yields:
        SSE data frames.
    """
    final_assistant_content = ""

    try:
        if request.enable_tools:
            async for event in _agent_loop_events(
                request=request,
                device=device,
                db=db,
                manager=manager,
                tool_mode=tool_mode,
            ):
                if event.get("type") == "assistant_message":
                    final_assistant_content = str(event.get("content") or "")
                yield _sse(event)
        else:
            # Pass-through: stream the response token-by-token.
            messages = _normalize_messages(request.messages, include_tool_call_id=True)
            collected = await _stream_inference_as_deltas(
                messages=messages,
                function_name="chat_no_tools",
            )
            for delta_event in collected["deltas"]:
                yield _sse(delta_event)
            final_assistant_content = collected["full_text"]
            yield _sse({"type": "assistant_message", "content": final_assistant_content})

        if session is not None and final_assistant_content.strip():
            await _append_session_message(
                db,
                session,
                "assistant",
                final_assistant_content,
            )

        yield _sse({"type": "done"})
    except HTTPException as e:
        yield _sse({"type": "error", "error": str(e.detail)})
    except Exception as e:
        logger.exception("[Chat Stream] Streaming failed")
        yield _sse({"type": "error", "error": str(e)})


def _classify_block_type(block: Any) -> str:
    """Return a string label for a content block's type."""
    if hasattr(block, "type"):
        return str(getattr(block, "type") or "unknown")
    if isinstance(block, dict):
        return str(block.get("type") or "unknown")
    return type(block).__name__


def _parse_response_blocks(
    response: Any,
    iteration: int = 0,
) -> tuple[str, list[dict[str, Any]], str, list[Any]]:
    """Extract text, tool calls, model, and raw blocks from a response.

    Logs a warning when both text and tool calls are empty.

    Returns:
        Tuple of (content, tool_calls, model_used, raw_blocks).
        ``raw_blocks`` is the original content list from the response,
        needed for native-mode message history.
    """
    blocks = _get_content_blocks(response)
    block_types = [_classify_block_type(b) for b in blocks]

    content = ""
    tool_calls: list[dict[str, Any]] = []
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

    return content, tool_calls, model_used, blocks


async def _execute_single_tool(
    tc: dict[str, Any],
    skill_service: Any,
    seen_keys: set[str],
    repeated: dict[str, int],
    iteration: int,
) -> tuple[dict[str, Any], bool]:
    """Execute one tool call, handling duplicates and repeats.

    Returns:
        Tuple of (result dict, was_executed).
    """
    execution_key = (
        f"{tc['name']}:{json.dumps(tc['arguments'] or {}, sort_keys=True, default=str)}"
    )

    if execution_key in seen_keys:
        logger.warning(
            "[Agent Loop] Duplicate tool call in single response; skipping."
            " tool=%s args=%s",
            tc.get("name"),
            tc.get("arguments"),
        )
        return {"result": "(duplicate tool call skipped)"}, False

    seen_keys.add(execution_key)
    repeated[execution_key] = repeated.get(execution_key, 0) + 1
    if repeated[execution_key] > 1:
        logger.warning(
            "[Agent Loop] Tool call repeated across iterations."
            " iteration=%s count=%s tool=%s args=%s",
            iteration,
            repeated[execution_key],
            tc.get("name"),
            tc.get("arguments"),
        )

    result = await skill_service.execute_tool(tc["name"], tc["arguments"])
    return result, True


def _format_tool_result(
    result: dict[str, Any],
) -> tuple[bool, Optional[str], Optional[str]]:
    """Normalise a tool result into (success, result_str, error_str)."""
    success = "result" in result
    result_str = str(result.get("result", "")) if success else None
    error_str = str(result.get("error", "")) if not success else None

    if success and (result_str is None or not result_str.strip()):
        result_str = "(no output)"
    if (not success) and (error_str is None or not error_str.strip()):
        error_str = "(unknown error)"
    return success, result_str, error_str


async def _execute_tool_calls(
    tool_calls: list[dict[str, Any]],
    skill_service: Any,
    seen_keys: set[str],
    repeated: dict[str, int],
    iteration: int,
) -> AsyncIterator[dict[str, Any]]:
    """Execute a batch of tool calls, yielding SSE events.

    Yields ``tool_call_started`` and ``tool_call_result`` events, then
    a final internal ``_tool_summary`` pseudo-event with ``results``
    (list[str]) and ``had_execution`` (bool) keys.
    """
    tool_results: list[str] = []
    had_execution = False

    for tc in tool_calls:
        tool_call_id = str(tc.get("id") or "")
        yield {
            "type": "tool_call_started",
            "tool_call_id": tool_call_id,
            "tool_name": tc.get("name") or "",
            "arguments": tc.get("arguments") or {},
        }

        result, was_executed = await _execute_single_tool(
            tc,
            skill_service,
            seen_keys,
            repeated,
            iteration,
        )
        if was_executed:
            had_execution = True

        success, result_str, error_str = _format_tool_result(result)

        yield {
            "type": "tool_call_result",
            "tool_call_id": tool_call_id,
            "tool_name": tc.get("name") or "",
            "success": success,
            "result": result_str,
            "error": error_str,
        }

        label = tc["name"]
        if success:
            tool_results.append(f"Tool {label}: {result_str}")
        else:
            tool_results.append(f"Tool {label} error: {error_str}")

    yield {
        "type": "_tool_summary",
        "results": tool_results,
        "had_execution": had_execution,
    }


def _handle_no_tool_calls(
    messages: list[dict[str, Any]],
    content: str,
    had_tool_execution: bool,
    already_retried: bool,
) -> str:
    """Decide what to do when the model returns no tool calls.

    Returns ``"retry"`` if we should nudge the model, or ``"done"``
    to accept the current content.
    """
    if _should_retry_empty_text(had_tool_execution, content, already_retried):
        messages.append({"role": "user", "content": _EMPTY_TEXT_NUDGE})
        return "retry"
    return "done"


def _should_retry_empty_text(
    had_tool_execution: bool,
    content: str,
    already_retried: bool,
) -> bool:
    """Check if we should nudge the LLM for a text response."""
    return had_tool_execution and not content.strip() and not already_retried


_EMPTY_TEXT_NUDGE = (
    "[System Note] The previous response contained no text. "
    "Do NOT call tools again. Respond now in natural language "
    "using the tool results above."
)


def _inject_tool_results(
    messages: list[dict[str, Any]],
    tool_mode: str,
    content: str,
    raw_blocks: list[Any],
    tool_results: list[str],
    tool_calls: list[dict[str, Any]],
    per_tool_results: list[dict[str, Any]],
) -> dict[str, Any]:
    """Append assistant + tool-result messages to the conversation.

    Returns an ``injected_message`` event dict for the caller to yield.
    """
    if tool_mode == "native":
        messages.append({"role": "assistant", "content": raw_blocks})
        blocks = _build_native_tool_result_blocks(tool_calls, per_tool_results)
        messages.append({"role": "user", "content": blocks})
        return {
            "type": "injected_message",
            "role": "user",
            "content": json.dumps(blocks, default=str),
        }

    messages.append({"role": "assistant", "content": content})
    tool_output = "\n".join(tool_results)
    injected = (
        f"[Tool Results]\n{tool_output}\n\n"
        "[Now respond naturally to the user based on these results.]"
    )
    messages.append({"role": "user", "content": injected})
    return {
        "type": "injected_message",
        "role": "user",
        "content": injected,
    }


def _build_native_tool_result_blocks(
    tool_calls: list[dict[str, Any]],
    per_tool_results: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build TensorZero ``tool_result`` content blocks for native mode.

    Each block maps a tool call ID to its result string, matching the
    format expected by TensorZero for multi-turn tool-use conversations.

    Args:
        tool_calls: Tool call dicts (with ``id`` and ``name``).
        per_tool_results: Corresponding ``tool_call_result`` events.

    Returns:
        List of ``{"type": "tool_result", "id": ..., "name": ..., "result": ...}``
        dicts.
    """
    result_by_id: dict[str, dict[str, Any]] = {}
    for evt in per_tool_results:
        tcid = evt.get("tool_call_id") or ""
        result_by_id[tcid] = evt

    blocks: list[dict[str, Any]] = []
    for tc in tool_calls:
        tcid = str(tc.get("id") or "")
        evt = result_by_id.get(tcid, {})
        result_str = str(evt.get("result") or evt.get("error") or "(no output)")
        blocks.append({
            "type": "tool_result",
            "id": tcid,
            "name": tc.get("name") or "",
            "result": result_str,
        })
    return blocks


async def _build_native_tz_kwargs(
    skill_service: Any,
    tool_mode: str,
) -> dict[str, Any]:
    """Build extra TensorZero kwargs for native tool mode.

    Returns an empty dict for python_exec mode, or ``additional_tools``
    and ``allowed_tools`` for native mode.
    """
    if tool_mode != "native":
        return {}

    tool_schemas, tool_names = (
        await skill_service.get_native_tool_schemas()
    )
    if not tool_schemas:
        return {}

    return {
        "additional_tools": tool_schemas,
        "allowed_tools": (
            ["search_skills", "describe_function"] + tool_names
        ),
    }


async def _finalize_agent_content(
    content: str,
    had_tool_exec: bool,
    tool_mode: str,
    messages: list[dict[str, Any]],
    system_prompt: str,
    tz_kwargs: dict[str, Any],
    model_used: str,
) -> str:
    """Ensure we have text content; run a fallback inference if needed."""
    if (content or "").strip():
        return content

    # Native mode: extra inference with tool_choice=none
    if had_tool_exec and tool_mode == "native":
        fb = await _native_text_fallback(messages, system_prompt, tz_kwargs)
        if fb.strip():
            return fb

    logger.warning(
        "[Agent Loop] Empty model response after tool execution loop. variant=%s",
        model_used,
    )
    return (
        "I didn't get a usable response from the model"
        " (empty content blocks). Please try again."
    )


async def _native_text_fallback(
    messages: list[dict[str, Any]],
    system_prompt: str,
    tz_kwargs: dict[str, Any],
) -> str:
    """Force-generate a text summary after a native tool loop.

    Appends a nudge message and calls inference with
    ``tool_choice='none'`` so the model must produce text.
    """
    logger.debug("[Agent Loop][native] Running text fallback inference")
    messages.append({"role": "user", "content": _EMPTY_TEXT_NUDGE})
    fallback_kwargs = dict(tz_kwargs)
    fallback_kwargs["tool_choice"] = "none"
    try:
        response = await tz_inference(
            messages=messages,
            function_name="chat",
            system=system_prompt,
            **fallback_kwargs,
        )
        content, _, _, _ = _parse_response_blocks(response)
        return content
    except Exception:
        logger.exception("[Agent Loop][native] Text fallback failed")
        return ""


async def _agent_loop_events(
    request: ChatCompletionRequest,
    device: Device,
    db: AsyncSession,
    manager: ConnectionManager,
    tool_mode: str = "python_exec",
) -> AsyncIterator[dict[str, Any]]:
    """Run agent loop and yield structured events.

    This is the shared implementation used by both:
    - streaming SSE responses
    - classic JSON responses (non-streaming)

    Args:
        tool_mode: ``"python_exec"`` or ``"native"``.
    """
    from ..skill_service import HubSkillService

    skill_service = HubSkillService(
        db=db,
        user_id=device.user_id,
        connection_manager=manager,
    )

    messages: List[Dict[str, Any]] = []
    system_prompt = await skill_service.get_system_prompt(
        requesting_device_key=normalize_device_name(
            device.name or ""
        ),
        tool_mode=tool_mode,
    )
    messages.extend(
        _normalize_messages(
            request.messages, include_tool_call_id=False
        )
    )
    max_iterations = settings.agent_max_iterations

    tz_kwargs = await _build_native_tz_kwargs(
        skill_service, tool_mode
    )

    final_content = ""
    model_used = "unknown"
    had_any_tool_execution = False
    did_empty_text_retry = False
    repeated_across_iterations: dict[str, int] = {}

    for iteration in range(max_iterations):
        response = await tz_inference(
            messages=messages,
            function_name="chat",
            system=system_prompt,
            **tz_kwargs,
        )

        content, tool_calls, model_used, raw_blocks = _parse_response_blocks(
            response, iteration=iteration
        )

        # No tool calls → final text response (or empty-text retry).
        if not tool_calls:
            action = _handle_no_tool_calls(
                messages, content, had_any_tool_execution, did_empty_text_retry,
            )
            if action == "retry":
                did_empty_text_retry = True
                yield {
                    "type": "injected_message",
                    "role": "user",
                    "content": _EMPTY_TEXT_NUDGE,
                }
                continue

            if content.strip():
                for delta in _split_into_deltas(content):
                    yield {"type": "content_delta", "delta": delta}
            final_content = content
            break

        # Execute tool calls via helper generator.
        seen_keys: set[str] = set()
        per_tool_results: list[dict[str, Any]] = []
        async for event in _execute_tool_calls(
            tool_calls,
            skill_service,
            seen_keys,
            repeated_across_iterations,
            iteration,
        ):
            if event["type"] == "_tool_summary":
                tool_results = event["results"]
                if event["had_execution"]:
                    had_any_tool_execution = True
            elif event["type"] == "tool_call_result":
                per_tool_results.append(event)
                yield event
            else:
                yield event

        yield _inject_tool_results(
            messages, tool_mode, content, raw_blocks,
            tool_results, tool_calls, per_tool_results,
        )
        final_content = content

    final_content = await _finalize_agent_content(
        final_content, had_any_tool_execution, tool_mode,
        messages, system_prompt, tz_kwargs, model_used,
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
    manager: ConnectionManager,
    tool_mode: str = "python_exec",
) -> ChatCompletionResponse:
    """Run agent loop with tool execution.

    This is used when enable_tools=True (Hub executes tools).
    """
    # Consume the shared generator and construct the classic JSON response.
    final_content: Optional[str] = None
    model_used = "unknown"
    usage: dict[str, Any] = {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
    }

    async for event in _agent_loop_events(
        request=request,
        device=device,
        db=db,
        manager=manager,
        tool_mode=tool_mode,
    ):
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


def _split_into_deltas(text: str) -> list[str]:
    """Split text into word-level chunks for streaming.

    Preserves whitespace so that concatenating all deltas produces the
    original text exactly.

    Args:
        text: Full text to split.

    Returns:
        List of small string chunks.
    """
    # Split on word boundaries, keeping whitespace attached to the
    # preceding word so the UI can render smoothly.
    parts = _re.findall(r"\S+\s*", text)
    # If there's only trailing whitespace left, include it
    remainder = text[sum(len(p) for p in parts) :]
    if remainder:
        parts.append(remainder)
    return parts


async def _stream_inference_as_deltas(
    messages: list[dict[str, Any]],
    function_name: str = "chat_no_tools",
    system: str | None = None,
) -> dict[str, Any]:
    """Run streaming inference and collect content_delta events.

    Tries TensorZero streaming first; falls back to non-streaming +
    word-level splitting if streaming is not supported.

    Returns:
        Dict with ``deltas`` (list of content_delta event dicts) and
        ``full_text`` (the complete response text).
    """
    try:
        stream = await tz_inference_stream(
            messages=messages,
            function_name=function_name,
            system=system,
        )

        # Collect deltas from the streaming response
        deltas: list[dict[str, Any]] = []
        full_parts: list[str] = []
        async for chunk in stream:
            # TensorZero chunks have varying shapes; extract text content
            text = ""
            if hasattr(chunk, "content"):
                for block in chunk.content or []:
                    text += _extract_text_from_block(block)
            elif isinstance(chunk, dict):
                for block in chunk.get("content") or []:
                    text += _extract_text_from_block(block)
            if text:
                deltas.append({"type": "content_delta", "delta": text})
                full_parts.append(text)

        return {"deltas": deltas, "full_text": "".join(full_parts)}
    except Exception:
        # Fallback: non-streaming inference + word-level splitting
        logger.debug("Streaming inference not available, falling back to chunked")
        response = await tz_inference(
            messages=messages,
            function_name=function_name,
            system=system,
        )
        content = _extract_content(response)
        deltas = [
            {"type": "content_delta", "delta": d} for d in _split_into_deltas(content)
        ]
        return {"deltas": deltas, "full_text": content}


# Also expose as /inference for TensorZero compatibility
@router.post("/inference")
async def inference(
    request: ChatCompletionRequest,
    device: Device = Depends(get_current_device),
    db: AsyncSession = Depends(get_db),
    manager: ConnectionManager = Depends(get_connection_manager),
) -> ChatCompletionResponse:
    """TensorZero-style inference endpoint."""
    return await chat_completions(request, device, db=db, manager=manager)
