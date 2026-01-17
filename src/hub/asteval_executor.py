"""Thread-safe asteval-based executor for running LLM-generated Python code.

This module uses `asteval.Interpreter` to safely execute Python code with
support for loops, conditionals, and function calls. Async skill calls are
wrapped in sync proxies that block until the result is available.
"""

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from asteval import Interpreter

logger = logging.getLogger(__name__)


@dataclass
class ExecutionResult:
    """Result of executing code."""

    success: bool
    output: str = ""
    error: Optional[str] = None


class SyncMethodProxy:
    """Wraps an async method to be callable synchronously from asteval.

    When called, it schedules the async method on the event loop and blocks
    until the result is available.
    """

    def __init__(
        self,
        async_method,
        device_name: str,
        skill_name: str,
        method_name: str,
        event_loop: asyncio.AbstractEventLoop,
    ):
        self._async_method = async_method
        self._device_name = device_name
        self._skill_name = skill_name
        self._method_name = method_name
        self._loop = event_loop

    def __call__(self, *args, **kwargs) -> Any:
        """Execute the async method synchronously."""
        logger.debug(
            f"[SyncProxy] Calling {self._device_name}.{self._skill_name}.{self._method_name}"
            f"({args}, {kwargs})"
        )
        try:
            # Schedule the coroutine on the event loop and wait for result
            future = asyncio.run_coroutine_threadsafe(
                self._async_method(*args, **kwargs),
                self._loop,
            )
            result = future.result(timeout=30.0)
            logger.debug(f"[SyncProxy] Result: {result}")
            return result
        except TimeoutError:
            raise TimeoutError(
                f"Skill call timed out: {self._device_name}.{self._skill_name}.{self._method_name}"
            )
        except Exception as e:
            logger.error(f"[SyncProxy] Error: {e}")
            raise


class SyncSkillProxy:
    """Wraps a skill to provide sync method access."""

    def __init__(
        self,
        devices_proxy,
        device_name: str,
        skill_name: str,
        event_loop: asyncio.AbstractEventLoop,
    ):
        self._devices_proxy = devices_proxy
        self._device_name = device_name
        self._skill_name = skill_name
        self._loop = event_loop

    def __getattr__(self, method_name: str) -> SyncMethodProxy:
        """Get a sync proxy for a method."""
        # Create an async method that calls execute_skill
        async def async_method(*args, **kwargs):
            return await self._devices_proxy.execute_skill(
                device_name=self._device_name,
                skill_name=self._skill_name,
                method_name=method_name,
                args=list(args),
                kwargs=kwargs,
            )

        return SyncMethodProxy(
            async_method=async_method,
            device_name=self._device_name,
            skill_name=self._skill_name,
            method_name=method_name,
            event_loop=self._loop,
        )


class SyncDeviceProxy:
    """Wraps a device to provide sync skill access."""

    def __init__(
        self,
        devices_proxy,
        device_name: str,
        event_loop: asyncio.AbstractEventLoop,
    ):
        self._devices_proxy = devices_proxy
        self._device_name = device_name
        self._loop = event_loop

    def __getattr__(self, skill_name: str) -> SyncSkillProxy:
        """Get a sync proxy for a skill on this device."""
        return SyncSkillProxy(
            devices_proxy=self._devices_proxy,
            device_name=self._device_name,
            skill_name=skill_name,
            event_loop=self._loop,
        )


class SyncDevicesProxy:
    """Wraps the async DevicesProxy to be usable synchronously in asteval.

    Provides:
    - devices.device_name.SkillClass.method() - sync skill calls
    - devices.search_skills(query) - sync search
    - devices.describe_function(path) - sync describe
    """

    def __init__(
        self,
        devices_proxy,
        event_loop: asyncio.AbstractEventLoop,
    ):
        self._devices_proxy = devices_proxy
        self._loop = event_loop

    def search_skills(self, query: str = "", device_limit: int = 10) -> List[Dict]:
        """Search for skills (sync wrapper)."""
        future = asyncio.run_coroutine_threadsafe(
            self._devices_proxy.search_skills(query, device_limit),
            self._loop,
        )
        return future.result(timeout=30.0)

    def describe_function(self, path: str) -> str:
        """Describe a function (sync wrapper)."""
        future = asyncio.run_coroutine_threadsafe(
            self._devices_proxy.describe_function(path),
            self._loop,
        )
        return future.result(timeout=30.0)

    def __getattr__(self, device_name: str) -> SyncDeviceProxy:
        """Get a sync proxy for a specific device."""
        return SyncDeviceProxy(
            devices_proxy=self._devices_proxy,
            device_name=device_name,
            event_loop=self._loop,
        )


async def execute_with_asteval(
    code: str,
    devices_proxy,
) -> Dict[str, Any]:
    """Execute LLM-generated Python code using asteval.

    This creates a fresh Interpreter for each execution (thread-safe),
    injects the `devices` proxy as a sync wrapper, and captures output.

    To avoid deadlock, the asteval execution runs in a thread pool executor,
    allowing the sync proxies to block the thread while the main event loop
    continues running and can process the async skill calls.

    Args:
        code: Python code to execute
        devices_proxy: The async DevicesProxy for skill access

    Returns:
        Dict with "result" or "error" key
    """

    # Get the current event loop (we'll pass it to the thread)
    loop = asyncio.get_running_loop()

    def run_in_thread():
        """Run asteval in a thread so sync proxies can block without deadlock."""
        output_buffer: List[str] = []

        def custom_print(*args, **kwargs):
            """Capture print output."""
            text = " ".join(str(a) for a in args)
            output_buffer.append(text)

        # Create sync wrapper for devices proxy
        sync_devices = SyncDevicesProxy(devices_proxy, loop)

        # Create a fresh interpreter (thread-safe)
        aeval = Interpreter(
            usersyms={
                "devices": sync_devices,
                "device_manager": sync_devices,  # Alias
                "print": custom_print,
            },
            no_print=True,  # We handle print ourselves
        )

        try:
            logger.info(f"[asteval] Executing code:\n{code}")

            # Execute the code
            result = aeval(code)

            # Check for errors
            if aeval.error:
                error_msgs = []
                for err in aeval.error:
                    error_msgs.append(str(err.get_error()))
                error_str = "\n".join(error_msgs)
                logger.error(f"[asteval] Errors: {error_str}")
                return {"error": error_str}

            # Combine output
            output = "\n".join(output_buffer).strip()
            if not output and result is not None:
                output = str(result)

            logger.info(f"[asteval] Output: {output or '(no output)'}")
            return {"result": output or "(no output)"}

        except Exception as e:
            logger.error(f"[asteval] Exception: {e}")
            return {"error": f"{type(e).__name__}: {e}"}

    # Use await run_in_executor so the event loop keeps running
    # This allows the sync proxies' run_coroutine_threadsafe calls to complete
    return await loop.run_in_executor(None, run_in_thread)
