"""Chat/inference endpoints - OpenAI compatible.

Routes LLM requests through TensorZero embedded gateway with fallback support.
When enable_tools=true, Hub runs the agent loop and executes tools.
When enable_tools=false (default for Spoke pass-through), Hub just returns
LLM response.

File Summary:
- chat_completions: Main endpoint that routes to agent loop or pass-through
- _run_agent_loop: Executes tools and continues conversation until done
- _call_tensorzero: Simple pass-through to LLM (no tool execution)

Sub-modules:
- models: Pydantic request/response models
- tz_parsing: TensorZero response parsing helpers
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...auth import get_current_device
from ...config import settings
from ...database import Device, Message, Session, get_db
from ...prompt import get_tool_mode_provider
from ...tensorzero_gateway import inference as tz_inference
from ...tensorzero_gateway import inference_stream as tz_inference_stream
from ...utils import normalize_device_name
from ..websocket import ConnectionManager, get_connection_manager

# Re-export models so external code can import from hub.routers.chat
from .models import (  # noqa: F401
    _VALID_TOOL_MODES,
    ChatChoice,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatMessage,
    build_chat_response,
)
from .tool_execution import (
    DISCOVERY_TOOL_NAMES as _DISCOVERY_TOOL_NAMES,
)
from .tool_execution import (
    build_native_tz_kwargs as _build_native_tz_kwargs,
)
from .tool_execution import (
    execute_tool_calls as _execute_tool_calls,
)
from .tool_execution import (
    inject_tool_results as _inject_tool_results,
)
from .tz_parsing import (
    extract_content,
    extract_model,
    extract_text_from_block,
    normalize_messages,
    parse_response_blocks,
    split_into_deltas,
)
from .tz_parsing import (
    extract_tool_call_from_block as extract_tool_call_from_block,
)
from .tz_parsing import (
    get_content_blocks as get_content_blocks,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["chat"])

# ---------------------------------------------------------------------------
# Session helpers
# ---------------------------------------------------------------------------


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
        raise HTTPException(
            status_code=404, detail="Session not found"
        )

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
    """Append a message to a session and update cached metadata."""
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
        session.title = (
            content[:50] + ("..." if len(content) > 50 else "")
        )

    await db.commit()


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


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
        "[Chat] Received request: enable_tools=%s stream=%s"
        " messages=%s tool_mode=%s",
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
            "[Chat] Routing to agent loop"
            " (enable_tools=True, tool_mode=%s)",
            tool_mode,
        )
        response = await _run_agent_loop(
            request, device, db, manager, tool_mode=tool_mode
        )
    else:
        logger.info(
            "[Chat] Routing to pass-through (enable_tools=False)"
        )
        response = await _call_tensorzero(
            request, use_tools=False
        )

    if session is not None:
        assistant_content = response.choices[0].message.content
        if assistant_content.strip():
            await _append_session_message(
                db, session, "assistant", assistant_content
            )

    return response


# ---------------------------------------------------------------------------
# SSE / Streaming helpers
# ---------------------------------------------------------------------------


def _sse(data: dict[str, Any]) -> str:
    """Format a single Server-Sent Event payload.

    Args:
        data: JSON-serializable object.

    Returns:
        SSE-formatted string.
    """
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


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
                    final_assistant_content = str(
                        event.get("content") or ""
                    )
                yield _sse(event)
        else:
            # Pass-through: stream the response token-by-token.
            messages = normalize_messages(
                request.messages, include_tool_call_id=True
            )
            collected = await _stream_inference_as_deltas(
                messages=messages,
                function_name="chat_no_tools",
            )
            for delta_event in collected["deltas"]:
                yield _sse(delta_event)
            final_assistant_content = collected["full_text"]
            yield _sse({
                "type": "assistant_message",
                "content": final_assistant_content,
            })

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
            # TZ chunks have varying shapes; extract text content
            text = ""
            if hasattr(chunk, "content"):
                for block in chunk.content or []:
                    text += extract_text_from_block(block)
            elif isinstance(chunk, dict):
                for block in chunk.get("content") or []:
                    text += extract_text_from_block(block)
            if text:
                deltas.append({
                    "type": "content_delta", "delta": text,
                })
                full_parts.append(text)

        return {
            "deltas": deltas, "full_text": "".join(full_parts),
        }
    except (NotImplementedError, TypeError):
        # Fallback: non-streaming inference + word-level splitting
        logger.warning(
            "Streaming inference not available,"
            " falling back to chunked"
        )
        response = await tz_inference(
            messages=messages,
            function_name=function_name,
            system=system,
        )
        content = extract_content(response)
        deltas = [
            {"type": "content_delta", "delta": d}
            for d in split_into_deltas(content)
        ]
        return {"deltas": deltas, "full_text": content}



# ---------------------------------------------------------------------------
# Agent loop steering helpers
# ---------------------------------------------------------------------------


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
    if _should_retry_empty_text(
        had_tool_execution, content, already_retried
    ):
        messages.append(
            {"role": "user", "content": _EMPTY_TEXT_NUDGE}
        )
        return "retry"
    return "done"


def _should_retry_empty_text(
    had_tool_execution: bool,
    content: str,
    already_retried: bool,
) -> bool:
    """Check if we should nudge the LLM for a text response."""
    return (
        had_tool_execution
        and not content.strip()
        and not already_retried
    )


_EMPTY_TEXT_NUDGE = (
    "[System Note] The previous response contained no text. "
    "Do NOT call tools again. Respond now in natural language "
    "using the tool results above."
)

_DISCOVERY_LIMIT_NUDGE = (
    "[System Note] You already have the data you need from previous "
    "tool calls. Do NOT call search_skills or describe_function "
    "again. Respond to the user NOW in natural language using the "
    "results above."
)


def _count_discovery_calls(
    tool_calls: list[dict[str, Any]],
    had_execution: bool,
) -> int:
    """Count discovery tool calls in a batch, but only after a skill
    tool has already executed."""
    if not had_execution:
        return 0
    return sum(
        1 for tc in tool_calls
        if (tc.get("name") or "") in _DISCOVERY_TOOL_NAMES
    )

def _build_iteration_kwargs(
    tz_kwargs: dict[str, Any],
    discovery_limit: int,
    discovery_count: int,
    had_execution: bool,
    all_calls_skipped: bool,
    messages: list[dict[str, Any]],
    iteration: int = 0,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Build per-iteration inference kwargs.

    Checks three conditions that can force ``tool_choice='none'``:
    1. All previous-iteration tool calls were skipped (duplicates)
    2. A skill tool already executed — force text on next iteration
    3. Discovery-after-execution limit exceeded

    Returns:
        ``(iter_kwargs, nudge_event)`` — *nudge_event* is ``None``
        when no nudge was needed.
    """
    iter_kwargs = dict(tz_kwargs)

    if all_calls_skipped:
        logger.info(
            "[Agent Loop] Forcing text"
            " (all prior calls were skipped as duplicates)."
        )
        iter_kwargs["tool_choice"] = "none"
        nudge = _EMPTY_TEXT_NUDGE
        messages.append({"role": "user", "content": nudge})
        return iter_kwargs, {
            "type": "injected_message",
            "role": "user",
            "content": nudge,
        }

    # NOTE: NEVER prevent duplicate tool calls. 3 devs have tried this.
    # They have been scolded. It breaks certain uncommon workflows.

    if (
        discovery_limit > 0
        and had_execution
        and discovery_count >= discovery_limit
    ):
        logger.info(
            "[Agent Loop] Discovery limit exceeded (%d >= %d);"
            " forcing text-only response.",
            discovery_count,
            discovery_limit,
        )
        iter_kwargs["tool_choice"] = "none"
        nudge = _DISCOVERY_LIMIT_NUDGE
        messages.append({"role": "user", "content": nudge})
        return iter_kwargs, {
            "type": "injected_message",
            "role": "user",
            "content": nudge,
        }

    return iter_kwargs, None


# ---------------------------------------------------------------------------
# Agent loop orchestration
# ---------------------------------------------------------------------------


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
        fb = await _native_text_fallback(
            messages, system_prompt, tz_kwargs
        )
        if fb.strip():
            return fb

    logger.warning(
        "[Agent Loop] Empty model response after tool execution"
        " loop. variant=%s",
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
    logger.debug(
        "[Agent Loop][native] Running text fallback inference"
    )
    messages.append(
        {"role": "user", "content": _EMPTY_TEXT_NUDGE}
    )
    fallback_kwargs = dict(tz_kwargs)
    fallback_kwargs["tool_choice"] = "none"
    try:
        response = await tz_inference(
            messages=messages,
            function_name="chat",
            system=system_prompt,
            **fallback_kwargs,
        )
        content, _, _, _ = parse_response_blocks(response)
        return content
    except Exception:
        logger.exception(
            "[Agent Loop][native] Text fallback failed"
        )
        return ""


@dataclass
class _AgentLoopState:
    """Mutable state tracked across agent loop iterations."""

    final_content: str = ""
    model_used: str = "unknown"
    had_any_tool_execution: bool = False
    did_empty_text_retry: bool = False
    repeated: dict = field(default_factory=dict)
    discovery_after_exec: int = 0
    all_calls_skipped: bool = False


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
    from ...skill_service import HubSkillService

    skill_service = HubSkillService(
        db=db,
        user_id=device.user_id,
        connection_manager=manager,
    )

    provider = get_tool_mode_provider(tool_mode)

    messages: List[Dict[str, Any]] = []
    system_prompt = await skill_service.get_system_prompt(
        requesting_device_key=normalize_device_name(
            device.name or ""
        ),
        tool_mode=tool_mode,
    )
    messages.extend(
        normalize_messages(
            request.messages, include_tool_call_id=False
        )
    )
    max_iterations = settings.agent_max_iterations

    tz_kwargs = await _build_native_tz_kwargs(
        skill_service, tool_mode
    )

    discovery_limit = provider.max_discovery_after_execution()
    state = _AgentLoopState()

    for iteration in range(max_iterations):
        iter_kwargs, nudge_event = _build_iteration_kwargs(
            tz_kwargs, discovery_limit,
            state.discovery_after_exec,
            state.had_any_tool_execution,
            state.all_calls_skipped, messages,
            iteration=iteration,
        )
        state.all_calls_skipped = False
        if nudge_event:
            yield nudge_event

        response = await tz_inference(
            messages=messages,
            function_name="chat",
            system=system_prompt,
            **iter_kwargs,
        )

        content, tool_calls, state.model_used, raw_blocks = (
            parse_response_blocks(response, iteration=iteration)
        )

        # No tool calls → final text response (or empty-text retry).
        if not tool_calls:
            action = _handle_no_tool_calls(
                messages, content,
                state.had_any_tool_execution,
                state.did_empty_text_retry,
            )
            if action == "retry":
                state.did_empty_text_retry = True
                yield {
                    "type": "injected_message",
                    "role": "user",
                    "content": _EMPTY_TEXT_NUDGE,
                }
                continue

            if content.strip():
                for delta in split_into_deltas(content):
                    yield {
                        "type": "content_delta",
                        "delta": delta,
                    }
            state.final_content = content
            break

        state.discovery_after_exec += _count_discovery_calls(
            tool_calls, state.had_any_tool_execution,
        )

        # Execute tool calls and collect results.
        tool_results: list[str] = []
        per_tool_results: list[dict[str, Any]] = []
        batch_executed = False
        async for event in _execute_tool_calls(
            tool_calls, skill_service, set(),
            state.repeated, iteration,
            tool_mode=tool_mode,
        ):
            if event["type"] == "_tool_summary":
                tool_results = event["results"]
                batch_executed = event["had_execution"]
            elif event["type"] == "tool_call_result":
                per_tool_results.append(event)
                yield event
            else:
                yield event

        state.had_any_tool_execution = (
            state.had_any_tool_execution or batch_executed
        )
        state.all_calls_skipped = (
            not batch_executed and bool(tool_calls)
        )

        yield _inject_tool_results(
            messages, tool_mode, content, raw_blocks,
            tool_results, tool_calls, per_tool_results,
            provider=provider,
        )
        state.final_content = content

    state.final_content = await _finalize_agent_content(
        state.final_content,
        state.had_any_tool_execution,
        tool_mode,
        messages, system_prompt, tz_kwargs, state.model_used,
    )

    yield {
        "type": "assistant_message",
        "content": state.final_content,
        "model": state.model_used,
        "usage": {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        },
    }


# ---------------------------------------------------------------------------
# Non-streaming wrappers
# ---------------------------------------------------------------------------


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
    # Consume the shared generator and construct the JSON response.
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
            model_used = str(
                event.get("model") or model_used
            )
            incoming_usage = event.get("usage")
            if isinstance(incoming_usage, dict):
                usage = incoming_usage

    if not (final_content or "").strip():
        final_content = (
            "I didn't get a usable response from the model"
            " (empty content blocks). Please try again."
        )

    return build_chat_response(
        content=final_content,
        model=model_used,
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
        use_tools: If False, uses chat_no_tools function
            (Spoke handles tools)
    """
    messages = normalize_messages(
        request.messages, include_tool_call_id=True
    )

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

    # Extract content and model from TensorZero response
    content = extract_content(response)
    model_used = extract_model(response)
    if not (content or "").strip():
        raise HTTPException(
            status_code=502,
            detail=(
                "LLM returned an empty response"
                f" (no content blocks). variant={model_used}"
            ),
        )

    return build_chat_response(
        content=content,
        model=model_used,
    )


# Also expose as /inference for TensorZero compatibility
@router.post("/inference")
async def inference(
    request: ChatCompletionRequest,
    device: Device = Depends(get_current_device),
    db: AsyncSession = Depends(get_db),
    manager: ConnectionManager = Depends(get_connection_manager),
) -> ChatCompletionResponse:
    """TensorZero-style inference endpoint."""
    return await chat_completions(
        request, device, db=db, manager=manager
    )
