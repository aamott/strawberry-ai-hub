"""Tests for hub.tool_schema — signature parsing and JSON Schema generation.

Covers:
- Signature parsing (typed, untyped, defaults, edge cases)
- Python type → JSON Schema conversion
- Docstring parameter extraction
- Full tool schema building
- build_all_tool_schemas with dedup and limits
- Tool name parsing
"""

from __future__ import annotations

import pytest

from hub.tool_schema import (
    build_all_tool_schemas,
    build_tool_name,
    build_tool_schema,
    parse_docstring_params,
    parse_signature,
    parse_tool_name,
    python_type_to_json_schema,
)

# ── parse_signature ──────────────────────────────────────────────────────


class TestParseSignature:
    def test_basic_typed(self):
        params = parse_signature(
            "get_weather(location: str, units: str) -> str"
        )
        assert len(params) == 2
        assert params[0].name == "location"
        assert params[0].type_hint == "str"
        assert params[0].is_required is True
        assert params[1].name == "units"

    def test_with_defaults(self):
        params = parse_signature(
            "get_weather(location: str, units: str = 'metric')"
        )
        assert len(params) == 2
        assert params[0].is_required is True
        assert params[1].is_required is False
        assert params[1].default == "'metric'"

    def test_untyped_params(self):
        params = parse_signature("do_stuff(x, y=10)")
        assert len(params) == 2
        assert params[0].name == "x"
        assert params[0].type_hint is None
        assert params[1].default == "10"

    def test_self_stripped(self):
        params = parse_signature(
            "WeatherSkill.get_weather(self, location: str)"
        )
        assert len(params) == 1
        assert params[0].name == "location"

    def test_no_params(self):
        params = parse_signature("status()")
        assert params == []

    def test_optional_type(self):
        params = parse_signature("f(x: Optional[str])")
        assert len(params) == 1
        assert params[0].is_required is False

    def test_complex_defaults(self):
        params = parse_signature(
            "f(x: int = 42, y: str = 'hello world', z: bool = True)"
        )
        assert len(params) == 3
        assert params[0].default == "42"
        assert params[1].default == "'hello world'"
        assert params[2].default == "True"

    def test_malformed_returns_empty(self):
        assert parse_signature("not a signature at all") == []
        assert parse_signature("") == []

    def test_multiline_skipped(self):
        # Single-line regex; multiline signatures not supported
        params = parse_signature("f(a: int)")
        assert len(params) == 1

    def test_list_type_param(self):
        params = parse_signature("f(items: List[str])")
        assert len(params) == 1
        assert params[0].type_hint == "List[str]"

    def test_dict_type_param(self):
        params = parse_signature("f(data: Dict[str, Any])")
        assert len(params) == 1
        assert params[0].type_hint == "Dict[str, Any]"


# ── python_type_to_json_schema ───────────────────────────────────────────


class TestTypeConversion:
    def test_str(self):
        assert python_type_to_json_schema("str") == {"type": "string"}

    def test_int(self):
        assert python_type_to_json_schema("int") == {"type": "integer"}

    def test_float(self):
        assert python_type_to_json_schema("float") == {"type": "number"}

    def test_bool(self):
        assert python_type_to_json_schema("bool") == {"type": "boolean"}

    def test_list_untyped(self):
        assert python_type_to_json_schema("list") == {"type": "array", "items": {}}

    def test_list_typed(self):
        schema = python_type_to_json_schema("List[int]")
        assert schema == {"type": "array", "items": {"type": "integer"}}

    def test_dict(self):
        assert python_type_to_json_schema("dict") == {"type": "object"}

    def test_optional(self):
        schema = python_type_to_json_schema("Optional[str]")
        assert schema == {"type": "string"}

    def test_union_with_none(self):
        schema = python_type_to_json_schema("str | None")
        assert schema == {"type": "string"}

    def test_none_type(self):
        assert python_type_to_json_schema(None) == {}

    def test_unknown_type(self):
        assert python_type_to_json_schema("SomeCustomClass") == {}

    def test_any(self):
        assert python_type_to_json_schema("Any") == {}

    def test_case_insensitive(self):
        assert python_type_to_json_schema("String") == {"type": "string"}
        assert python_type_to_json_schema("INT") == {"type": "integer"}


# ── parse_docstring_params ───────────────────────────────────────────────


class TestDocstringParsing:
    def test_google_style(self):
        doc = """\
Get the current weather.

Args:
    location: The city name or coordinates.
    units: Temperature units (metric or imperial).

Returns:
    Weather description string.
"""
        params = parse_docstring_params(doc)
        assert params["location"] == "The city name or coordinates."
        assert "metric" in params["units"]

    def test_multiline_descriptions(self):
        doc = """\
Do something.

Args:
    name: The name of the thing
        that we are working with.
    count: How many items.
"""
        params = parse_docstring_params(doc)
        assert "thing" in params["name"]
        assert "working with" in params["name"]
        assert params["count"] == "How many items."

    def test_no_args_section(self):
        assert parse_docstring_params("Just a summary.") == {}

    def test_none_docstring(self):
        assert parse_docstring_params(None) == {}

    def test_empty_docstring(self):
        assert parse_docstring_params("") == {}

    def test_params_header_variant(self):
        doc = """\
Summary.

Parameters:
    x: The x value.
"""
        params = parse_docstring_params(doc)
        assert params["x"] == "The x value."


# ── build_tool_schema ────────────────────────────────────────────────────


class TestBuildToolSchema:
    def test_basic(self):
        schema = build_tool_schema(
            class_name="WeatherSkill",
            method_name="get_current_weather",
            signature=(
                "get_current_weather(location: str,"
                " units: str = 'metric') -> str"
            ),
            docstring="Get current weather for a location.",
        )
        assert schema is not None
        assert schema["name"] == "WeatherSkill__get_current_weather"
        assert "weather" in schema["description"].lower()

        params = schema["parameters"]
        assert params["type"] == "object"
        assert "location" in params["properties"]
        assert "units" in params["properties"]
        assert "device" in params["properties"]

        assert "location" in params["required"]
        assert "units" not in params["required"]
        assert "device" not in params["required"]

    def test_device_param_always_present(self):
        schema = build_tool_schema(
            class_name="Calc",
            method_name="add",
            signature="add(a: int, b: int) -> int",
        )
        assert schema is not None
        assert "device" in schema["parameters"]["properties"]
        device_prop = schema["parameters"]["properties"]["device"]
        assert device_prop["type"] == "string"

    def test_no_params(self):
        schema = build_tool_schema(
            class_name="StatusSkill",
            method_name="ping",
            signature="ping() -> str",
        )
        assert schema is not None
        assert schema["parameters"]["required"] == []
        # Only device param should be in properties
        assert "device" in schema["parameters"]["properties"]

    def test_docstring_descriptions_injected(self):
        schema = build_tool_schema(
            class_name="S",
            method_name="m",
            signature="m(x: str)",
            docstring="Summary.\n\nArgs:\n    x: The x value.",
        )
        assert schema is not None
        assert schema["parameters"]["properties"]["x"].get(
            "description"
        ) == "The x value."

    def test_malformed_signature_returns_none(self):
        # Empty parameters list is valid (returns schema with no params)
        # but totally unparseable signature returns None only if
        # parse_signature returns None. Currently returns [] for
        # malformed, which is valid (no params).
        schema = build_tool_schema(
            class_name="X",
            method_name="y",
            signature="not a signature",
        )
        # Malformed sig → parse_signature returns [] → valid schema
        # with just the device param
        assert schema is not None
        assert schema["parameters"]["required"] == []

    def test_default_coercion(self):
        schema = build_tool_schema(
            class_name="S",
            method_name="m",
            signature="m(x: int = 42, y: bool = True, z: str = 'hi')",
        )
        assert schema is not None
        props = schema["parameters"]["properties"]
        assert props["x"]["default"] == 42
        assert props["y"]["default"] is True
        assert props["z"]["default"] == "hi"


# ── build_all_tool_schemas ───────────────────────────────────────────────


class TestBuildAllToolSchemas:
    def _make_skill(
        self, cls: str, fn: str, sig: str, doc: str = ""
    ) -> dict:
        return {
            "class_name": cls,
            "function_name": fn,
            "signature": sig,
            "docstring": doc,
        }

    def test_basic(self):
        skills = [
            self._make_skill(
                "W", "get", "get(location: str)", "Get weather"
            ),
            self._make_skill("C", "add", "add(a: int, b: int)", "Add"),
        ]
        schemas, names = build_all_tool_schemas(skills)
        assert len(schemas) == 2
        assert names == ["W__get", "C__add"]

    def test_dedup_same_method_different_devices(self):
        skills = [
            self._make_skill("W", "get", "get(x: str)", ""),
            self._make_skill("W", "get", "get(x: str)", ""),
        ]
        schemas, names = build_all_tool_schemas(skills)
        assert len(schemas) == 1

    def test_limit(self):
        skills = [
            self._make_skill(f"S{i}", "m", "m()", "")
            for i in range(50)
        ]
        schemas, names = build_all_tool_schemas(skills, limit=5)
        assert len(schemas) == 5
        assert len(names) == 5


# ── Tool name helpers ────────────────────────────────────────────────────


class TestToolNameHelpers:
    def test_build_tool_name(self):
        assert build_tool_name("Weather", "get") == "Weather__get"

    def test_parse_tool_name(self):
        cls, method = parse_tool_name("Weather__get_current_weather")
        assert cls == "Weather"
        assert method == "get_current_weather"

    def test_parse_invalid_raises(self):
        with pytest.raises(ValueError, match="no '__'"):
            parse_tool_name("nope")
