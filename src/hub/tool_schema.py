"""Generate TensorZero-compatible JSON Schema tool definitions from skill metadata.

Parses the text-based ``signature`` and ``docstring`` stored in the Hub's
Skill DB rows and produces tool definitions suitable for TensorZero's
``additional_tools`` inference parameter.

Tool naming convention::

    {SkillClassName}__{method_name}

Double underscore separates class from method (single underscore is common
in method names).  Examples: ``WeatherSkill__get_current_weather``,
``CalculatorSkill__add``.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ── Python type → JSON Schema mapping ────────────────────────────────────

_TYPE_MAP: Dict[str, Dict[str, Any]] = {
    "str": {"type": "string"},
    "string": {"type": "string"},
    "int": {"type": "integer"},
    "integer": {"type": "integer"},
    "float": {"type": "number"},
    "number": {"type": "number"},
    "bool": {"type": "boolean"},
    "boolean": {"type": "boolean"},
    # Gemini requires `items` even for untyped arrays.
    "list": {"type": "array", "items": {}},
    "dict": {"type": "object"},
    "none": {},
    "any": {},
}

# Matches ``List[X]``, ``Optional[X]``, ``Dict[K, V]``, etc.
_GENERIC_RE = re.compile(r"^(\w+)\[(.+)\]$")

TOOL_NAME_SEP = "__"


# ── Data classes ─────────────────────────────────────────────────────────


@dataclass
class ParamInfo:
    """Parsed parameter extracted from a signature string."""

    name: str
    type_hint: Optional[str] = None
    default: Optional[str] = None
    description: Optional[str] = None

    @property
    def is_required(self) -> bool:
        """A param is required when it has no default and isn't Optional."""
        if self.default is not None:
            return False
        if self.type_hint and self.type_hint.lower().startswith("optional"):
            return False
        return True


# ── Signature parsing ────────────────────────────────────────────────────

# Matches a function-call style signature (with or without return annotation).
_SIG_RE = re.compile(
    r"^\s*(?:\w+\.)*(\w+)\s*\(([^)]*)\)(?:\s*->\s*(.+))?\s*$",
    re.DOTALL,
)

# Splits on commas that are *not* inside brackets/parens.
_PARAM_SPLIT_RE = re.compile(r",(?![^(\[{]*[)\]}])")


def parse_signature(sig: str) -> Optional[List[ParamInfo]]:
    """Parse a text signature into a list of :class:`ParamInfo`.

    Handles forms like::

        get_weather(location: str, units: str = 'metric') -> str
        add(a: int, b: int)
        do_stuff(x, y=10)

    ``self`` parameters are silently dropped.

    Args:
        sig: Raw signature string (as stored in the Skill DB).

    Returns:
        List of parsed parameters, or ``None`` if the signature is
        malformed and cannot be parsed at all.  An empty list means
        the method genuinely takes no parameters.
    """
    m = _SIG_RE.match(sig.strip())
    if not m:
        logger.debug("Signature did not match expected pattern: %s", sig)
        return None

    raw_params = m.group(2).strip()
    if not raw_params:
        return []

    params: List[ParamInfo] = []
    for chunk in _PARAM_SPLIT_RE.split(raw_params):
        chunk = chunk.strip()
        if not chunk or chunk == "self":
            continue

        p = _parse_single_param(chunk)
        if p and p.name != "self":
            params.append(p)

    return params


def _parse_single_param(chunk: str) -> Optional[ParamInfo]:
    """Parse one parameter token like ``location: str = 'NYC'``."""
    name: str
    type_hint: Optional[str] = None
    default: Optional[str] = None

    # Split on '=' for default, but be careful with '==' inside defaults.
    if "=" in chunk:
        lhs, _, rhs = chunk.partition("=")
        default = rhs.strip()
        chunk = lhs.strip()

    if ":" in chunk:
        name, _, type_hint = chunk.partition(":")
        name = name.strip()
        type_hint = type_hint.strip() or None
    else:
        name = chunk.strip()

    if not name or not name.isidentifier():
        return None

    return ParamInfo(name=name, type_hint=type_hint, default=default)


# ── Type conversion ──────────────────────────────────────────────────────


def python_type_to_json_schema(type_str: Optional[str]) -> Dict[str, Any]:
    """Convert a Python type-hint string to a JSON Schema fragment.

    Args:
        type_str: A type hint like ``"str"``, ``"List[int]"``,
            ``"Optional[str]"``, or ``None`` (untyped).

    Returns:
        JSON Schema dict (e.g. ``{"type": "string"}``).  Returns ``{}``
        for unknown or absent types.
    """
    if not type_str:
        return {}

    normalized = type_str.strip()
    lower = normalized.lower()

    # Direct lookup
    if lower in _TYPE_MAP:
        return dict(_TYPE_MAP[lower])

    # Generic types: Optional[X], List[X], Dict[K,V]
    gm = _GENERIC_RE.match(normalized)
    if gm:
        outer = gm.group(1).lower()
        inner = gm.group(2).strip()

        if outer == "optional":
            return python_type_to_json_schema(inner)

        if outer == "list":
            items = python_type_to_json_schema(inner)
            # Always include `items`; Gemini rejects arrays without it.
            return {"type": "array", "items": items or {}}

        if outer == "dict":
            return {"type": "object"}

    # Union types: ``str | None``, ``int | str``
    if "|" in normalized:
        parts = [p.strip() for p in normalized.split("|")]
        non_none = [p for p in parts if p.lower() != "none"]
        if len(non_none) == 1:
            return python_type_to_json_schema(non_none[0])
        # Multi-type union — leave unconstrained
        return {}

    return {}


# ── Docstring parsing ────────────────────────────────────────────────────


_ARGS_HEADERS = frozenset({"args:", "arguments:", "parameters:", "params:"})
_SECTION_HEADER_RE = re.compile(r"^\w[\w\s]*:\s*$")
_PARAM_ENTRY_RE = re.compile(r"^(\w+)(?:\s*\([^)]*\))?\s*:\s*(.*)$")


def _is_args_header(line: str) -> bool:
    return line.lower() in _ARGS_HEADERS


def _is_section_break(line: str) -> bool:
    """True for non-Args section headers like ``Returns:``."""
    return bool(line and _SECTION_HEADER_RE.match(line))


def parse_docstring_params(docstring: Optional[str]) -> Dict[str, str]:
    """Extract parameter descriptions from a Google-style docstring.

    Looks for an ``Args:`` section and parses entries like::

        location: The city name or coordinates.
        units: Temperature units (metric or imperial).

    Args:
        docstring: Full docstring text, or ``None``.

    Returns:
        Mapping of param name → description.
    """
    if not docstring:
        return {}

    result: Dict[str, str] = {}
    in_args = False
    current_name: Optional[str] = None
    current_desc: List[str] = []

    def _flush() -> None:
        nonlocal current_name, current_desc
        if current_name:
            result[current_name] = " ".join(current_desc).strip()
        current_name = None
        current_desc = []

    for line in docstring.splitlines():
        stripped = line.strip()

        if _is_args_header(stripped):
            in_args = True
            continue

        is_other_section = (
            _SECTION_HEADER_RE.match(stripped)
            and not _is_args_header(stripped)
        )
        if in_args and is_other_section:
            _flush()
            in_args = False
            continue

        if not in_args:
            continue

        param_match = _PARAM_ENTRY_RE.match(stripped)
        if param_match:
            _flush()
            current_name = param_match.group(1)
            current_desc = [param_match.group(2)] if param_match.group(2) else []
        elif current_name and stripped:
            current_desc.append(stripped)

    _flush()
    return result


def _first_line(docstring: Optional[str]) -> str:
    """Return the first non-empty line of a docstring as a summary."""
    if not docstring:
        return ""
    for line in docstring.splitlines():
        line = line.strip()
        if line:
            return line
    return ""


# ── Schema builders ──────────────────────────────────────────────────────

# Injected into every native tool schema for device routing.
_DEVICE_PARAM_SCHEMA: Dict[str, Any] = {
    "type": "string",
    "description": (
        "Target device name for routing. "
        "Optional — the hub auto-routes to the best available device if omitted."
    ),
}


def build_tool_schema(
    class_name: str,
    method_name: str,
    signature: str,
    docstring: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Build a single TensorZero-compatible tool definition.

    Args:
        class_name: Skill class name (e.g. ``"WeatherSkill"``).
        method_name: Method name (e.g. ``"get_current_weather"``).
        signature: Full text signature from the DB.
        docstring: Optional docstring text.

    Returns:
        Tool definition dict with ``name``, ``description``, and
        ``parameters`` keys, or ``None`` if the signature is
        unparseable.
    """
    params = parse_signature(signature)
    if params is None:
        return None

    param_descriptions = parse_docstring_params(docstring)
    summary = _first_line(docstring) or f"{class_name}.{method_name}"

    properties: Dict[str, Any] = {}
    required: List[str] = []

    for p in params:
        prop: Dict[str, Any] = python_type_to_json_schema(p.type_hint)

        desc = p.description or param_descriptions.get(p.name)
        if desc:
            prop["description"] = desc

        if p.default is not None:
            # Store default as-is (string representation); the LLM uses it
            # for context, TensorZero doesn't enforce it.
            prop["default"] = _coerce_default(p.default, p.type_hint)

        properties[p.name] = prop

        if p.is_required:
            required.append(p.name)

    # Inject the optional device routing parameter
    properties["device"] = dict(_DEVICE_PARAM_SCHEMA)

    tool_name = f"{class_name}{TOOL_NAME_SEP}{method_name}"

    return {
        "name": tool_name,
        "description": summary,
        "parameters": {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "properties": properties,
            "required": required,
            "additionalProperties": False,
        },
    }


def _coerce_default(raw: str, type_hint: Optional[str]) -> Any:
    """Best-effort coercion of a default value string to its native type.

    Falls back to the raw string on any failure.
    """
    stripped = raw.strip().strip("'\"")

    if stripped.lower() == "none":
        return None
    if stripped.lower() == "true":
        return True
    if stripped.lower() == "false":
        return False

    # Numeric defaults
    try:
        if type_hint and type_hint.lower() in ("int", "integer"):
            return int(stripped)
        if type_hint and type_hint.lower() in ("float", "number"):
            return float(stripped)
        # Try int/float even without hint
        if stripped.isdigit() or (stripped.startswith("-") and stripped[1:].isdigit()):
            return int(stripped)
        if re.match(r"^-?\d+\.\d+$", stripped):
            return float(stripped)
    except (ValueError, IndexError):
        pass

    return stripped


def build_tool_name(class_name: str, method_name: str) -> str:
    """Build the canonical native tool name."""
    return f"{class_name}{TOOL_NAME_SEP}{method_name}"


def parse_tool_name(tool_name: str) -> Tuple[str, str]:
    """Split a native tool name into (class_name, method_name).

    Raises:
        ValueError: If the tool name doesn't contain the separator.
    """
    if TOOL_NAME_SEP not in tool_name:
        raise ValueError(f"Invalid native tool name (no '{TOOL_NAME_SEP}'): {tool_name}")
    class_name, method_name = tool_name.split(TOOL_NAME_SEP, 1)
    return class_name, method_name


def build_all_tool_schemas(
    skills: List[Dict[str, Any]],
    *,
    limit: int = 15,
    active_tool_names: Optional[set[str]] = None,
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Build tool schemas for a list of skill rows.

    Each element in *skills* should be a dict (or dict-like) with keys:
    ``class_name``, ``function_name``, ``signature``, ``docstring``.

    Deduplicates by ``(class_name, function_name)`` so the same method
    registered on multiple devices produces only one tool definition.

    Args:
        skills: Skill metadata dicts (typically from a DB query).
        limit: Maximum number of tool schemas to produce without filtering.
        active_tool_names: Set of active tool names (Class__method). If provided
            and len(skills) > limit, only generates schemas for these active tools.

    Returns:
        Tuple of ``(tool_schemas, tool_names)`` where *tool_schemas*
        are TensorZero ``additional_tools`` dicts and *tool_names* are
        the corresponding tool name strings.
    """
    seen: set[Tuple[str, str]] = set()
    schemas: List[Dict[str, Any]] = []
    names: List[str] = []

    # If we have more skills than our limit, we defer loading. We only
    # build schemas for tools that are currently "active" in the chat context.
    defer_loading = limit > 0 and len(skills) > limit

    for skill in skills:
        cn = skill["class_name"]
        fn = skill["function_name"]
        key = (cn, fn)

        if key in seen:
            continue

        tool_name = build_tool_name(cn, fn)

        if defer_loading:
            if active_tool_names is None or tool_name not in active_tool_names:
                continue

        seen.add(key)

        schema = build_tool_schema(
            class_name=cn,
            method_name=fn,
            signature=skill.get("signature", ""),
            docstring=skill.get("docstring"),
        )
        if schema is None:
            logger.warning(
                "Skipping unparseable skill %s.%s (sig=%r)",
                cn,
                fn,
                skill.get("signature"),
            )
            continue

        schemas.append(schema)
        names.append(schema["name"])

    return schemas, names
