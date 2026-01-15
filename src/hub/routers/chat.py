"""Chat/inference endpoints - OpenAI compatible.

Routes LLM requests through TensorZero embedded gateway with fallback support.
When enable_tools=true, Hub runs the agent loop and executes tools.
When enable_tools=false (default for Spoke pass-through), Hub just returns LLM response.

File Summary:
- ChatCompletionRequest: Request model with enable_tools parameter
- chat_completions: Main endpoint that routes to agent loop or pass-through
- _run_agent_loop: Executes tools and continues conversation until done
- _call_tensorzero: Simple pass-through to LLM (no tool execution)
"""

import json
import logging
import time
import uuid
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import get_current_device
from ..config import settings
from ..database import Device, get_db
from ..tensorzero_gateway import inference as tz_inference

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["chat"])


class ChatMessage(BaseModel):
    """A single chat message."""
    role: Literal["system", "user", "assistant", "tool"]
    content: str
    tool_call_id: Optional[str] = None
    name: Optional[str] = None


class ChatCompletionRequest(BaseModel):
    """OpenAI-compatible chat completion request with tool execution control.
    
    Attributes:
        enable_tools: If True, Hub runs agent loop and executes tools.
                     If False, Hub just passes through to LLM (Spoke handles tools).
    """
    model: str = "gpt-4o-mini"
    messages: List[ChatMessage]
    temperature: Optional[float] = 0.7
    max_tokens: Optional[int] = None
    stream: bool = False
    enable_tools: bool = False


class ChatChoice(BaseModel):
    """A single completion choice."""
    index: int
    message: ChatMessage
    finish_reason: str


class ChatCompletionResponse(BaseModel):
    """OpenAI-compatible chat completion response."""
    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: List[ChatChoice]
    usage: Optional[Dict[str, Any]] = None


@router.post("/v1/chat/completions", response_model=ChatCompletionResponse)
async def chat_completions(
    request: ChatCompletionRequest,
    device: Device = Depends(get_current_device),
    db: AsyncSession = Depends(get_db),
) -> ChatCompletionResponse:
    """OpenAI-compatible chat completions endpoint.
    
    Routes requests through TensorZero embedded gateway with automatic
    fallback between configured providers.
    
    When enable_tools=True, Hub runs the agent loop and executes tools.
    When enable_tools=False (default), Hub just passes through to LLM.
    """
    if request.enable_tools:
        return await _run_agent_loop(request, device, db)
    return await _call_tensorzero(request, use_tools=False)


async def _run_agent_loop(
    request: ChatCompletionRequest,
    device: Device,
    db: AsyncSession,
) -> ChatCompletionResponse:
    """Run agent loop with tool execution.
    
    This is used when enable_tools=True (Hub executes tools).
    """
    from .websocket import connection_manager
    from ..skill_service import HubSkillService
    
    # Create skill service for this user
    skill_service = HubSkillService(
        db=db,
        user_id=device.user_id,
        connection_manager=connection_manager,
    )
    
    # Build messages for TensorZero
    messages: List[Dict[str, Any]] = []
    
    # Add system prompt for online mode
    system_prompt = skill_service.get_system_prompt()
    logger.info(f"[Hub Agent] System prompt length: {len(system_prompt)}")
    logger.debug(f"[Hub Agent] System prompt preview: {system_prompt[:300]}")
    messages.append({"role": "user", "content": system_prompt})
    
    # Add conversation messages
    for m in request.messages:
        if m.role in ("user", "assistant"):
            messages.append({"role": m.role, "content": m.content})
        elif m.role == "system":
            messages.append({"role": "user", "content": m.content})
        elif m.role == "tool":
            prefix_parts = ["[Tool Result]"]
            if m.name:
                prefix_parts.append(f"name={m.name}")
            prefix = " ".join(prefix_parts)
            messages.append({"role": "user", "content": f"{prefix}\n{m.content}"})
    
    final_content = ""
    model_used = "unknown"

    # Deduplicate tool calls across iterations within a single request.
    # Models sometimes "double check" by repeating the same tool call with the
    # same arguments. We treat identical calls as idempotent and reuse the
    # cached result instead of executing again.
    tool_result_cache: dict[str, dict[str, Any]] = {}
    had_iteration_with_no_new_tool_exec = False
    
    # Agent loop
    max_iterations = settings.agent_max_iterations
    for iteration in range(max_iterations):
        logger.info(f"[Hub Agent] Iteration {iteration + 1}/{max_iterations}")
        logger.info(f"[Hub Agent] Messages count: {len(messages)}")
        logger.debug(f"[Hub Agent] First message: {messages[0] if messages else 'none'}")
        
        try:
            # Call TensorZero with tools
            response = await tz_inference(
                messages=messages,
                function_name="chat",  # Uses the function with tools defined
            )
            logger.info(f"[Hub Agent] Got response with content blocks: {len(response.content) if hasattr(response, 'content') else 0}")
        except Exception as e:
            logger.error(f"[Hub Agent] LLM inference failed: {e}")
            raise HTTPException(
                status_code=502,
                detail=f"LLM inference failed: {e}",
            )
        
        # Extract content and tool calls
        content = ""
        tool_calls = []
        
        if hasattr(response, "content"):
            logger.info(f"[Hub Agent] Response has {len(response.content)} content blocks")
            for i, block in enumerate(response.content):
                logger.info(f"[Hub Agent] Block {i}: type={getattr(block, 'type', 'unknown')}, hasattr text={hasattr(block, 'text')}")
                if hasattr(block, "text"):
                    content += block.text
                elif hasattr(block, "type") and block.type == "tool_call":
                    name = getattr(block, "name", None) or getattr(block, "raw_name", None)
                    arguments = getattr(block, "arguments", None)
                    logger.info(f"[Hub Agent] Tool call found: {name}, args type: {type(arguments)}")
                    if not isinstance(arguments, dict):
                        raw_args = getattr(block, "raw_arguments", None)
                        if raw_args and isinstance(raw_args, str):
                            try:
                                arguments = json.loads(raw_args)
                            except json.JSONDecodeError:
                                arguments = {}
                        else:
                            arguments = {}
                    
                    if name:
                        tool_calls.append({
                            "id": str(getattr(block, "id", "") or ""),
                            "name": name,
                            "arguments": arguments,
                        })
                        logger.info(f"[Hub Agent] Added tool call: {name}({arguments})")
        
        model_used = getattr(response, "variant_name", "unknown")
        
        # If no tool calls, we're done
        if not tool_calls:
            final_content = content
            logger.info(f"[Hub Agent] No tool calls, ending loop. Content: {content[:200] if content else '(empty)'}")
            break
        
        logger.info(f"[Hub Agent] Executing {len(tool_calls)} tool calls: {[tc['name'] for tc in tool_calls]}")
        
        # Execute tool calls
        tool_results = []
        tool_summaries = []  # Keep summary for final response
        had_new_tool_exec = False
        for tc in tool_calls:
            cache_key = f"{tc['name']}:{json.dumps(tc['arguments'] or {}, sort_keys=True, default=str)}"

            if cache_key in tool_result_cache:
                result = tool_result_cache[cache_key]
                logger.info(
                    f"[Hub Agent] Reusing cached result for tool: {tc['name']} args: {tc['arguments']}"
                )
            else:
                logger.info(
                    f"[Hub Agent] Executing tool: {tc['name']} with args: {tc['arguments']}"
                )
                result = await skill_service.execute_tool(tc["name"], tc["arguments"])
                tool_result_cache[cache_key] = result
                had_new_tool_exec = True
            logger.info(f"[Hub Agent] Tool result: {result}")
            
            if "result" in result:
                result_str = str(result['result'])
                tool_results.append(f"Tool {tc['name']}: {result_str}")
                tool_summaries.append(f"**{tc['name']}({', '.join(f'{k}={v}' for k, v in tc['arguments'].items())})**\n```\n{result_str}\n```")
            else:
                error_msg = result.get('error', 'Unknown error')
                logger.warning(f"[Hub Agent] Tool {tc['name']} failed: {error_msg}")
                tool_results.append(f"Tool {tc['name']} error: {error_msg}")
                tool_summaries.append(f"**{tc['name']}** - Error: {error_msg}")
        
        # Add assistant response and tool results to messages
        messages.append({"role": "assistant", "content": content})
        tool_output = "\n".join(tool_results)
        logger.info(f"[Hub Agent] Tool output summary: {tool_output[:500]}")

        if not had_new_tool_exec:
            # Model repeated identical calls. Strongly steer it to stop looping.
            if had_iteration_with_no_new_tool_exec:
                # Second consecutive iteration with no new tool execution:
                # break early to avoid burning iterations.
                logger.warning(
                    "[Hub Agent] No new tool execution for two consecutive iterations; stopping agent loop."
                )
                final_content = (
                    content
                    or "I already executed the requested tools and got results. See tool log above."
                )
                break

            had_iteration_with_no_new_tool_exec = True
            tool_output = (
                f"{tool_output}\n\n"
                "[Note] The tool call(s) above were already executed with identical arguments. "
                "Do NOT repeat the same tool call again. If you need more information, "
                "call a different tool or change the arguments. Otherwise, respond now."
            )
        else:
            had_iteration_with_no_new_tool_exec = False
        messages.append({
            "role": "user",
            "content": f"[Tool Results]\n{tool_output}\n\n[Now respond naturally to the user based on these results.]"
        })
        
        # Keep tool summaries for final output
        if not hasattr(skill_service, '_tool_execution_log'):
            skill_service._tool_execution_log = []
        skill_service._tool_execution_log.extend(tool_summaries)
        
        final_content = content
    
    # If we executed tools, append execution log to the final content so user can see what happened
    if iteration > 0 and hasattr(skill_service, '_tool_execution_log') and skill_service._tool_execution_log:
        tool_log = "\n\n".join(skill_service._tool_execution_log)
        final_content = f"{final_content}\n\n---\n### Tool Execution Log\n\n{tool_log}"
    
    return ChatCompletionResponse(
        id=f"chatcmpl-{uuid.uuid4().hex[:8]}",
        created=int(time.time()),
        model=model_used,
        choices=[
            ChatChoice(
                index=0,
                message=ChatMessage(role="assistant", content=final_content),
                finish_reason="stop",
            )
        ],
        usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    )


async def _call_tensorzero(
    request: ChatCompletionRequest,
    use_tools: bool = False,
) -> ChatCompletionResponse:
    """Route request through TensorZero embedded gateway.
    
    TensorZero handles provider selection and fallback automatically.
    
    Args:
        request: The chat completion request
        use_tools: If False, uses chat_no_tools function (Spoke handles tools)
    """
    # Convert messages to TensorZero format.
    # Hub's embedded TensorZero function input expects message roles to be
    # compatible with its internal schema (commonly user/assistant). TensorZero
    # tool-calling flows can introduce roles like `system` and `tool`, so we
    # normalize those into `user` messages while preserving order.
    messages: list[dict[str, Any]] = []
    for m in request.messages:
        if m.role in ("user", "assistant"):
            messages.append({"role": m.role, "content": m.content})
            continue

        if m.role == "system":
            # Preserve system prompt content but avoid `system` role.
            messages.append({"role": "user", "content": m.content})
            continue

        if m.role == "tool":
            # OpenAI tool-result messages include `tool_call_id` and sometimes `name`.
            # Preserve the information in-band so the model can continue.
            prefix_parts = ["[Tool Result]"]
            if m.name:
                prefix_parts.append(f"name={m.name}")
            if m.tool_call_id:
                prefix_parts.append(f"tool_call_id={m.tool_call_id}")
            prefix = " ".join(prefix_parts)
            messages.append({"role": "user", "content": f"{prefix}\n{m.content}"})
            continue
    
    # Choose function based on whether tools are enabled
    function_name = "chat" if use_tools else "chat_no_tools"
    
    try:
        response = await tz_inference(
            messages=messages,
            function_name=function_name,
        )
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=f"LLM inference failed: {e}",
        )
    
    # Extract content from TensorZero response
    content = _extract_content(response)
    model_used = _extract_model(response)
    
    return ChatCompletionResponse(
        id=f"chatcmpl-{uuid.uuid4().hex[:8]}",
        created=int(time.time()),
        model=model_used,
        choices=[
            ChatChoice(
                index=0,
                message=ChatMessage(role="assistant", content=content),
                finish_reason="stop",
            )
        ],
        usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    )


def _extract_content(response: Any) -> str:
    """Extract text content from TensorZero inference response."""
    # TensorZero returns response with content attribute
    if hasattr(response, "content"):
        # Content is a list of ContentBlock objects
        content_blocks = response.content
        if content_blocks:
            # Get text from first block
            block = content_blocks[0]
            if hasattr(block, "text"):
                return block.text
    
    # Fallback: try dict access
    if isinstance(response, dict):
        content = response.get("content", [])
        if content and isinstance(content[0], dict):
            return content[0].get("text", "")
    
    return str(response)


def _extract_model(response: Any) -> str:
    """Extract model name from TensorZero inference response."""
    if hasattr(response, "variant_name"):
        return response.variant_name
    if isinstance(response, dict):
        return response.get("variant_name", "unknown")
    return "unknown"


# Also expose as /inference for TensorZero compatibility
@router.post("/inference")
async def inference(
    request: ChatCompletionRequest,
    device: Device = Depends(get_current_device),
) -> ChatCompletionResponse:
    """TensorZero-style inference endpoint."""
    return await chat_completions(request, device)

