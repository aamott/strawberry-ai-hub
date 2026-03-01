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
