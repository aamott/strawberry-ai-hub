"""Tool execution, result formatting, and result injection.

Handles executing tool calls (with duplicate/repeat detection), formatting
results, and injecting tool results back into the conversation in both
python_exec and native modes.
"""

import json
import logging
from typing import Any, AsyncIterator, Optional

from ...prompt import ToolModeProvider

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Single source of truth for discovery tool names.  Imported by
# __init__.py for _count_discovery_calls and _build_iteration_kwargs.
DISCOVERY_TOOL_NAMES = frozenset({
    "search_skills", "describe_function",
})

_REPEAT_WARN_THRESHOLD = 1  # Warn (but still execute) after this many calls

_REPEAT_WARNING = (
    "[Warning: This tool was already called with the same arguments. "
    "Do NOT call the tool again unless specifically required for the task.]\n"
)


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------


async def execute_single_tool(
    tc: dict[str, Any],
    skill_service: Any,
    seen_keys: set[str],
    repeated: dict[str, int],
    iteration: int,
    tool_mode: str = "python_exec",
) -> tuple[dict[str, Any], bool]:
    """Execute one tool call, handling duplicates and repeats.

    Duplicates within a single batch are skipped entirely. Repeats
    across iterations are still executed but include a warning in the
    result after ``_REPEAT_WARN_THRESHOLD`` executions.

    Args:
        tc: Tool call dict with ``name`` and ``arguments``.
        skill_service: Service for executing tools.
        seen_keys: Set of execution keys for deduplication.
        repeated: Repeat counter per execution key.
        iteration: Current agent loop iteration.
        tool_mode: ``"python_exec"`` or ``"native"`` — passed to
            ``skill_service.execute_tool``.

    Returns:
        Tuple of (result dict, was_executed).
    """
    execution_key = (
        f"{tc['name']}:"
        f"{json.dumps(tc['arguments'] or {}, sort_keys=True, default=str)}"
    )

    # Exact duplicate within the same response batch — skip
    if execution_key in seen_keys:
        logger.warning(
            "[Agent Loop] Duplicate tool call in single response;"
            " skipping. tool=%s args=%s",
            tc.get("name"),
            tc.get("arguments"),
        )
        return {"result": "(duplicate tool call skipped)"}, False

    seen_keys.add(execution_key)
    repeated[execution_key] = repeated.get(execution_key, 0) + 1
    is_repeat = repeated[execution_key] > _REPEAT_WARN_THRESHOLD

    if is_repeat:
        logger.warning(
            "[Agent Loop] Repeated tool call (%d > %d);"
            " executing with warning."
            " iteration=%s tool=%s args=%s",
            repeated[execution_key],
            _REPEAT_WARN_THRESHOLD,
            iteration,
            tc.get("name"),
            tc.get("arguments"),
        )

    # Always execute — even repeats get to run
    result = await skill_service.execute_tool(
        tc["name"], tc["arguments"], tool_mode=tool_mode,
    )

    # Prepend warning so the LLM knows it's repeating
    if is_repeat and "result" in result:
        result["result"] = _REPEAT_WARNING + str(result["result"])

    return result, True


def format_tool_result(
    result: dict[str, Any],
) -> tuple[bool, Optional[str], Optional[str]]:
    """Normalise a tool result into (success, result_str, error_str)."""
    success = "result" in result
    result_str = (
        str(result.get("result", "")) if success else None
    )
    error_str = (
        str(result.get("error", "")) if not success else None
    )

    if success and (result_str is None or not result_str.strip()):
        result_str = "(no output)"
    if (not success) and (
        error_str is None or not error_str.strip()
    ):
        error_str = "(unknown error)"
    return success, result_str, error_str


async def execute_tool_calls(
    tool_calls: list[dict[str, Any]],
    skill_service: Any,
    seen_keys: set[str],
    repeated: dict[str, int],
    iteration: int,
    tool_mode: str = "python_exec",
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

        result, was_executed = await execute_single_tool(
            tc, skill_service, seen_keys, repeated, iteration,
            tool_mode=tool_mode,
        )
        if was_executed:
            had_execution = True

        success, result_str, error_str = format_tool_result(
            result
        )

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
            tool_results.append(
                f"Tool {label} error: {error_str}"
            )

    yield {
        "type": "_tool_summary",
        "results": tool_results,
        "had_execution": had_execution,
    }


# ---------------------------------------------------------------------------
# Result injection
# ---------------------------------------------------------------------------


def inject_tool_results(
    messages: list[dict[str, Any]],
    tool_mode: str,
    content: str,
    raw_blocks: list[Any],
    tool_results: list[str],
    tool_calls: list[dict[str, Any]],
    per_tool_results: list[dict[str, Any]],
    provider: ToolModeProvider | None = None,
) -> dict[str, Any]:
    """Append assistant + tool-result messages to the conversation.

    Uses the provider's ``tool_result_guidance()`` to build per-tool
    steering messages rather than hardcoding them here.

    Returns an ``injected_message`` event dict for the caller to yield.
    """
    if tool_mode == "native":
        return _inject_native_tool_results(
            messages, raw_blocks, tool_calls,
            per_tool_results, provider,
        )

    return _inject_python_exec_tool_results(
        messages, content, tool_results, tool_calls,
        per_tool_results, provider,
    )


def _inject_native_tool_results(
    messages: list[dict[str, Any]],
    raw_blocks: list[Any],
    tool_calls: list[dict[str, Any]],
    per_tool_results: list[dict[str, Any]],
    provider: ToolModeProvider | None = None,
) -> dict[str, Any]:
    """Native mode: structured tool_result blocks + guidance.

    Guidance is embedded as a ``text`` content block in the SAME user
    message as the ``tool_result`` blocks so the model actually sees
    it.  A separate user message after tool_results is ignored by
    most models.
    """
    messages.append({"role": "assistant", "content": raw_blocks})
    blocks = _build_native_tool_result_blocks(
        tool_calls, per_tool_results
    )

    guidance = build_aggregate_guidance(
        tool_calls, per_tool_results, provider,
    )
    if guidance:
        blocks.append({"type": "text", "text": guidance})

    messages.append({"role": "user", "content": blocks})

    return {
        "type": "injected_message",
        "role": "user",
        "content": json.dumps(blocks, default=str),
    }


def _inject_python_exec_tool_results(
    messages: list[dict[str, Any]],
    content: str,
    tool_results: list[str],
    tool_calls: list[dict[str, Any]],
    per_tool_results: list[dict[str, Any]],
    provider: ToolModeProvider | None = None,
) -> dict[str, Any]:
    """python_exec mode: plain-text tool results + guidance."""
    messages.append({"role": "assistant", "content": content})
    tool_output = "\n".join(tool_results)

    guidance = build_aggregate_guidance(
        tool_calls, per_tool_results, provider,
    )
    injected = f"[Tool Results]\n{tool_output}"
    if guidance:
        injected += f"\n\n{guidance}"

    messages.append({"role": "user", "content": injected})
    return {
        "type": "injected_message",
        "role": "user",
        "content": injected,
    }


def build_aggregate_guidance(
    tool_calls: list[dict[str, Any]],
    per_tool_results: list[dict[str, Any]],
    provider: ToolModeProvider | None,
) -> str:
    """Combine per-tool guidance from the provider into one message.

    Falls back to a generic "respond naturally" if no provider is set.
    """
    if not provider:
        return (
            "[Now respond naturally to the user"
            " based on these results.]"
        )

    result_by_id: dict[str, dict[str, Any]] = {
        evt.get("tool_call_id", ""): evt
        for evt in per_tool_results
    }

    lines: list[str] = []
    seen: set[str] = set()
    for tc in tool_calls:
        tcid = str(tc.get("id") or "")
        evt = result_by_id.get(tcid, {})
        success = evt.get("success", True)
        name = tc.get("name") or ""
        guidance = provider.tool_result_guidance(name, success)
        if guidance and guidance not in seen:
            lines.append(guidance)
            seen.add(guidance)

    return "\n".join(lines)


def _build_native_tool_result_blocks(
    tool_calls: list[dict[str, Any]],
    per_tool_results: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build TensorZero ``tool_result`` content blocks for native mode.

    Each block maps a tool call ID to its result string, matching the
    format expected by TensorZero for multi-turn tool-use
    conversations.

    Args:
        tool_calls: Tool call dicts (with ``id`` and ``name``).
        per_tool_results: Corresponding ``tool_call_result`` events.

    Returns:
        List of ``{"type": "tool_result", ...}`` dicts.
    """
    result_by_id: dict[str, dict[str, Any]] = {}
    for evt in per_tool_results:
        tcid = evt.get("tool_call_id") or ""
        result_by_id[tcid] = evt

    blocks: list[dict[str, Any]] = []
    for tc in tool_calls:
        tcid = str(tc.get("id") or "")
        evt = result_by_id.get(tcid, {})
        result_str = str(
            evt.get("result")
            or evt.get("error")
            or "(no output)"
        )
        blocks.append({
            "type": "tool_result",
            "id": tcid,
            "name": tc.get("name") or "",
            "result": result_str,
        })
    return blocks


# ---------------------------------------------------------------------------
# Native mode TZ kwargs
# ---------------------------------------------------------------------------


async def build_native_tz_kwargs(
    skill_service: Any,
    tool_mode: str,
) -> dict[str, Any]:
    """Build extra TensorZero kwargs for native tool mode.

    Returns an empty dict for python_exec mode, or ``additional_tools``
    and ``allowed_tools`` for native mode.

    Always sets ``allowed_tools`` in native mode — even when no skill
    schemas are available — so that ``python_exec`` cannot leak through
    from the default TZ config.
    """
    if tool_mode != "native":
        return {}

    tool_schemas, tool_names = (
        await skill_service.get_native_tool_schemas()
    )

    kwargs: dict[str, Any] = {
        "allowed_tools": list(DISCOVERY_TOOL_NAMES) + tool_names,
    }
    if tool_schemas:
        kwargs["additional_tools"] = tool_schemas
    return kwargs
