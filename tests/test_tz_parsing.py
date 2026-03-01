"""Unit tests for TensorZero response parsing helpers.

Covers both object-style and dict-style response shapes to catch
breakage when the TZ SDK changes its return format.
"""

import types

from hub.routers.chat.models import ChatMessage
from hub.routers.chat.tz_parsing import (
    extract_content,
    extract_model,
    extract_text_from_block,
    extract_tool_call_from_block,
    get_content_blocks,
    normalize_messages,
    parse_response_blocks,
    split_into_deltas,
)

# ---------------------------------------------------------------------------
# Helpers for creating mock response shapes
# ---------------------------------------------------------------------------


def _obj(**kwargs):
    """Create a simple namespace object with the given attributes."""
    return types.SimpleNamespace(**kwargs)


def _text_block(text: str):
    """Create a text content block (object-style)."""
    return _obj(type="text", text=text)


def _tool_call_block(
    name: str, arguments: dict | None = None, tc_id: str = "tc1",
):
    """Create a tool_call content block (object-style)."""
    return _obj(
        type="tool_call", name=name,
        arguments=arguments or {}, id=tc_id,
    )


# ---------------------------------------------------------------------------
# get_content_blocks
# ---------------------------------------------------------------------------


class TestGetContentBlocks:
    """Test extracting content blocks from various response shapes."""

    def test_object_style_with_content_attr(self):
        resp = _obj(content=[_text_block("hi")])
        blocks = get_content_blocks(resp)
        assert len(blocks) == 1

    def test_dict_style_with_content_key(self):
        resp = {"content": [{"type": "text", "text": "hello"}]}
        blocks = get_content_blocks(resp)
        assert len(blocks) == 1

    def test_empty_object(self):
        resp = _obj(content=[])
        assert get_content_blocks(resp) == []

    def test_empty_dict(self):
        assert get_content_blocks({}) == []

    def test_none_response(self):
        assert get_content_blocks(None) == []

    def test_dict_with_none_content(self):
        assert get_content_blocks({"content": None}) == []


# ---------------------------------------------------------------------------
# extract_text_from_block
# ---------------------------------------------------------------------------


class TestExtractTextFromBlock:
    """Test text extraction from both block shapes."""

    def test_object_style(self):
        block = _text_block("hello world")
        assert extract_text_from_block(block) == "hello world"

    def test_dict_style(self):
        block = {"type": "text", "text": "hello dict"}
        assert extract_text_from_block(block) == "hello dict"

    def test_tool_call_block_returns_empty(self):
        block = _tool_call_block("python_exec")
        assert extract_text_from_block(block) == ""

    def test_empty_text(self):
        block = _text_block("")
        assert extract_text_from_block(block) == ""

    def test_none_text_attr(self):
        block = _obj(type="text", text=None)
        assert extract_text_from_block(block) == ""


# ---------------------------------------------------------------------------
# extract_tool_call_from_block
# ---------------------------------------------------------------------------


class TestExtractToolCallFromBlock:
    """Test tool call extraction from both block shapes."""

    def test_object_style_with_arguments(self):
        block = _tool_call_block(
            "python_exec", {"code": "print(1)"},
        )
        tc = extract_tool_call_from_block(block)
        assert tc is not None
        assert tc["name"] == "python_exec"
        assert tc["arguments"] == {"code": "print(1)"}
        assert tc["id"] == "tc1"

    def test_dict_style_with_arguments(self):
        block = {
            "type": "tool_call",
            "name": "search_skills",
            "arguments": {"query": "weather"},
            "id": "tc2",
        }
        tc = extract_tool_call_from_block(block)
        assert tc is not None
        assert tc["name"] == "search_skills"
        assert tc["arguments"] == {"query": "weather"}
        assert tc["id"] == "tc2"

    def test_object_style_with_raw_arguments(self):
        block = _obj(
            type="tool_call", name="test",
            arguments=None,
            raw_arguments='{"key": "val"}',
            id="tc3",
        )
        tc = extract_tool_call_from_block(block)
        assert tc is not None
        assert tc["arguments"] == {"key": "val"}

    def test_dict_style_with_raw_arguments(self):
        block = {
            "type": "tool_call",
            "name": "test",
            "arguments": None,
            "raw_arguments": '{"key": "val"}',
            "id": "tc4",
        }
        tc = extract_tool_call_from_block(block)
        assert tc is not None
        assert tc["arguments"] == {"key": "val"}

    def test_text_block_returns_none(self):
        block = _text_block("hello")
        assert extract_tool_call_from_block(block) is None

    def test_dict_text_block_returns_none(self):
        block = {"type": "text", "text": "hi"}
        assert extract_tool_call_from_block(block) is None

    def test_raw_name_fallback(self):
        block = _obj(
            type="tool_call", name=None,
            raw_name="fallback_name",
            arguments={}, id="tc5",
        )
        tc = extract_tool_call_from_block(block)
        assert tc is not None
        assert tc["name"] == "fallback_name"

    def test_missing_id_defaults_to_empty(self):
        block = {"type": "tool_call", "name": "test", "arguments": {}}
        tc = extract_tool_call_from_block(block)
        assert tc["id"] == ""


# ---------------------------------------------------------------------------
# parse_response_blocks
# ---------------------------------------------------------------------------


class TestParseResponseBlocks:
    """Test full response parsing."""

    def test_text_only_response(self):
        resp = _obj(
            content=[_text_block("The answer is 42.")],
            variant_name="gpt-4o",
        )
        content, tool_calls, model, blocks = parse_response_blocks(resp)
        assert content == "The answer is 42."
        assert tool_calls == []
        assert model == "gpt-4o"

    def test_tool_call_only_response(self):
        resp = _obj(
            content=[_tool_call_block("python_exec", {"code": "1+1"})],
            variant_name="gpt-4o-mini",
        )
        content, tool_calls, model, blocks = parse_response_blocks(resp)
        assert content == ""
        assert len(tool_calls) == 1
        assert tool_calls[0]["name"] == "python_exec"

    def test_mixed_response(self):
        resp = _obj(
            content=[
                _text_block("Let me check. "),
                _tool_call_block("search_skills", {"query": "weather"}),
            ],
            variant_name="gpt-4o",
        )
        content, tool_calls, model, blocks = parse_response_blocks(resp)
        assert "Let me check" in content
        assert len(tool_calls) == 1

    def test_dict_style_response(self):
        resp = {
            "content": [
                {"type": "text", "text": "Hello!"},
            ],
            "variant_name": "test-model",
        }
        content, tool_calls, model, blocks = parse_response_blocks(resp)
        assert content == "Hello!"
        assert model == "test-model"


# ---------------------------------------------------------------------------
# extract_content / extract_model
# ---------------------------------------------------------------------------


class TestExtractContentAndModel:
    def test_extract_content_object(self):
        resp = _obj(content=[_text_block("hi")])
        assert extract_content(resp) == "hi"

    def test_extract_content_dict(self):
        resp = {"content": [{"type": "text", "text": "hi"}]}
        assert extract_content(resp) == "hi"

    def test_extract_model_object(self):
        resp = _obj(variant_name="gpt-4o")
        assert extract_model(resp) == "gpt-4o"

    def test_extract_model_dict(self):
        assert extract_model({"variant_name": "test"}) == "test"

    def test_extract_model_unknown(self):
        assert extract_model({}) == "unknown"
        assert extract_model(None) == "unknown"


# ---------------------------------------------------------------------------
# normalize_messages
# ---------------------------------------------------------------------------


class TestNormalizeMessages:
    """Test message normalization for TZ input."""

    def test_user_message_passes_through(self):
        msgs = [ChatMessage(role="user", content="hi")]
        result = normalize_messages(msgs)
        assert result == [{"role": "user", "content": "hi"}]

    def test_assistant_message_passes_through(self):
        msgs = [ChatMessage(role="assistant", content="hello")]
        result = normalize_messages(msgs)
        assert result == [{"role": "assistant", "content": "hello"}]

    def test_system_becomes_user(self):
        msgs = [ChatMessage(role="system", content="You are helpful.")]
        result = normalize_messages(msgs)
        assert result[0]["role"] == "user"
        assert result[0]["content"] == "You are helpful."

    def test_tool_includes_prefix(self):
        msgs = [ChatMessage(
            role="tool", content="result data",
            name="python_exec", tool_call_id="tc1",
        )]
        result = normalize_messages(msgs, include_tool_call_id=True)
        assert "[Tool Result]" in result[0]["content"]
        assert "name=python_exec" in result[0]["content"]
        assert "tool_call_id=tc1" in result[0]["content"]

    def test_tool_without_tool_call_id(self):
        msgs = [ChatMessage(
            role="tool", content="result",
            name="test",
        )]
        result = normalize_messages(msgs, include_tool_call_id=False)
        assert "tool_call_id" not in result[0]["content"]


# ---------------------------------------------------------------------------
# split_into_deltas
# ---------------------------------------------------------------------------


class TestSplitIntoDeltas:
    """Test word-level splitting for streaming."""

    def test_basic_split(self):
        deltas = split_into_deltas("hello world")
        assert "".join(deltas) == "hello world"
        assert len(deltas) >= 2

    def test_preserves_trailing_whitespace_on_words(self):
        # split_into_deltas uses \S+\s* which attaches trailing
        # whitespace to words but doesn't capture leading whitespace
        text = "hello   world  "
        deltas = split_into_deltas(text)
        assert "".join(deltas) == text

    def test_empty_string(self):
        assert split_into_deltas("") == []

    def test_single_word(self):
        deltas = split_into_deltas("hello")
        assert "".join(deltas) == "hello"

    def test_trailing_whitespace_preserved(self):
        text = "hello "
        deltas = split_into_deltas(text)
        assert "".join(deltas) == text
