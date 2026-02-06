"""TensorZero embedded gateway service for Strawberry Hub.

Provides a singleton async gateway that routes LLM requests through
TensorZero with fallback support between providers.
"""

import os
from pathlib import Path
from typing import Any, Optional

try:
    from tensorzero import AsyncTensorZeroGateway
except Exception:  # pragma: no cover
    AsyncTensorZeroGateway = None  # type: ignore[assignment]

# Global gateway instance (lazy initialization)
_gateway: Optional[AsyncTensorZeroGateway] = None
_gateway_initialized: bool = False


def get_config_path() -> str:
    """Get the path to tensorzero.toml config file.
    
    Returns:
        Absolute path to the config file.
    """
    # Check for override via environment variable
    config_path = os.getenv("TENSORZERO_CONFIG_PATH")
    if config_path:
        return config_path
    
    # Default: config/tensorzero.toml relative to project root
    # The project root is two levels up from this file (src/hub/)
    hub_dir = Path(__file__).parent
    project_root = hub_dir.parent.parent
    return str(project_root / "config" / "tensorzero.toml")


async def get_gateway() -> AsyncTensorZeroGateway:
    """Get or create the TensorZero gateway instance.
    
    Returns:
        The initialized AsyncTensorZeroGateway instance.
        
    Raises:
        RuntimeError: If gateway initialization fails.
    """
    global _gateway, _gateway_initialized

    if AsyncTensorZeroGateway is None:
        raise RuntimeError(
            "TensorZero is not installed. Install the 'tensorzero' package to enable Hub chat."
        )
    
    if _gateway is not None and _gateway_initialized:
        return _gateway
    
    config_path = get_config_path()
    
    # Build embedded gateway (no external process needed)
    # clickhouse_url is optional - omit for no observability
    _gateway = await AsyncTensorZeroGateway.build_embedded(
        config_file=config_path,
        async_setup=True,
    )
    _gateway_initialized = True
    
    return _gateway


async def shutdown_gateway() -> None:
    """Shutdown the TensorZero gateway gracefully."""
    global _gateway, _gateway_initialized
    
    if _gateway is not None:
        # AsyncTensorZeroGateway should be used as context manager,
        # but for singleton pattern we manage lifecycle manually
        try:
            await _gateway.__aexit__(None, None, None)
        except Exception:
            pass  # Best effort cleanup
        _gateway = None
        _gateway_initialized = False


async def inference(
    messages: list[dict[str, str]],
    function_name: str = "chat",
    system: Optional[str] = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Run inference through the TensorZero gateway.
    
    Args:
        messages: List of chat messages in OpenAI format.
        function_name: TensorZero function to call (default: "chat").
        system: Optional system prompt to include.
        **kwargs: Additional arguments passed to gateway.inference().
        
    Returns:
        The inference response from TensorZero.
    """
    gateway = await get_gateway()
    
    tz_input: dict[str, Any] = {"messages": messages}
    if system:
        tz_input["system"] = system
    
    response = await gateway.inference(
        function_name=function_name,
        input=tz_input,
        **kwargs,
    )
    
    return response


async def inference_stream(
    messages: list[dict[str, str]],
    function_name: str = "chat",
    system: Optional[str] = None,
    **kwargs: Any,
) -> Any:
    """Run streaming inference through the TensorZero gateway.

    Uses ``stream=True`` so the gateway yields chunks as the model
    generates them.

    Args:
        messages: List of chat messages in OpenAI format.
        function_name: TensorZero function to call.
        system: Optional system prompt to include.
        **kwargs: Additional arguments passed to gateway.inference().

    Returns:
        An async iterator of streaming chunks.
    """
    gateway = await get_gateway()

    tz_input: dict[str, Any] = {"messages": messages}
    if system:
        tz_input["system"] = system

    stream = await gateway.inference(
        function_name=function_name,
        input=tz_input,
        stream=True,
        **kwargs,
    )

    return stream
