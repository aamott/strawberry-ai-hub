"""Tests for the Hub's modular prompt generation.

Covers:
- HubPythonExecToolMode sections
- Provider registry
- build_system_prompt composition
- _strip_tool_sections for legacy custom prompts
- Device keys footer
"""

from __future__ import annotations

import pytest

from hub.prompt import (
    ROLE_SECTION,
    HubPythonExecToolMode,
    ToolModeProvider,
    _strip_tool_sections,
    build_device_keys_section,
    build_system_prompt,
    get_tool_mode_provider,
)

# ---------------------------------------------------------------------------
# Provider registry
# ---------------------------------------------------------------------------


class TestProviderRegistry:
    """Tests for get_tool_mode_provider."""

    def test_default_is_hub_python_exec(self) -> None:
        provider = get_tool_mode_provider()
        assert isinstance(provider, HubPythonExecToolMode)

    def test_explicit_python_exec(self) -> None:
        provider = get_tool_mode_provider("python_exec")
        assert isinstance(provider, HubPythonExecToolMode)

    def test_unknown_mode_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown tool mode"):
            get_tool_mode_provider("nonexistent")

    def test_provider_is_singleton(self) -> None:
        a = get_tool_mode_provider("python_exec")
        b = get_tool_mode_provider("python_exec")
        assert a is b

    def test_is_subclass_of_abc(self) -> None:
        assert issubclass(HubPythonExecToolMode, ToolModeProvider)


# ---------------------------------------------------------------------------
# HubPythonExecToolMode sections
# ---------------------------------------------------------------------------


class TestHubPythonExecToolMode:
    """Tests for the Hub tool mode provider."""

    @pytest.fixture
    def provider(self) -> HubPythonExecToolMode:
        return HubPythonExecToolMode()

    def test_tool_header_lists_three_tools(self, provider) -> None:
        header = provider.tool_header()
        assert "search_skills" in header
        assert "describe_function" in header
        assert "python_exec" in header

    def test_discovery_mentions_devices_hub(self, provider) -> None:
        section = provider.discovery_section()
        assert "devices.hub" in section

    def test_execution_uses_devices_syntax(self, provider) -> None:
        section = provider.execution_section()
        assert "devices.<device>.<SkillClass>.<method>" in section

    def test_execution_warns_against_offline_syntax(self, provider) -> None:
        section = provider.execution_section()
        assert "offline-mode syntax" in section

    def test_examples_have_devices_syntax(self, provider) -> None:
        examples = provider.examples_section()
        assert "devices.<device>" in examples

    def test_rules_mention_python_exec(self, provider) -> None:
        rules = provider.rules_section()
        assert "python_exec" in rules

    def test_build_tools_section_composites_all(self, provider) -> None:
        tools = provider.build_tools_section()
        # Should contain content from all sub-sections
        assert "## Available Tools" in tools
        assert "## search_skills" in tools
        assert "## python_exec" in tools
        assert "## Examples" in tools
        assert "## Rules" in tools


# ---------------------------------------------------------------------------
# Device keys section
# ---------------------------------------------------------------------------


class TestDeviceKeysSection:
    """Tests for device keys footer."""

    def test_includes_device_keys(self) -> None:
        result = build_device_keys_section("hub, my_spoke")
        assert "hub, my_spoke" in result

    def test_empty_keys_shows_none(self) -> None:
        result = build_device_keys_section("")
        assert "(none)" in result

    def test_mentions_hub_for_agnostic(self) -> None:
        result = build_device_keys_section("hub, my_spoke")
        assert "devices.hub" in result


# ---------------------------------------------------------------------------
# build_system_prompt
# ---------------------------------------------------------------------------


class TestBuildSystemPrompt:
    """Tests for full system prompt composition."""

    def test_default_prompt_has_all_parts(self) -> None:
        result = build_system_prompt("hub, my_spoke")
        # Role section
        assert "Strawberry" in result
        # Tools section
        assert "## Available Tools" in result
        assert "python_exec" in result
        # Device keys footer
        assert "hub, my_spoke" in result
        assert "VALID DEVICE KEYS" in result

    def test_no_duplication(self) -> None:
        result = build_system_prompt("hub")
        count = result.count("## Available Tools")
        assert count == 1, f"Expected 1, got {count}"

    def test_custom_prompt_replaces_role(self) -> None:
        result = build_system_prompt(
            "hub", custom_prompt="You are Captain Pirate.",
        )
        assert "Captain Pirate" in result
        # Still has tools section
        assert "## Available Tools" in result
        # Default role is replaced
        assert ROLE_SECTION not in result

    def test_legacy_custom_prompt_stripped(self) -> None:
        """Legacy prompt with baked-in tool sections: no duplication."""
        legacy = (
            "You are Custom Bot.\n\n"
            "## Available Tools\n\n"
            "1) old tools list\n\n"
            "## python_exec\n\n"
            "old instructions\n\n"
            "## Rules\n\n"
            "old rules\n"
        )
        result = build_system_prompt("hub", custom_prompt=legacy)
        count = result.count("## Available Tools")
        assert count == 1, f"Expected 1, got {count}"
        # Custom role text preserved
        assert "Custom Bot" in result


# ---------------------------------------------------------------------------
# _strip_tool_sections
# ---------------------------------------------------------------------------


class TestStripToolSections:
    """Tests for legacy tool section stripping."""

    def test_strips_known_headers(self) -> None:
        text = "Role.\n\n## Available Tools\n\nContent.\n"
        result = _strip_tool_sections(text)
        assert "Role." in result
        assert "Available Tools" not in result

    def test_preserves_non_tool_headings(self) -> None:
        text = "Role.\n\n## My Section\n\nKeep.\n## python_exec\n\nStrip.\n"
        result = _strip_tool_sections(text)
        assert "My Section" in result
        assert "Keep" in result
        assert "python_exec" not in result

    def test_all_tool_headers_stripped(self) -> None:
        headers = [
            "## Available Tools", "## search_skills",
            "## describe_function", "## python_exec",
            "## Examples", "## Rules", "## Searching Tips",
            "## Critical Notes",
        ]
        text = "Personality.\n\n" + "\n\nBody.\n\n".join(headers)
        result = _strip_tool_sections(text)
        assert "Personality." in result
        for h in headers:
            assert h not in result
