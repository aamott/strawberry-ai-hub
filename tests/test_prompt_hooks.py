"""Unit tests for ToolModeProvider behavioral hooks and chat.py steering helpers."""


import pytest

from hub.prompt import (
    HubNativeToolMode,
    HubPythonExecToolMode,
    get_tool_mode_provider,
)
from hub.routers.chat import (
    _build_iteration_kwargs,
    _count_discovery_calls,
)
from hub.routers.chat.tool_execution import (
    build_aggregate_guidance as _build_aggregate_guidance,
)

# ---------------------------------------------------------------------------
# Provider behavioral hook tests
# ---------------------------------------------------------------------------


class TestPythonExecToolModeHooks:
    """Verify HubPythonExecToolMode behavioral hooks."""

    def setup_method(self):
        self.provider = HubPythonExecToolMode()

    def test_guidance_after_search_skills_success(self):
        guidance = self.provider.tool_result_guidance("search_skills", True)
        assert "python_exec" in guidance
        assert "NOT run" in guidance

    def test_guidance_after_describe_function_success(self):
        guidance = self.provider.tool_result_guidance("describe_function", True)
        assert "python_exec" in guidance

    def test_guidance_after_python_exec_success(self):
        guidance = self.provider.tool_result_guidance("python_exec", True)
        assert "natural-language" in guidance
        assert "Do NOT repeat" in guidance

    def test_guidance_on_failure(self):
        guidance = self.provider.tool_result_guidance("search_skills", False)
        assert "Fix" in guidance


    def test_max_discovery_after_execution_zero(self):
        assert self.provider.max_discovery_after_execution() == 0


class TestNativeToolModeHooks:
    """Verify HubNativeToolMode behavioral hooks."""

    def setup_method(self):
        self.provider = HubNativeToolMode()

    def test_guidance_after_search_skills_success(self):
        guidance = self.provider.tool_result_guidance("search_skills", True)
        assert "skill tool" in guidance.lower()

    def test_guidance_after_describe_function_success(self):
        guidance = self.provider.tool_result_guidance("describe_function", True)
        assert "skill tool" in guidance.lower()

    def test_guidance_after_skill_tool_success(self):
        guidance = self.provider.tool_result_guidance(
            "WeatherSkill__get_current_weather", True,
        )
        assert "Respond" in guidance
        assert "Do NOT call search_skills" in guidance

    def test_guidance_on_failure(self):
        guidance = self.provider.tool_result_guidance(
            "WeatherSkill__get_current_weather", False,
        )
        assert "failed" in guidance.lower()
        assert "describe_function" in guidance


    def test_max_discovery_after_execution_positive(self):
        limit = self.provider.max_discovery_after_execution()
        assert limit > 0
        assert limit == 2

    def test_rules_section_contains_stop_guidance(self):
        """The system prompt rules should reinforce the behavioral hooks."""
        rules = self.provider.rules_section()
        assert "IMMEDIATELY" in rules or "never after" in rules


class TestProviderRegistry:
    def test_python_exec_provider(self):
        p = get_tool_mode_provider("python_exec")
        assert isinstance(p, HubPythonExecToolMode)

    def test_native_provider(self):
        p = get_tool_mode_provider("native")
        assert isinstance(p, HubNativeToolMode)

    def test_unknown_provider_raises(self):
        with pytest.raises(ValueError, match="Unknown tool mode"):
            get_tool_mode_provider("nonexistent")


# ---------------------------------------------------------------------------
# Chat.py steering helper tests
# ---------------------------------------------------------------------------


class TestCountDiscoveryCalls:
    def test_counts_search_skills(self):
        calls = [
            {"name": "search_skills", "arguments": {}},
            {"name": "WeatherSkill__get_current_weather", "arguments": {}},
        ]
        assert _count_discovery_calls(calls, had_execution=True) == 1

    def test_counts_describe_function(self):
        calls = [{"name": "describe_function", "arguments": {}}]
        assert _count_discovery_calls(calls, had_execution=True) == 1

    def test_counts_both(self):
        calls = [
            {"name": "search_skills", "arguments": {}},
            {"name": "describe_function", "arguments": {}},
        ]
        assert _count_discovery_calls(calls, had_execution=True) == 2

    def test_zero_when_no_prior_execution(self):
        calls = [{"name": "search_skills", "arguments": {}}]
        assert _count_discovery_calls(calls, had_execution=False) == 0

    def test_zero_for_skill_calls_only(self):
        calls = [
            {"name": "WeatherSkill__get_current_weather", "arguments": {}},
        ]
        assert _count_discovery_calls(calls, had_execution=True) == 0


class TestBuildIterationKwargs:
    def test_no_enforcement_when_limit_zero(self):
        messages: list = []
        kwargs, event = _build_iteration_kwargs(
            tz_kwargs={}, discovery_limit=0, discovery_count=5,
            had_execution=True, all_calls_skipped=False, messages=messages,
        )
        assert event is None
        assert "tool_choice" not in kwargs

    def test_no_enforcement_when_under_limit(self):
        messages: list = []
        kwargs, event = _build_iteration_kwargs(
            tz_kwargs={}, discovery_limit=3, discovery_count=1,
            had_execution=True, all_calls_skipped=False, messages=messages,
        )
        assert event is None
        assert "tool_choice" not in kwargs

    def test_no_enforcement_when_no_execution(self):
        messages: list = []
        kwargs, event = _build_iteration_kwargs(
            tz_kwargs={}, discovery_limit=2, discovery_count=5,
            had_execution=False, all_calls_skipped=False, messages=messages,
        )
        assert event is None

    def test_enforces_when_discovery_limit_exceeded(self):
        messages: list = []
        kwargs, event = _build_iteration_kwargs(
            tz_kwargs={"extra": 1}, discovery_limit=2, discovery_count=2,
            had_execution=True, all_calls_skipped=False, messages=messages,
        )
        assert event is not None
        assert event["type"] == "injected_message"
        assert kwargs["tool_choice"] == "none"
        assert kwargs["extra"] == 1
        assert len(messages) == 1

    def test_force_text_takes_priority(self):
        messages: list = []
        kwargs, event = _build_iteration_kwargs(
            tz_kwargs={}, discovery_limit=0, discovery_count=0,
            had_execution=False, all_calls_skipped=True, messages=messages,
        )
        assert event is not None
        assert kwargs["tool_choice"] == "none"
        assert len(messages) == 1

    def test_does_not_mutate_original_kwargs(self):
        messages: list = []
        original = {"key": "value"}
        kwargs, _ = _build_iteration_kwargs(
            tz_kwargs=original, discovery_limit=2, discovery_count=3,
            had_execution=True, all_calls_skipped=False, messages=messages,
        )
        assert "tool_choice" not in original
        assert "tool_choice" in kwargs


class TestBuildAggregateGuidance:
    """Test the aggregate guidance builder used by _inject_tool_results."""

    def test_fallback_when_no_provider(self):
        guidance = _build_aggregate_guidance([], [], provider=None)
        assert "respond naturally" in guidance.lower()

    def test_native_skill_success_guidance(self):
        provider = HubNativeToolMode()
        tool_calls = [
            {"id": "tc1", "name": "WeatherSkill__get_current_weather"},
        ]
        results = [
            {"tool_call_id": "tc1", "success": True, "result": "sunny"},
        ]
        guidance = _build_aggregate_guidance(tool_calls, results, provider)
        assert "Respond" in guidance
        assert "Do NOT call search_skills" in guidance

    def test_native_discovery_guidance(self):
        provider = HubNativeToolMode()
        tool_calls = [
            {"id": "tc1", "name": "search_skills"},
        ]
        results = [
            {"tool_call_id": "tc1", "success": True, "result": "found skills"},
        ]
        guidance = _build_aggregate_guidance(tool_calls, results, provider)
        assert "skill tool" in guidance.lower()

    def test_python_exec_success_guidance(self):
        provider = HubPythonExecToolMode()
        tool_calls = [
            {"id": "tc1", "name": "python_exec"},
        ]
        results = [
            {"tool_call_id": "tc1", "success": True, "result": "42"},
        ]
        guidance = _build_aggregate_guidance(tool_calls, results, provider)
        assert "natural-language" in guidance

    def test_deduplicates_identical_guidance(self):
        """Multiple tools with the same guidance should not repeat."""
        provider = HubNativeToolMode()
        tool_calls = [
            {"id": "tc1", "name": "WeatherSkill__get_current_weather"},
            {"id": "tc2", "name": "WeatherSkill__get_forecast"},
        ]
        results = [
            {"tool_call_id": "tc1", "success": True, "result": "sunny"},
            {"tool_call_id": "tc2", "success": True, "result": "rainy"},
        ]
        guidance = _build_aggregate_guidance(tool_calls, results, provider)
        # Should appear only once, not twice
        assert guidance.count("Do NOT call search_skills") == 1
