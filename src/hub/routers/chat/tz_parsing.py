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
    import re

    # NOTE (regression guard): We have repeatedly hit a native-mode bug where
    # active tool names were "lost" after discovery because search results were
    # nested inside tool_result.result as JSON-encoded strings (with escaped
    # quotes like \"tool_name\"). A plain regex over str(content) misses those,
    # which collapses allowed_tools to discovery-only when schema defer-loading
    # is enabled. Keep this extraction path robust and structured-first.
    def _collect_tool_names_deep(value: Any) -> None:
        if isinstance(value, dict):
            for k, v in value.items():
                if k == "tool_name" and isinstance(v, str) and v:
                    active_tools.add(v)
                _collect_tool_names_deep(v)
            return
        if isinstance(value, list):
            for item in value:
                _collect_tool_names_deep(item)
            return
        if isinstance(value, str):
            s = value.strip()
            if not s:
                return
            # Try structured decode first to handle escaped JSON payloads.
            if s.startswith("{") or s.startswith("["):
                try:
                    parsed = json.loads(s)
                    _collect_tool_names_deep(parsed)
                    return
                except Exception:
                    pass
            # Fallback regex for plain text / repr-like payloads.
            pattern_plain = r"['\"]tool_name['\"]:\s*['\"]([^'\"]+)['\"]"
            pattern_escaped = r'\\\"tool_name\\\"\s*:\s*\\\"([^\\\"]+)\\\"'
            for m in re.findall(pattern_plain, s):
                active_tools.add(m)
            for m in re.findall(pattern_escaped, s):
                active_tools.add(m)

    for msg in messages:
        role = (
            msg.get("role") if isinstance(msg, dict)
            else getattr(msg, "role", None)
        )
        content = (
            msg.get("content") if isinstance(msg, dict)
            else getattr(msg, "content", None)
        )
        tool_calls = (
            msg.get("tool_calls") if isinstance(msg, dict)
            else getattr(msg, "tool_calls", None)
        )

        # 1. Discover tools from explicit assistant tool call metadata.
        if role == "assistant" and tool_calls:
            for tc in tool_calls:
                if isinstance(tc, dict):
                    if "function" in tc and isinstance(tc["function"], dict):
                        name = tc["function"].get("name")
                        if name:
                            active_tools.add(name)
                    elif "name" in tc:
                        active_tools.add(tc["name"])
                elif hasattr(tc, "function") and hasattr(tc.function, "name"):
                    active_tools.add(tc.function.name)

        # 2. Discover tools from structured content blocks.
        # In native mode we store assistant raw blocks and user tool_result
        # blocks directly in `content`, so parse that structure first.
        if isinstance(content, list):
            for block in content:
                tc = extract_tool_call_from_block(block)
                if tc and tc.get("name"):
                    active_tools.add(str(tc["name"]))

                block_type = ""
                if isinstance(block, dict):
                    block_type = str(block.get("type") or "")
                elif hasattr(block, "type"):
                    block_type = str(getattr(block, "type") or "")
                if block_type == "tool_result":
                    # Capture the called tool directly and also crawl result data.
                    if isinstance(block, dict):
                        name = block.get("name")
                        if name:
                            active_tools.add(str(name))
                        _collect_tool_names_deep(block.get("result"))
                    else:
                        name = getattr(block, "name", None)
                        if name:
                            active_tools.add(str(name))
                        _collect_tool_names_deep(getattr(block, "result", None))
                else:
                    _collect_tool_names_deep(block)
            continue

        # 3. Fallback for string content (pass-through / legacy forms).
        if content:
            _collect_tool_names_deep(content)

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
