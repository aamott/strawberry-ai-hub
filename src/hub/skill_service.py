"""Hub Skill Service - Executes tools when Hub runs the agent loop.

This module provides:
- search_skills: Search for skills across all connected devices
- describe_function: Get full function signature and docstring
- python_exec: Execute Python code with access to `devices` object

The `devices` object routes skill calls to target devices via WebSocket.
"""

import json
import logging
import traceback
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .database import Device, Skill
from .utils import normalize_device_name

logger = logging.getLogger(__name__)


# Default system prompt for online mode (Hub executes tools).
# Users can override this via the SYSTEM_PROMPT env var / settings.
# The placeholder {device_keys} is replaced at runtime with the
# list of valid device keys.
DEFAULT_ONLINE_MODE_PROMPT = """SYSTEM INSTRUCTIONS (read carefully and follow exactly):

You are Strawberry, a helpful AI assistant with access to
skills across all connected devices.

## Available Tools

You have exactly 3 tools:
1) search_skills(query) - Find skills by keyword (searches method names and descriptions)
2) describe_function(path) - Get full signature for a skill method
3) python_exec(code) - Execute Python code that calls skills

## Critical Behavior

- Do NOT ask the user for permission to search for skills.
  If a user asks for something that likely needs a skill,
  immediately call search_skills.
- Do NOT say "I can't" until you have searched for
  relevant skills and attempted execution.
- After you find the right skill, execute it immediately.
- Do NOT rerun the same tool call to double-check; use the first result.
- After tool calls complete, ALWAYS provide a final natural-language answer.

## How to Execute Skills

- Always execute skills via python_exec.
- Use the `devices` object for remote devices:
  - devices.<device>.<SkillClass>.<method>(...)
- Wrap skill calls in print(...), so the result is surfaced to the user.

## Device Selection

- Always choose the device key from the `devices` list returned by search_skills().
- Prefer `preferred_device` if present.
- Never invent device keys.
- Do NOT use offline-mode syntax like device.<SkillClass>.<method>(...) in online mode.

## Searching Tips

search_skills matches against method names, skill names, and descriptions.
Search by **action** or **verb**, not by specific entity/object names.
- To turn on a lamp, search 'turn on' not 'lamp'.
- To set brightness, search 'light' or 'brightness'.
- To look up docs, search 'documentation' or 'query'.

## Standard Operating Procedure

1) If the user request could be handled by a skill:
   - Call search_skills with a concise query (use action words).
2) Pick the best match (prefer the highest-relevance
   entry and a device that is available).
3) Call python_exec with code that prints the skill result.
4) Respond naturally using the returned output.

## Examples

Weather:
- User: "What's the weather in Roy, UT?"
  a) search_skills(query="weather")
  b) python_exec(code="print(
     devices.<device>.WeatherSkill
     .get_current_weather('Roy, UT'))")

Calculator:
- User: "Add 5 and 3"
  a) search_skills(query="calculator")
  b) python_exec(code="print(
     devices.<device>.CalculatorSkill.add(a=5, b=3))")

Smart Home (turn on/off, lights, locks, media):
- User: "Turn on the short lamp"
  a) search_skills(query="turn on")
  b) python_exec(code="print(
     devices.<device>.HomeAssistantSkill
     .HassTurnOn(name='short lamp'))")

Documentation lookup:
- User: "Look up React docs"
  a) search_skills(query="documentation")
  b) python_exec(code="print(
     devices.<device>.Context7Skill
     .resolve_library_id(libraryName='react'))")
  c) python_exec(code="print(
     devices.<device>.Context7Skill
     .query_docs(libraryId='...', query='getting started'))")

## Rules

1. Use python_exec to call skills - do NOT call skill methods directly as tools.
2. Do NOT output code blocks or ```tool_outputs``` - use actual tool calls.
3. Keep responses concise and friendly.
4. For smart-home commands (turn on/off, lights, locks,
   media), look for HomeAssistantSkill. Pass the
   device/entity name as the 'name' kwarg.
5. If a tool call fails with 'Unknown tool', immediately
   switch to python_exec and proceed.

If there are multiple possible devices or skills, choose
the most relevant and proceed. Only ask a question if you
are missing required user input (e.g., location is missing).
"""


class DevicesProxy:
    """Proxy object for accessing skills across all devices.

    Used inside python_exec to route skill calls to target devices.
    """

    def __init__(
        self,
        db: AsyncSession,
        user_id: str,
        connection_manager: Any,
    ):
        self._db = db
        self._user_id = user_id
        self._connection_manager = connection_manager
        self._device_cache: Dict[str, Device] = {}

    async def _get_user_devices(self) -> Dict[str, Device]:
        """Get all active devices for the current user."""
        if self._device_cache:
            return self._device_cache

        result = await self._db.execute(
            select(Device).where(
                Device.user_id == self._user_id,
                Device.is_active,
            )
        )
        devices = result.scalars().all()
        self._device_cache = {normalize_device_name(d.name): d for d in devices}
        return self._device_cache

    async def search_skills(
        self,
        query: str = "",
        device_limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """Search for skills across all devices."""
        devices = await self._get_user_devices()

        expiry_time = datetime.now(timezone.utc) - timedelta(
            seconds=settings.skill_expiry_seconds
        )
        result = await self._db.execute(
            select(Skill)
            .where(Skill.device_id.in_([d.id for d in devices.values()]))
            .where(Skill.last_heartbeat > expiry_time)
        )
        skills = result.scalars().all()

        # Filter by query — try all-words first for precision, then
        # fall back to any-word matching if nothing is found.  This keeps
        # "turn on" from matching everything via "on" while still allowing
        # single-concept queries like "react documentation" to work.
        if query:
            query_words = query.lower().split()

            def _matches(s: Skill, mode: str) -> bool:
                searchable = (
                    f"{s.function_name} {s.class_name} {s.docstring or ''}"
                ).lower()
                check = all if mode == "all" else any
                return check(w in searchable for w in query_words)

            filtered = [s for s in skills if _matches(s, "all")]
            if not filtered:
                filtered = [s for s in skills if _matches(s, "any")]
            skills = filtered

        # Group by (class_name, function_name, signature)
        skill_groups: Dict[tuple, Dict] = {}
        device_id_to_name = {
            d.id: normalize_device_name(d.name) for d in devices.values()
        }

        # Pre-fetch connected status for sorting
        connected_device_ids = set()
        if self._connection_manager:
            connected_device_ids = set(self._connection_manager.get_connected_devices())

        for s in skills:
            key = (s.class_name, s.function_name, s.signature)
            device_name = device_id_to_name.get(s.device_id, "unknown")

            if key not in skill_groups:
                summary = ""
                if s.docstring:
                    lines = s.docstring.strip().split("\n")
                    summary = lines[0] if lines else ""

                skill_groups[key] = {
                    "path": f"{s.class_name}.{s.function_name}",
                    "signature": s.signature,
                    "summary": summary,
                    "docstring": s.docstring or "",
                    "devices": [],
                    "device_ids": [],
                }

            skill_groups[key]["devices"].append(device_name)
            skill_groups[key]["device_ids"].append(s.device_id)

        # Format results
        results = []
        max_devices = max(1, min(device_limit, 100))

        for key, group in sorted(skill_groups.items(), key=lambda x: x[0][0]):
            unique_devices = sorted(set(group["devices"]))

            # Sort devices: connected first, then alphabetical
            def _sort_key(d_name):
                # Find device ID for this name (inefficient but safe for small N)
                d_id = next(
                    (
                        did
                        for did, d in devices.items()
                        if normalize_device_name(d.name) == d_name
                    ),
                    None,
                )
                if d_id:
                    d_obj = devices[d_id]
                    is_connected = d_obj.id in connected_device_ids
                    # False < True, so connected comes first.
                    return (not is_connected, d_name)
                return (True, d_name)

            sorted_devices = sorted(unique_devices, key=_sort_key)

            device_sample = sorted_devices[:max_devices]
            preferred_device = device_sample[0] if device_sample else None
            path = group["path"]
            results.append(
                {
                    "path": path,
                    "signature": group["signature"],
                    "summary": group["summary"],
                    "devices": device_sample,
                    "device_count": len(sorted_devices),
                    # TODO: replace "preferred_device" with
                    # instructions to prioritize executing
                    # from the current device, and a reminder
                    # of "current_device: {current_device_name}"
                    # somewhere it won't be
                    # repeated once per result
                    "preferred_device": preferred_device,
                    "call_example": (
                        f"devices.{preferred_device}.{path}(...)"
                        if preferred_device
                        else ""
                    ),
                    "python_exec_example": (
                        f'python_exec(code="print(devices.{preferred_device}.{path}(...))")'
                        if preferred_device
                        else ""
                    ),
                }
            )

        return results

    async def describe_function(self, path: str) -> str:
        """Get full function signature and docstring.

        Args:
            path: Function path like "SkillClass.method_name"
        """
        parts = path.split(".")
        if len(parts) < 2:
            return f"Invalid path format: {path}. Use 'SkillClass.method_name'"

        class_name = parts[0]
        method_name = parts[1]

        devices = await self._get_user_devices()
        expiry_time = datetime.now(timezone.utc) - timedelta(
            seconds=settings.skill_expiry_seconds
        )

        result = await self._db.execute(
            select(Skill)
            .where(Skill.device_id.in_([d.id for d in devices.values()]))
            .where(Skill.last_heartbeat > expiry_time)
            .where(Skill.class_name == class_name)
            .where(Skill.function_name == method_name)
        )
        skill = result.scalars().first()

        if not skill:
            return f"Function not found: {path}"

        # Format output
        output = f"def {skill.signature}:"
        if skill.docstring:
            output += f'\n    """{skill.docstring}"""'

        # Add device info
        result = await self._db.execute(
            select(Skill)
            .where(Skill.device_id.in_([d.id for d in devices.values()]))
            .where(Skill.last_heartbeat > expiry_time)
            .where(Skill.class_name == class_name)
            .where(Skill.function_name == method_name)
        )
        all_instances = result.scalars().all()
        device_id_to_name = {
            d.id: normalize_device_name(d.name) for d in devices.values()
        }
        device_names = sorted(
            set(device_id_to_name.get(s.device_id, "unknown") for s in all_instances)
        )

        if device_names:
            output += f"\n\n# Available on: {', '.join(device_names[:5])}"
            if len(device_names) > 5:
                output += f" (+{len(device_names) - 5} more)"

        return output

    async def execute_skill(
        self,
        device_name: str,
        skill_name: str,
        method_name: str,
        args: List[Any],
        kwargs: Dict[str, Any],
    ) -> Any:
        """Execute a skill on a specific device via WebSocket."""
        devices = await self._get_user_devices()
        normalized = normalize_device_name(device_name)

        device = devices.get(normalized)
        if not device:
            available = ", ".join(sorted(devices.keys()))
            raise ValueError(
                f"Device '{device_name}' not found."
                f" Available devices: {available or '(none)'}"
            )

        if not self._connection_manager.is_connected(device.id):
            raise ValueError(f"Device '{device_name}' is not currently connected")

        try:
            result = await self._connection_manager.send_skill_request(
                device_id=device.id,
                skill_name=skill_name,
                method_name=method_name,
                args=args,
                kwargs=kwargs,
                timeout=30.0,
            )
            return result
        except TimeoutError:
            raise TimeoutError(f"Device '{device_name}' did not respond in time")
        except RuntimeError as e:
            raise RuntimeError(f"Skill execution error: {e}")

    def __getattr__(self, device_name: str) -> "DeviceProxy":
        """Get a proxy for a specific device."""
        return DeviceProxy(self, device_name)


class DeviceProxy:
    """Proxy for a specific device, providing access to its skills."""

    def __init__(self, devices_proxy: DevicesProxy, device_name: str):
        self._devices_proxy = devices_proxy
        self._device_name = device_name

    def __getattr__(self, skill_name: str) -> "SkillProxy":
        """Get a proxy for a specific skill on this device."""
        return SkillProxy(self._devices_proxy, self._device_name, skill_name)


class SkillProxy:
    """Proxy for a specific skill on a specific device."""

    def __init__(
        self,
        devices_proxy: DevicesProxy,
        device_name: str,
        skill_name: str,
    ):
        self._devices_proxy = devices_proxy
        self._device_name = device_name
        self._skill_name = skill_name

    def __getattr__(self, method_name: str) -> "MethodProxy":
        """Get a proxy for a specific method."""
        return MethodProxy(
            self._devices_proxy,
            self._device_name,
            self._skill_name,
            method_name,
        )


class MethodProxy:
    """Proxy for a specific method on a skill."""

    def __init__(
        self,
        devices_proxy: DevicesProxy,
        device_name: str,
        skill_name: str,
        method_name: str,
    ):
        self._devices_proxy = devices_proxy
        self._device_name = device_name
        self._skill_name = skill_name
        self._method_name = method_name

    async def __call__(self, *args, **kwargs) -> Any:
        """Execute the skill method."""
        return await self._devices_proxy.execute_skill(
            device_name=self._device_name,
            skill_name=self._skill_name,
            method_name=self._method_name,
            args=list(args),
            kwargs=kwargs,
        )


class HubSkillService:
    """Service for executing tools on the Hub.

    Provides search_skills, describe_function, and python_exec.
    """

    def __init__(
        self,
        db: AsyncSession,
        user_id: str,
        connection_manager: Any,
    ):
        self.db = db
        self.user_id = user_id
        self.connection_manager = connection_manager
        self._devices_proxy: Optional[DevicesProxy] = None

    @property
    def devices(self) -> DevicesProxy:
        """Get the devices proxy for skill access."""
        if self._devices_proxy is None:
            self._devices_proxy = DevicesProxy(
                db=self.db,
                user_id=self.user_id,
                connection_manager=self.connection_manager,
            )
        return self._devices_proxy

    async def execute_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Execute a tool call.

        Args:
            tool_name: Name of the tool (search_skills, describe_function, python_exec)
            arguments: Tool arguments

        Returns:
            Dict with "result" or "error" key
        """
        try:
            if tool_name == "search_skills":
                query = arguments.get("query", "")
                device_limit = int(arguments.get("device_limit", 10) or 10)
                results = await self.devices.search_skills(query, device_limit)
                return {"result": json.dumps(results, indent=2)}

            elif tool_name == "describe_function":
                path = arguments.get("path", "")
                result = await self.devices.describe_function(path)
                return {"result": result}

            elif tool_name == "python_exec":
                code = arguments.get("code", "")
                result = await self._execute_python(code)
                return result

            else:
                # Dynamic skill execution fallback.
                # Some model variants incorrectly call skill methods directly as tools
                # (e.g., `get_current_weather(...)`). When that happens, we attempt to
                # map the tool name to a registered Skill row and route it via WebSocket.
                return await self._execute_dynamic_skill_tool(tool_name, arguments)

        except Exception as e:
            logger.error(f"Tool execution error: {e}")
            return {"error": f"{type(e).__name__}: {e}\n{traceback.format_exc()}"}

    async def _execute_dynamic_skill_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Execute a tool call by treating it as a skill method invocation.

        This is a compatibility shim for cases where the LLM calls a skill method
        directly as a tool instead of using python_exec.

        Supported tool_name formats:
        - method name only: `get_current_weather`
        - qualified: `WeatherSkill.get_current_weather`
        """
        class_name: Optional[str] = None
        method_name: str = tool_name

        if "." in tool_name:
            parts = tool_name.split(".")
            if len(parts) == 2:
                class_name, method_name = parts[0], parts[1]
            else:
                # If it's more nested than expected, fall back to last segment
                method_name = parts[-1]

        expiry_time = datetime.now(timezone.utc) - timedelta(
            seconds=settings.skill_expiry_seconds
        )

        stmt = (
            select(Skill, Device)
            .join(Device, Skill.device_id == Device.id)
            .where(Device.user_id == self.user_id)
            .where(Skill.function_name == method_name)
            .where(Skill.last_heartbeat > expiry_time)
        )
        if class_name:
            stmt = stmt.where(Skill.class_name == class_name)

        result = await self.db.execute(stmt)
        matches = result.all()

        if not matches:
            if class_name:
                return {"error": f"Unknown tool: {tool_name}"}
            return {
                "error": (
                    f"Unknown tool: {tool_name}. "
                    "If you intended to call a skill, use"
                    " python_exec with"
                    " devices.<device>.<Skill>.<method>(...)."
                )
            }

        if len(matches) > 1:
            # Sort matches: connected devices first
            connected_device_ids = set()
            if self.connection_manager:
                connected_device_ids = set(
                    self.connection_manager.get_connected_devices()
                )

            def _sort_matches(match):
                skill, device = match
                return (
                    device.id not in connected_device_ids,
                    normalize_device_name(device.name),
                )

            matches.sort(key=_sort_matches)

        # Pick the top match (which is now the most preferred connected device)
        skill, device = matches[0]

        # Route to the owning device. The DevicesProxy expects a normalized device name.
        device_name = normalize_device_name(device.name)
        logger.info(
            "[Hub Dynamic Skill] Routing tool '%s' -> devices.%s.%s.%s(kwargs=%s)",
            tool_name,
            device_name,
            skill.class_name,
            skill.function_name,
            arguments,
        )

        try:
            call_result = await self.devices.execute_skill(
                device_name=device_name,
                skill_name=skill.class_name,
                method_name=skill.function_name,
                args=[],
                kwargs=arguments or {},
            )
            return {"result": call_result}
        except Exception as e:
            logger.error(
                "[Hub Dynamic Skill] Failed executing %s on %s: %s",
                tool_name,
                device_name,
                e,
            )
            return {"error": f"{type(e).__name__}: {e}"}

    async def _execute_python(self, code: str) -> Dict[str, Any]:
        """Execute Python code with access to devices proxy using asteval.

        This uses asteval.Interpreter for safe execution with support for
        loops, conditionals, and function calls. Async skill calls are
        wrapped in sync proxies.

        Args:
            code: Python code to execute

        Returns:
            Dict with "result" or "error" key
        """
        from .asteval_executor import execute_with_asteval

        return await execute_with_asteval(code, self.devices)

    async def get_system_prompt(self, requesting_device_key: str) -> str:
        """Get the system prompt for online mode.

        Uses the custom system prompt from settings if configured,
        otherwise falls back to DEFAULT_ONLINE_MODE_PROMPT.

        The prompt includes the set of valid ``devices.<device>`` keys
        so the model does not invent device names.
        """
        devices = await self.devices._get_user_devices()

        # The hub itself is a control plane and should not be used as a target
        # device for spoke-originated runs.
        filtered_device_keys: list[str] = []
        for key in sorted(devices.keys()):
            if key == "strawberry_hub" and requesting_device_key != "strawberry_hub":
                continue
            filtered_device_keys.append(key)

        device_keys = ", ".join(filtered_device_keys)

        # Use custom prompt from settings if provided, else default.
        base_prompt = (
            settings.system_prompt.strip()
            if settings.system_prompt and settings.system_prompt.strip()
            else DEFAULT_ONLINE_MODE_PROMPT
        )

        return (
            f"{base_prompt}\n\n"
            "VALID DEVICE KEYS (use exactly these after 'devices.'):\n"
            f"{device_keys or '(none)'}\n\n"
            "IMPORTANT:\n"
            "- Never invent device names. Always pick a device from "
            "search_skills() results or from the list above.\n"
        )
