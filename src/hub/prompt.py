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
You are Strawberry, a helpful AI assistant. You have access to skills
(specialized tools) across all connected devices that let you perform
real-world actions — controlling smart home devices, checking weather,
searching documents, and more.

Use your tools to accomplish tasks. When you're unsure what's available,
search first, then act. Ask followup questions when needed, but try to
accomplish the user's request in as few steps as possible. Overall, remember
you're a smart agent - you can figure things out!"""


# ---------------------------------------------------------------------------
# ToolModeProvider ABC (same interface as spoke)
# ---------------------------------------------------------------------------


class ToolModeProvider(ABC):
    """Base class for tool-mode-specific prompt content and behavior.

    Each tool mode implements this interface to define both:
    - **System prompt sections** (what the LLM sees at conversation start)
    - **Behavioral hooks** (post-tool-call steering, iteration control)

    The shared composition logic lives in :meth:`build_tools_section`.
    Behavioral hooks are called by the agent loop in ``chat.py`` to
    inject per-tool guidance messages after each tool execution.
    """

    # -- System prompt sections (abstract) -----------------------------------

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

    # -- Behavioral hooks (abstract) -----------------------------------------

    @abstractmethod
    def tool_result_guidance(self, tool_name: str, success: bool) -> str:
        """Return a steering message to inject after a tool call completes.

        The agent loop appends this as a user-role message (or embeds it
        alongside ``tool_result`` blocks) so the LLM knows what to do
        next — e.g. "respond to the user" or "call the skill tool now".

        Args:
            tool_name: Name of the tool that just ran (e.g.
                ``"search_skills"``, ``"WeatherSkill__get_current_weather"``).
            success: Whether the tool call succeeded.

        Returns:
            Guidance string.  May be empty if no guidance is needed.
        """


    @abstractmethod
    def max_discovery_after_execution(self) -> int:
        """Maximum discovery-tool calls allowed after a skill tool has
        already returned a result.

        Once this limit is exceeded, the loop injects a forceful nudge
        telling the model to stop calling tools and respond.  This
        prevents the "tool-happy" pattern where the model calls
        ``describe_function`` and ``search_skills`` after already having
        the data it needs.

        Returns:
            Max discovery calls.  0 means no limit.
        """

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
        """List the available tools."""
        return """\
## Available Tools

1) search_skills(query) - Find skills by keyword. Might require a few queries
   to find the right skill.
2) describe_function(path) - Get full signature and docstring for a
   skill method.
3) python_exec(code) - Execute Python code to call skills."""

    def discovery_section(self) -> str:
        """Describe search_skills for Hub (multi-device)."""
        return """\
## search_skills

search_skills(query) returns matching skill methods, the devices
they belong to, and short descriptions. If a skill appears on
multiple devices, prefer the `preferred_device` if present.

Example: search_skills(query="weather")"""

    def describe_section(self) -> str:
        """Describe describe_function."""
        return """\
## describe_function

describe_function(path) returns the full signature and docstring
for a skill method. Use it when you need more details about a skill method
or a skill isn't behaving as expected."""

    def execution_section(self) -> str:
        """Describe python_exec for Hub (always devices.*)."""
        return """\
## python_exec

Execute skills via python_exec. Syntax:
  python_exec(code="print(devices.<device>.<Skill>.<method>(...))")

Always print() the result of the function call so you can see it.
<device> has no default value, so you must specify it based on available
devices.
"""

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

Smart Home:
- User: "Turn on the rocketship lamp"
  a) search_skills(query="smart home")
  b) python_exec(code="print(
     devices.<device>.HomeAssistantSkill__HassTurnOn(
     entity_id='light.rocketship_lamp'))")
  c) Respond naturally with the result.
  d) User: "Now turn it off"
  e) python_exec(code="print(
     devices.<device>.HomeAssistantSkill__HassTurnOff(
     entity_id='light.rocketship_lamp'))")
  f) Respond naturally with the result.
     """

    def rules_section(self) -> str:
        """Minimal rules — most steering is via tool_result_guidance."""
        return """\
## Important

- Always print() results inside python_exec.
- If a tool call fails, fix the error and retry.
- If multiple skills match, pick the best and proceed."""

    # -- Behavioral hooks ---------------------------------------------------

    def tool_result_guidance(self, tool_name: str, success: bool) -> str:
        """Steer the LLM after each tool call."""
        if not success:
            return (
                "Fix the error and try again with corrected arguments."
            )
        if tool_name == "search_skills":
            return (
                "Now call python_exec to execute the skill. "
                "search_skills only finds skills — it does NOT run them."
            )
        if tool_name == "describe_function":
            return "Now call python_exec to execute the skill."
        # python_exec or any other tool
        return (
            "Give the user a short, natural-language answer "
            "confirming what was done. Do NOT repeat this tool call."
        )


    def max_discovery_after_execution(self) -> int:
        """No limit on discovery calls for Hub python_exec mode."""
        return 0


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
        """List the available tools in native mode."""
        return """\
## Available Tools

"Skills" are tools provided to you to complete user requests. Be smart while
using them. Try to fulfill the user's request in one shot, but don't be afraid
to ask for clarification if needed, do multiple searches, or describe multiple
functions.

Discovery helpers:
1) search_skills(query) - Find skills by keyword.
    It's a pretty basic search, so try multiple queries if needed.
2) describe_function(path) - Get more info about a skill. Can be helpful when
   a skill fails or you need to know more about it."""

    def discovery_section(self) -> str:
        """Describe search_skills."""
        return """\
## search_skills

search_skills(query) returns matching skill names, devices, and
short descriptions. Use this when you're not sure which tool to call.

Example: search_skills(query="weather")"""

    def describe_section(self) -> str:
        """Describe describe_function."""
        return """\
## describe_function

describe_function(path) returns the full signature and docstring
for a skill method. Use it when you need parameter details or a
skill isn't responding as expected."""

    def execution_section(self) -> str:
        """Describe native tool calling syntax."""
        return """\
## Calling Skills

Call skill tools directly by name using the pattern:
  ToolName(param=value)

Include the `device` parameter to target a specific device. Some skills
require the `device` parameter. """

    def examples_section(self) -> str:
        """Provide native-mode examples."""
        return """\
## Examples

Weather:
- User: "What's the weather in San Francisco?"
  a) search_skills(query="weather")
  b) WeatherSkill__get_current_weather(
         location="San Francisco, CA")

Home Assistant:
- User: "Turn on the kitchen lamp"
  a) search_skills(query="turn on light")
  b) HomeAssistantSkill__HassTurnOn(
         name="Kitchen Lamp",
         device="home_server")"""

    def rules_section(self) -> str:
        """Minimal native-mode rules."""
        return """\
## Important

- Call tools directly — do NOT use python_exec.
- If a tool call fails, check describe_function for correct
  parameters and retry."""

    # -- Behavioral hooks ---------------------------------------------------

    _DISCOVERY_TOOLS = frozenset({"search_skills", "describe_function"})

    def tool_result_guidance(self, tool_name: str, success: bool) -> str:
        """Steer the LLM after each tool call."""
        if not success:
            return (
                "The tool call failed. Check describe_function for "
                "correct parameter names and types, then retry."
            )
        if tool_name in self._DISCOVERY_TOOLS:
            return "Now call the appropriate skill tool directly."
        # A skill tool succeeded — strong nudge to respond.
        return (
            "You have the result. Respond to the user in natural "
            "language now. Do NOT call search_skills or "
            "describe_function — you already have the data you need."
        )


    def max_discovery_after_execution(self) -> int:
        """Allow up to 2 discovery calls after a skill tool returns."""
        return 2


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
    "important",
    "calling skills",
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
