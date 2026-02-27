"""Modular system prompt generation for the Hub agent loop.

Mirrors the spoke's ``ToolModeProvider`` pattern but specialised for
Hub usage (always REMOTE mode, device-agnostic routing via
``devices.hub.*``).

Architecture::

    ROLE_SECTION (static, tool-agnostic)
      + HubPythonExecToolMode.build_tools_section()
      + device_keys_section
      = full system prompt for the Hub agent loop
"""

from __future__ import annotations

import logging
import re
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Role section (static, tool-agnostic — same personality as spoke)
# ---------------------------------------------------------------------------

ROLE_SECTION = """\
SYSTEM INSTRUCTIONS (read carefully and follow exactly):

You are Strawberry, a helpful AI assistant with access to
skills across all connected devices.

## Critical Notes

- Try to be helpful. If the user requests something that you suspect
  requires a skill (fetching weather, adding numbers, etc), call
  `search_skills` to find the skill. If you need more information
  about a skill function, call `describe_function`.
- Do NOT say "I can't" until you have searched for skills and
  confirmed that the skill does not exist. It may take multiple
  searches.
- After you find the right skill, execute it immediately. Don't ask
  for confirmation unless you actually need clarification (e.g., a
  required location you don't have).
- Do NOT reexecute the same snippet of code if you don't get output.
  Just tell the user the skill failed and what happened. However, if
  you can try different input to make it work, do so.
- After tool calls complete, ALWAYS provide a final natural-language
  answer. Where useful, include interim responses ("Let me find that
  for you") to keep the user engaged.

## Searching Tips

search_skills matches against method names, skill names, and
descriptions. Search by **action** or **verb**, not by specific
entity/object names.
- To turn on a lamp, search 'turn on' or 'lamp'.
- To set brightness, search 'light' or 'brightness'.
- If a skill doesn't show up on the first try, continue searching
  and experiment with different keywords."""


# ---------------------------------------------------------------------------
# ToolModeProvider ABC (same interface as spoke)
# ---------------------------------------------------------------------------


class ToolModeProvider(ABC):
    """Base class for tool-mode-specific prompt content.

    Each tool mode implements this interface. The shared composition
    logic lives in :meth:`build_tools_section`.
    """

    @abstractmethod
    def tool_header(self) -> str:
        """Return the 'Available Tools' header."""

    @abstractmethod
    def discovery_section(self) -> str:
        """Return instructions for skill discovery."""

    @abstractmethod
    def describe_section(self) -> str:
        """Return instructions for describe_function."""

    @abstractmethod
    def execution_section(self) -> str:
        """Return instructions for skill execution."""

    @abstractmethod
    def examples_section(self) -> str:
        """Return concrete examples for the LLM."""

    @abstractmethod
    def rules_section(self) -> str:
        """Return execution rules and constraints."""

    # -- Concrete composition -----------------------------------------------

    def build_tools_section(self) -> str:
        """Compose all sub-sections into the tools block.

        Returns:
            Complete tools section string.
        """
        parts = [
            self.tool_header(),
            self.discovery_section(),
            self.describe_section(),
            self.execution_section(),
            self.examples_section(),
            self.rules_section(),
        ]
        return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# HubPythonExecToolMode — the Hub's default tool mode
# ---------------------------------------------------------------------------


class HubPythonExecToolMode(ToolModeProvider):
    """Tool mode using ``python_exec`` for the Hub agent loop.

    Always uses REMOTE syntax (``devices.<device>.<Skill>.<method>``).
    Device-agnostic skills route through ``devices.hub.*``.
    """

    def tool_header(self) -> str:
        """List the 3 available tools."""
        return """\
## Available Tools

You have exactly 3 tools and a set of python skills to help you execute tasks:
1) search_skills(query) - Find skills by keyword
   (searches method names and descriptions).
2) describe_function(path) - Get the full signature for a skill
   method. Call this if you need more information about a skill
   function, e.g. after an error.
3) python_exec(code) - Execute Python code, including skills."""

    def discovery_section(self) -> str:
        """Describe search_skills for Hub (multi-device)."""
        return """\
## search_skills

- search_skills(query) - Find skill functions by keyword.
  Searches method names and descriptions and returns a list of
  skill methods, devices they belong to, and a short description.
  Many devices may have the same skill method name, so the device
  is included to disambiguate. If it doesn't matter which device
  runs it (like the calculator skill) you can pick any device, but
  prefer the `preferred_device` if present.

  Example:
  ```
  search_skills(query="weather")
  ```

  Device-agnostic skills route through `devices.hub.*`"""

    def describe_section(self) -> str:
        """Describe describe_function (shared)."""
        return """\
## describe_function

- describe_function(path) - Get the full signature and docstring
  for a skill method. Helpful for debugging or when you need more
  information."""

    def execution_section(self) -> str:
        """Describe python_exec for Hub (always devices.*)."""
        return """\
## python_exec

- Use `python_exec` to execute skills. It takes a string of Python
  code and executes it. The code should call a skill method and
  print the final output. Avoid importing — just use default
  python functions.
- Use the `devices` object for remote devices:
  `devices.<device>.<SkillClass>.<method>(...)`
- print the final output so the result is surfaced to you.
  Otherwise you won't see a result.
- Do NOT use offline-mode syntax like device.<SkillClass>.<method>(...)
  in online mode."""

    def examples_section(self) -> str:
        """Provide Hub-specific examples."""
        return """\
## Examples

Weather:
- User: "What's the weather in San Francisco, CA?"
  a) search_skills(query="weather")
  b) python_exec(code="print(
     devices.<device>.WeatherSkill
     .get_current_weather('San Francisco, CA'))")

Documentation lookup:
- User: "Look up React docs"
  a) search_skills(query="documentation")
  b) python_exec(code="print(
     devices.<device>.Context7Skill
     .resolve_library_id(libraryName='react'))")
  c) python_exec(code="print(
     devices.<device>.Context7Skill
     .query_docs(libraryId='...', query='getting started'))")"""

    def rules_section(self) -> str:
        """Return python_exec rules for the Hub."""
        return """\
## Rules

1. Use python_exec to call skills — do NOT call skill methods
   directly as tools. It won't work.
2. Do NOT output code blocks or ```tool_outputs``` — use python_exec.
3. For smart-home commands (turn on/off, lights, locks, media), look
   for HomeAssistantSkill. Pass the device/entity name as the 'name'
   kwarg.

If there are multiple possible devices or skills, choose the most
relevant and proceed unless you NEED clarification."""


# ---------------------------------------------------------------------------
# HubNativeToolMode — native tool calling for the Hub
# ---------------------------------------------------------------------------


class HubNativeToolMode(ToolModeProvider):
    """Tool mode where each skill method is a native tool.

    The LLM calls skill methods directly (e.g.
    ``WeatherSkill__get_current_weather(location="Seattle")``)
    instead of writing Python code via ``python_exec``.

    Discovery tools (``search_skills``, ``describe_function``)
    remain available for finding the right tool.
    """

    def tool_header(self) -> str:
        return """\
## Available Tools

Each skill method is registered as a native tool that you can call
directly by name.  You also have two discovery helpers:
1) search_skills(query) - Find skills by keyword.
2) describe_function(path) - Get full signature and docstring."""

    def discovery_section(self) -> str:
        return """\
## search_skills

- search_skills(query) - Find skill functions by keyword.
  Returns skill names, devices, and short descriptions.
  Use this when you're not sure which tool to call.

  Example:
  ```
  search_skills(query="weather")
  ```"""

    def describe_section(self) -> str:
        return """\
## describe_function

- describe_function(path) - Get the full signature and docstring
  for a skill method. Helpful when you need parameter details."""

    def execution_section(self) -> str:
        return """\
## Calling Skills

- Call skill tools directly by name. No code required.
- Tool names follow the pattern: SkillClass__method_name
  (double underscore between class and method).
- Pass parameters as named arguments.
- To route to a specific device, include the optional
  `device` parameter. If omitted, the hub picks the best
  available device automatically.

Example:
  WeatherSkill__get_current_weather(
      location="San Francisco, CA",
      device="living_room_pc"
  )"""

    def examples_section(self) -> str:
        return """\
## Examples

Weather:
- User: "What's the weather in San Francisco?"
  a) search_skills(query="weather")
  b) WeatherSkill__get_current_weather(
         location="San Francisco, CA")

Multi-device:
- User: "Turn on the kitchen lights"
  a) search_skills(query="turn on light")
  b) HomeAssistantSkill__HassTurnOn(
         name="Kitchen Light",
         device="home_server")"""

    def rules_section(self) -> str:
        return """\
## Rules

1. Call tools directly — do NOT write code or use python_exec.
2. After a tool call completes, always give a natural-language
   response to the user.
3. Do NOT say "I can't" until you have searched for skills.
4. If a tool call fails, check describe_function for correct
   parameter names and types, then retry.
5. For smart-home commands, look for HomeAssistantSkill tools.
   Pass the device/entity name as the 'name' parameter."""


# ---------------------------------------------------------------------------
# Provider registry
# ---------------------------------------------------------------------------

_PROVIDERS: dict[str, ToolModeProvider] = {}


def get_tool_mode_provider(name: str = "python_exec") -> ToolModeProvider:
    """Get a tool mode provider by name (singleton).

    Args:
        name: Tool mode name (``"python_exec"`` or ``"native"``).

    Returns:
        ToolModeProvider instance.

    Raises:
        ValueError: If the tool mode is unknown.
    """
    if name not in _PROVIDERS:
        if name == "python_exec":
            _PROVIDERS[name] = HubPythonExecToolMode()
        elif name == "native":
            _PROVIDERS[name] = HubNativeToolMode()
        else:
            raise ValueError(
                f"Unknown tool mode: {name!r}. "
                "Available: ['python_exec', 'native']"
            )
    return _PROVIDERS[name]


# ---------------------------------------------------------------------------
# Legacy custom prompt stripping
# ---------------------------------------------------------------------------


# Headers that mark the start of a tool section to strip
_TOOL_HEADERS = {
    "available tools",
    "search_skills",
    "describe_function",
    "python_exec",
    "ts_exec",
    "examples",
    "example",
    "rules",
    "searching tips",
    "critical notes",
    "available skills",
}


def _strip_tool_sections(text: str) -> str:
    """Strip known tool-instruction sections from a custom prompt.

    Legacy custom prompts (set via SYSTEM_PROMPT env var) may contain
    the full system prompt including tool sections. This helper removes
    them so we can cleanly append the dynamically-generated tools
    section without duplication.

    Args:
        text: Raw custom prompt string.

    Returns:
        Prompt with tool sections removed.
    """
    lines = text.split("\n")
    result: list[str] = []
    skipping = False

    for line in lines:
        heading_match = re.match(r"^##\s+(.+)$", line)
        if heading_match:
            heading_text = heading_match.group(1).strip().lower()
            if heading_text in _TOOL_HEADERS:
                skipping = True
                continue
            skipping = False

        if not skipping:
            result.append(line)

    return "\n".join(result).rstrip()


# ---------------------------------------------------------------------------
# Device keys footer (Hub-specific)
# ---------------------------------------------------------------------------

DEVICE_AGNOSTIC_KEY = "hub"


def build_device_keys_section(device_keys: str) -> str:
    """Build the device keys footer for the system prompt.

    Args:
        device_keys: Comma-separated list of valid device keys.

    Returns:
        Formatted device keys section.
    """
    return (
        "VALID DEVICE KEYS (use exactly these after 'devices.'):\n"
        f"{device_keys or '(none)'}\n\n"
        "IMPORTANT:\n"
        "- Never invent device names. Always pick a device from "
        "search_skills() results or from the list above.\n"
        f"- For device-agnostic skills, use devices.{DEVICE_AGNOSTIC_KEY}."
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_system_prompt(
    device_keys: str,
    custom_prompt: str | None = None,
    tool_mode: str = "python_exec",
) -> str:
    """Generate the full Hub system prompt.

    Composes: role section + tools section + device keys footer.

    When *custom_prompt* is provided it replaces the role section.
    Any legacy tool sections are stripped automatically.

    Args:
        device_keys: Comma-separated valid device keys.
        custom_prompt: Optional custom role text. Defaults to
            ``ROLE_SECTION``.
        tool_mode: Tool mode name (default ``"python_exec"``).

    Returns:
        Complete system prompt string.
    """
    provider = get_tool_mode_provider(tool_mode)
    tools = provider.build_tools_section()
    keys_section = build_device_keys_section(device_keys)

    if custom_prompt:
        role = _strip_tool_sections(custom_prompt)
    else:
        role = ROLE_SECTION

    return f"{role}\n\n{tools}\n\n{keys_section}"
