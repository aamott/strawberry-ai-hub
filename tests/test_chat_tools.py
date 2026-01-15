"""Integration tests for Hub chat with tool execution."""

import os

import pytest
from unittest.mock import MagicMock, patch


# Mock TensorZero response for testing
class MockTensorZeroResponse:
    def __init__(self, content_text="", tool_calls=None):
        self.content = []
        if content_text:
            self.content.append(MockTextBlock(content_text))
        if tool_calls:
            for tc in tool_calls:
                self.content.append(MockToolCallBlock(tc["name"], tc["arguments"]))
        self.variant_name = "test_variant"


class MockTextBlock:
    def __init__(self, text):
        self.text = text
        self.type = "text"


class MockToolCallBlock:
    def __init__(self, name, arguments):
        self.type = "tool_call"
        self.name = name
        self.arguments = arguments
        self.id = "test_call_id"


@pytest.mark.asyncio
async def test_chat_with_tools_search_skills(auth_client):
    """Test chat endpoint with enable_tools=true can search for skills."""
    # Register a test skill first
    await auth_client.post(
        "/skills/register",
        json={
            "skills": [
                {
                    "class_name": "CalculatorSkill",
                    "function_name": "add",
                    "signature": "add(a: int, b: int) -> int",
                    "docstring": "Add two numbers together.",
                }
            ]
        },
    )
    
    # Send heartbeat to keep skill alive
    await auth_client.post("/skills/heartbeat")
    
    # Mock TensorZero to simulate tool call
    async def mock_inference(messages, function_name, **kwargs):
        # First call: LLM decides to search for skills
        if len(messages) == 2:  # System prompt + user message
            return MockTensorZeroResponse(
                content_text="",
                tool_calls=[{"name": "search_skills", "arguments": {"query": "calculator"}}]
            )
        # Second call: LLM responds with the search results
        else:
            return MockTensorZeroResponse(content_text="Found the calculator skill!")
    
    with patch("hub.routers.chat.tz_inference", side_effect=mock_inference):
        # Call chat with tools enabled
        response = await auth_client.post(
            "/api/v1/chat/completions",
            json={
                "model": "gpt-4o-mini",
                "messages": [
                    {"role": "user", "content": "Search for calculator skills"}
                ],
                "enable_tools": True,
            },
        )
        
        # Should get a response with tool execution log
        assert response.status_code == 200
        data = response.json()
        assert "choices" in data
        assert len(data["choices"]) > 0
        content = data["choices"][0]["message"]["content"]
        assert "Tool Execution Log" in content or "search_skills" in content


@pytest.mark.asyncio
async def test_chat_with_tools_calculator_skill(auth_client, monkeypatch):
    """Test chat endpoint can execute calculator skill through Hub.
    
    This test mocks the WebSocket connection manager since we don't have
    a real Spoke connected in tests.
    """
    # Register calculator skill
    await auth_client.post(
        "/skills/register",
        json={
            "skills": [
                {
                    "class_name": "CalculatorSkill",
                    "function_name": "add",
                    "signature": "add(a: int, b: int) -> int",
                    "docstring": "Add two numbers together.",
                },
                {
                    "class_name": "CalculatorSkill",
                    "function_name": "multiply",
                    "signature": "multiply(a: int, b: int) -> int",
                    "docstring": "Multiply two numbers together.",
                },
            ]
        },
    )
    
    # Send heartbeat
    await auth_client.post("/skills/heartbeat")
    
    # Mock the WebSocket connection manager
    from hub.routers.websocket import connection_manager
    
    # Mock device connection check
    original_is_connected = connection_manager.is_connected
    connection_manager.is_connected = MagicMock(return_value=True)
    
    # Mock skill execution to return a result
    async def mock_send_skill_request(device_id, skill_name, method_name, args, kwargs, timeout):
        """Mock skill execution."""
        if skill_name == "CalculatorSkill" and method_name == "add":
            a = args[0] if args else kwargs.get("a", 0)
            b = args[1] if len(args) > 1 else kwargs.get("b", 0)
            return a + b
        elif skill_name == "CalculatorSkill" and method_name == "multiply":
            a = args[0] if args else kwargs.get("a", 1)
            b = args[1] if len(args) > 1 else kwargs.get("b", 1)
            return a * b
        return 0
    
    original_send_skill_request = connection_manager.send_skill_request
    connection_manager.send_skill_request = mock_send_skill_request
    
    try:
        async def mock_inference(messages, function_name, **kwargs):
            # First call: request tool execution via python_exec
            if len(messages) == 2:  # System prompt + user message
                return MockTensorZeroResponse(
                    content_text="",
                    tool_calls=[
                        {
                            "name": "python_exec",
                            "arguments": {
                                "code": "print(devices.test_device.CalculatorSkill.add(a=5, b=3))"
                            },
                        }
                    ],
                )

            # Second call: LLM produces a final natural-language response
            return MockTensorZeroResponse(content_text="The answer is 8.")

        with patch("hub.routers.chat.tz_inference", side_effect=mock_inference):
            # Call chat with a request to use calculator
            response = await auth_client.post(
                "/api/v1/chat/completions",
                json={
                    "model": "gpt-4o-mini",
                    "messages": [
                        {
                            "role": "user",
                            "content": "Use the calculator to add 5 and 3.",
                        }
                    ],
                    "enable_tools": True,
                },
            )
        
        assert response.status_code == 200
        data = response.json()
        assert "choices" in data
        assert len(data["choices"]) > 0
        
        # Check that we got a response (the actual content will depend on the LLM)
        content = data["choices"][0]["message"]["content"]
        assert content is not None
        
    finally:
        # Restore original methods
        connection_manager.is_connected = original_is_connected
        connection_manager.send_skill_request = original_send_skill_request


@pytest.mark.asyncio
async def test_chat_with_tools_dynamic_skill_method_called_as_tool(auth_client):
    """If the model calls a skill method directly as a tool, Hub should still execute it.

    This covers the real-world failure mode observed with weather:
    the model calls `get_current_weather(...)` instead of using python_exec.
    """
    await auth_client.post(
        "/skills/register",
        json={
            "skills": [
                {
                    "class_name": "CalculatorSkill",
                    "function_name": "add",
                    "signature": "add(a: int, b: int) -> int",
                    "docstring": "Add two numbers together.",
                }
            ]
        },
    )
    await auth_client.post("/skills/heartbeat")

    from hub.routers.websocket import connection_manager

    original_is_connected = connection_manager.is_connected
    original_send_skill_request = connection_manager.send_skill_request
    connection_manager.is_connected = MagicMock(return_value=True)

    async def mock_send_skill_request(device_id, skill_name, method_name, args, kwargs, timeout):
        assert skill_name == "CalculatorSkill"
        assert method_name == "add"
        return int(kwargs.get("a")) + int(kwargs.get("b"))

    connection_manager.send_skill_request = mock_send_skill_request

    try:
        async def mock_inference(messages, function_name, **kwargs):
            # First call: model incorrectly calls skill method as tool
            if len(messages) == 2:
                return MockTensorZeroResponse(
                    content_text="",
                    tool_calls=[{"name": "add", "arguments": {"a": 5, "b": 3}}],
                )
            return MockTensorZeroResponse(content_text="8")

        with patch("hub.routers.chat.tz_inference", side_effect=mock_inference):
            response = await auth_client.post(
                "/api/v1/chat/completions",
                json={
                    "model": "gpt-4o-mini",
                    "messages": [{"role": "user", "content": "Add 5 and 3."}],
                    "enable_tools": True,
                },
            )

        assert response.status_code == 200
        data = response.json()
        content = data["choices"][0]["message"]["content"]
        assert "Tool Execution Log" in content
        assert "add" in content
        assert "8" in content

    finally:
        connection_manager.is_connected = original_is_connected
        connection_manager.send_skill_request = original_send_skill_request


@pytest.mark.asyncio
async def test_chat_dedupes_identical_tool_calls_across_iterations(auth_client):
    """Hub should not re-execute identical tool calls repeatedly across iterations."""
    # We patch HubSkillService.execute_tool to count how many times the Hub
    # actually executes a tool call. The agent loop should cache results and
    # avoid calling execute_tool twice for identical (name,args) pairs.
    from hub.skill_service import HubSkillService

    execute_count = {"count": 0}

    async def mock_execute_tool(self, tool_name, arguments):
        execute_count["count"] += 1
        return {"result": "8"}

    async def mock_inference(messages, function_name, **kwargs):
        # Iteration 1: request python_exec
        if len(messages) == 2:
            return MockTensorZeroResponse(
                content_text="",
                tool_calls=[{"name": "python_exec", "arguments": {"code": "print(8)"}}],
            )

        # Iteration 2: repeat the *exact same* tool call (should be deduped)
        if "[Tool Results]" in str(messages[-1].get("content", "")) and len(messages) < 6:
            return MockTensorZeroResponse(
                content_text="",
                tool_calls=[{"name": "python_exec", "arguments": {"code": "print(8)"}}],
            )

        return MockTensorZeroResponse(content_text="The answer is 8.")

    with patch("hub.routers.chat.tz_inference", side_effect=mock_inference):
        with patch.object(HubSkillService, "execute_tool", new=mock_execute_tool):
            response = await auth_client.post(
                "/api/v1/chat/completions",
                json={
                    "model": "gpt-4o-mini",
                    "messages": [{"role": "user", "content": "Add 5 and 3."}],
                    "enable_tools": True,
                },
            )

    assert response.status_code == 200
    assert execute_count["count"] == 1


@pytest.mark.asyncio
async def test_chat_without_tools(auth_client):
    """Test chat endpoint without tools (default behavior)."""

    async def mock_inference(messages, function_name, **kwargs):
        return MockTensorZeroResponse(content_text="Hello!")

    with patch("hub.routers.chat.tz_inference", side_effect=mock_inference):
        response = await auth_client.post(
            "/api/v1/chat/completions",
            json={
                "model": "gpt-4o-mini",
                "messages": [
                    {"role": "user", "content": "Hello, how are you?"}
                ],
                "enable_tools": False,
            },
        )
    
    assert response.status_code == 200
    data = response.json()
    assert "choices" in data
    assert len(data["choices"]) > 0


@pytest.mark.asyncio
@pytest.mark.skipif(
    os.environ.get("RUN_LIVE_LLM_TESTS") != "1",
    reason="Set RUN_LIVE_LLM_TESTS=1 to enable live LLM integration test",
)
async def test_live_llm_tool_search_and_calculator_exec(auth_client):
    """Live integration test that uses the real tz_inference call.

    We still mock the websocket backend so this test doesn't require an actual
    Spoke process, but it verifies:
    - system prompt + agent loop can drive tool use
    - tool search is available
    - python_exec path can lead to a skill call
    """
    api_key = os.environ.get("GOOGLE_AI_STUDIO_API_KEY")
    if not api_key or api_key.strip() in {"", "CHANGEME", "YOUR_API_KEY"}:
        pytest.fail("GOOGLE_AI_STUDIO_API_KEY is required for live LLM tests")

    await auth_client.post(
        "/skills/register",
        json={
            "skills": [
                {
                    "class_name": "CalculatorSkill",
                    "function_name": "add",
                    "signature": "add(a: int, b: int) -> int",
                    "docstring": "Add two numbers together.",
                }
            ]
        },
    )
    await auth_client.post("/skills/heartbeat")

    from hub.routers.websocket import connection_manager

    original_is_connected = connection_manager.is_connected
    original_send_skill_request = connection_manager.send_skill_request
    connection_manager.is_connected = MagicMock(return_value=True)

    async def mock_send_skill_request(device_id, skill_name, method_name, args, kwargs, timeout):
        if skill_name == "CalculatorSkill" and method_name == "add":
            return int(kwargs.get("a")) + int(kwargs.get("b"))
        raise RuntimeError(f"Unexpected call: {skill_name}.{method_name}")

    connection_manager.send_skill_request = mock_send_skill_request

    try:
        response = await auth_client.post(
            "/api/v1/chat/completions",
            json={
                "model": "gpt-4o-mini",
                "messages": [
                    {
                        "role": "user",
                        "content": (
                            "Find the calculator skill and compute 5+3. "
                            "You MUST use tool calls. Prefer python_exec calling "
                            "devices.test_device.CalculatorSkill.add(a=5, b=3)."
                        ),
                    }
                ],
                "enable_tools": True,
            },
        )

        if response.status_code == 502:
            error_text = response.text or ""
            if "API_KEY_INVALID" in error_text or "API key not valid" in error_text:
                pytest.fail("Live LLM API key is invalid; update GOOGLE_AI_STUDIO_API_KEY")

        assert response.status_code == 200, response.text
        data = response.json()
        content = data["choices"][0]["message"]["content"]
        assert "Tool Execution Log" in content
        assert "5" in content and "3" in content
        assert "8" in content

    finally:
        connection_manager.is_connected = original_is_connected
        connection_manager.send_skill_request = original_send_skill_request
