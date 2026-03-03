"""TensorZero response parsing helpers.

Pure functions for extracting text, tool calls, and model info from
TensorZero inference responses.  Handles both object-style (SDK class)
and dict-style (raw JSON) response shapes.
"""

import json
import logging
import re as _re
from typing import Any, List, Optional

from .models import ChatMessage

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Content block helpers
# ---------------------------------------------------------------------------


def get_content_blocks(response: Any) -> list[Any]:
    """Return TensorZero content blocks from either object or dict responses.

    TensorZero's Python SDK has returned different shapes across versions:
    - an object with a ``.content`` attribute containing block objects
    - a plain dict with a ``content`` list containing dict blocks

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


def extract_text_from_block(block: Any) -> str:
    """Extract text from a single content block."""
    if hasattr(block, "text"):
        text = getattr(block, "text", "")
        return str(text) if text else ""
    if isinstance(block, dict) and block.get("type") == "text":
        text = block.get("text", "")
        return str(text) if text else ""
    return ""


def extract_tool_call_from_block(
    block: Any,
) -> Optional[dict[str, Any]]:
    """Extract a tool call dict from a content block, if present."""
    # Object-style blocks (tests + some SDK versions)
    if hasattr(block, "type") and getattr(block, "type", None) == "tool_call":
        name = (
            getattr(block, "name", None)
            or getattr(block, "raw_name", None)
        )
        arguments: Any = getattr(block, "arguments", None)
        if not isinstance(arguments, dict):
            raw_args = getattr(block, "raw_arguments", None)
            if not raw_args and isinstance(arguments, str):
                raw_args = arguments
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
        arguments = block.get("arguments")
        if not isinstance(arguments, dict):
            raw_args = block.get("raw_arguments")
            if not raw_args and isinstance(arguments, str):
                raw_args = arguments
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


def classify_block_type(block: Any) -> str:
    """Return a string label for a content block's type."""
    if hasattr(block, "type"):
        return str(getattr(block, "type") or "unknown")
    if isinstance(block, dict):
        return str(block.get("type") or "unknown")
    return type(block).__name__


_TOOL_NAME_PATTERN_PLAIN = _re.compile(r"['\"]tool_name['\"]:\s*['\"]([^'\"]+)['\"]")
_TOOL_NAME_PATTERN_ESCAPED = _re.compile(r'\\\"tool_name\\\"\s*:\s*\\\"([^\\\"]+)\\\"')


def _add_tool_name(active_tools: set[str], value: Any) -> None:
    if isinstance(value, str) and value:
        active_tools.add(value)


def _extract_role_content_tool_calls(msg: Any) -> tuple[Any, Any, Any]:
    role = (
        msg.get("role")
        if isinstance(msg, dict)
        else getattr(msg, "role", None)
    )
    content = (
        msg.get("content")
        if isinstance(msg, dict)
        else getattr(msg, "content", None)
    )
    tool_calls = (
        msg.get("tool_calls")
        if isinstance(msg, dict)
        else getattr(msg, "tool_calls", None)
    )
    return role, content, tool_calls


def _collect_tool_names_from_string(s: str, active_tools: set[str]) -> None:
    s = s.strip()
    if not s:
        return

    if s.startswith("{") or s.startswith("["):
        try:
            _collect_tool_names_deep(json.loads(s), active_tools)
            return
        except Exception:
            pass

    for m in _TOOL_NAME_PATTERN_PLAIN.findall(s):
        active_tools.add(m)
    for m in _TOOL_NAME_PATTERN_ESCAPED.findall(s):
        active_tools.add(m)


def _collect_tool_names_deep(value: Any, active_tools: set[str]) -> None:
    """Collect nested tool_name fields from dict/list/string values.

    NOTE (regression guard): This exists because we repeatedly hit a
    native-mode bug where search results were nested inside
    ``tool_result.result`` as JSON-encoded strings (escaped quotes).
    Regex over plain ``str(content)`` alone misses those and can shrink
    native ``allowed_tools`` to discovery-only when defer-loading is on.
    """
    if isinstance(value, dict):
        for k, v in value.items():
            if k == "tool_name":
                _add_tool_name(active_tools, v)
            _collect_tool_names_deep(v, active_tools)
        return

    if isinstance(value, list):
        for item in value:
            _collect_tool_names_deep(item, active_tools)
        return

    if isinstance(value, str):
        _collect_tool_names_from_string(value, active_tools)


def _add_tools_from_assistant_calls(tool_calls: Any, active_tools: set[str]) -> None:
    if not tool_calls:
        return
    for tc in tool_calls:
        if isinstance(tc, dict):
            fn = tc.get("function")
            if isinstance(fn, dict):
                _add_tool_name(active_tools, fn.get("name"))
            else:
                _add_tool_name(active_tools, tc.get("name"))
            continue
        fn = getattr(tc, "function", None)
        _add_tool_name(active_tools, getattr(fn, "name", None))


def _add_tools_from_content_blocks(content: list[Any], active_tools: set[str]) -> None:
    for block in content:
        tc = extract_tool_call_from_block(block)
        if tc:
            _add_tool_name(active_tools, tc.get("name"))

        if classify_block_type(block) != "tool_result":
            _collect_tool_names_deep(block, active_tools)
            continue

        if isinstance(block, dict):
            _add_tool_name(active_tools, block.get("name"))
            _collect_tool_names_deep(block.get("result"), active_tools)
            continue

        _add_tool_name(active_tools, getattr(block, "name", None))
        _collect_tool_names_deep(getattr(block, "result", None), active_tools)


def extract_active_tools_from_history(messages: List[Any]) -> set[str]:
    """Extract active tool names from conversation history.

    A tool is considered active if:
    1. The assistant has called it previously (found in tool_calls).
    2. It was returned in a search_skills result ("tool_name": "...").

    Args:
        messages: The chat message history (list of dicts or ChatMessage objects).

    Returns:
        Set of active native tool names (e.g. ``Class__method``).
    """
    active_tools: set[str] = set()

    for msg in messages:
        role, content, tool_calls = _extract_role_content_tool_calls(msg)

        if role == "assistant":
            _add_tools_from_assistant_calls(tool_calls, active_tools)

        if isinstance(content, list):
            _add_tools_from_content_blocks(content, active_tools)
            continue

        if content:
            _collect_tool_names_deep(content, active_tools)

    return active_tools


# ---------------------------------------------------------------------------
# Response-level helpers
# ---------------------------------------------------------------------------


def parse_response_blocks(
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
    blocks = get_content_blocks(response)
    model_used = extract_model(response)

    text_parts: list[str] = []
    tool_calls: list[dict[str, Any]] = []
    for block in blocks:
        text = extract_text_from_block(block)
        if text:
            text_parts.append(text)
        tc = extract_tool_call_from_block(block)
        if tc:
            tool_calls.append(tc)

    content = "".join(text_parts)

    if not content.strip() and not tool_calls:
        block_types = [classify_block_type(b) for b in blocks]
        logger.warning(
            "[Agent Loop] LLM returned no text and no tool calls."
            " iteration=%s block_types=%s",
            iteration,
            block_types,
        )

    return content, tool_calls, model_used, blocks


def extract_content(response: Any) -> str:
    """Extract text content from TensorZero inference response."""
    parts: list[str] = []
    for block in get_content_blocks(response):
        text = extract_text_from_block(block)
        if text:
            parts.append(text)
    return "".join(parts)


def extract_model(response: Any) -> str:
    """Extract model name from TensorZero inference response."""
    if hasattr(response, "variant_name"):
        return response.variant_name
    if isinstance(response, dict):
        return response.get("variant_name", "unknown")
    return "unknown"


# ---------------------------------------------------------------------------
# Message normalization
# ---------------------------------------------------------------------------


def normalize_messages(
    messages: List[ChatMessage],
    include_tool_call_id: bool = False,
) -> list[dict[str, Any]]:
    """Normalize chat messages for TensorZero input.

    Args:
        messages: The incoming chat messages in OpenAI-compatible format.
        include_tool_call_id: Whether to include tool_call_id metadata
            in tool result prefixes.

    Returns:
        Normalized message dictionaries compatible with TensorZero input.
    """
    normalized: list[dict[str, Any]] = []

    for message in messages:
        if message.role in ("user", "assistant"):
            normalized.append(
                {"role": message.role, "content": message.content}
            )
            continue

        if message.role == "system":
            # Preserve system prompt content but avoid `system` role.
            normalized.append(
                {"role": "user", "content": message.content}
            )
            continue

        if message.role == "tool":
            # OpenAI tool-result messages include tool_call_id
            # and optionally name.
            prefix_parts = ["[Tool Result]"]
            if message.name:
                prefix_parts.append(f"name={message.name}")
            if include_tool_call_id and message.tool_call_id:
                prefix_parts.append(
                    f"tool_call_id={message.tool_call_id}"
                )
            prefix = " ".join(prefix_parts)
            normalized.append(
                {"role": "user", "content": f"{prefix}\n{message.content}"}
            )

    return normalized


# ---------------------------------------------------------------------------
# Streaming helpers
# ---------------------------------------------------------------------------


def split_into_deltas(text: str) -> list[str]:
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
    remainder = text[sum(len(p) for p in parts):]
    if remainder:
        parts.append(remainder)
    return parts
