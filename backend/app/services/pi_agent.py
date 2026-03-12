"""
Lightweight tool-calling agent using OpenAI SDK streaming.

Provides a streaming chat interface that can detect and execute tool calls,
then loop back to the LLM with results. Yields SSE-compatible event dicts.
"""

import json
import logging
import uuid
from typing import Any, AsyncGenerator, Callable, Awaitable

import openai

logger = logging.getLogger("studio.pi_agent")

MAX_ITERATIONS = 3


class PiAgent:
    """Lightweight tool-calling agent using OpenAI SDK streaming."""

    def __init__(self, api_key: str, base_url: str, model: str):
        self._client = openai.AsyncOpenAI(api_key=api_key, base_url=base_url)
        self._model = model
        # Registered tools: name -> {definition, handler}
        self._tools: dict[str, dict[str, Any]] = {}

    def register_tool(
        self,
        name: str,
        description: str,
        parameters: dict,
        handler: Callable[..., Awaitable[Any]],
    ):
        """Register a tool with OpenAI function format and an async handler."""
        self._tools[name] = {
            "definition": {
                "type": "function",
                "function": {
                    "name": name,
                    "description": description,
                    "parameters": parameters,
                },
            },
            "handler": handler,
        }

    async def chat(
        self,
        messages: list[dict],
        system_prompt: str | None = None,
    ) -> AsyncGenerator[dict, None]:
        """
        Main loop: stream LLM response, detect tool_calls, execute tools, loop.

        Yields SSE event dicts with keys ``event`` and ``data``.
        """
        try:
            # Build the full message list with optional system prompt
            full_messages: list[dict] = []
            if system_prompt:
                full_messages.append({"role": "system", "content": system_prompt})
            full_messages.extend(messages)

            # Collect references across all iterations
            all_references: dict[str, list[str]] = {"nodes": [], "edges": []}

            yield {"event": "start", "data": {"role": "assistant"}}

            for iteration in range(MAX_ITERATIONS):
                # Build tool definitions list
                tools_defs = [t["definition"] for t in self._tools.values()] or None

                # Stream from LLM
                stream = await self._client.chat.completions.create(
                    model=self._model,
                    messages=full_messages,
                    tools=tools_defs,
                    stream=True,
                )

                # Accumulators for this streaming pass
                content_parts: list[str] = []
                # Index-based tool call accumulation:
                # {index: {"id": str, "name": str, "arguments": str}}
                tool_calls_buf: dict[int, dict[str, str]] = {}

                async for chunk in stream:
                    if not chunk.choices:
                        continue

                    delta = chunk.choices[0].delta

                    # --- Text content ---
                    if delta.content:
                        content_parts.append(delta.content)
                        yield {
                            "event": "text_chunk",
                            "data": {"text": delta.content},
                        }

                    # --- Tool calls (index-based accumulation) ---
                    if delta.tool_calls:
                        for tc_delta in delta.tool_calls:
                            idx = tc_delta.index
                            if idx not in tool_calls_buf:
                                tool_calls_buf[idx] = {
                                    "id": "",
                                    "name": "",
                                    "arguments": "",
                                }
                            buf = tool_calls_buf[idx]
                            if tc_delta.id:
                                buf["id"] = tc_delta.id
                            if tc_delta.function:
                                if tc_delta.function.name:
                                    buf["name"] = tc_delta.function.name
                                if tc_delta.function.arguments:
                                    buf["arguments"] += tc_delta.function.arguments

                # If no tool calls were made, we're done
                if not tool_calls_buf:
                    final_content = "".join(content_parts)
                    yield {
                        "event": "end",
                        "data": {
                            "content": final_content,
                            "references": all_references,
                        },
                    }
                    return

                # --- Execute tool calls ---
                # Append the assistant message with tool_calls to history
                assistant_tool_calls = []
                for idx in sorted(tool_calls_buf.keys()):
                    tc = tool_calls_buf[idx]
                    # Ensure each tool call has an id
                    if not tc["id"]:
                        tc["id"] = f"call_{uuid.uuid4().hex[:24]}"
                    assistant_tool_calls.append(
                        {
                            "id": tc["id"],
                            "type": "function",
                            "function": {
                                "name": tc["name"],
                                "arguments": tc["arguments"],
                            },
                        }
                    )

                assistant_msg: dict[str, Any] = {
                    "role": "assistant",
                    "tool_calls": assistant_tool_calls,
                }
                if content_parts:
                    assistant_msg["content"] = "".join(content_parts)
                full_messages.append(assistant_msg)

                # Execute each tool call and build tool result messages
                for tc in assistant_tool_calls:
                    tool_name = tc["function"]["name"]
                    tool_call_id = tc["id"]
                    raw_args = tc["function"]["arguments"]

                    yield {
                        "event": "tool_call",
                        "data": {
                            "id": tool_call_id,
                            "name": tool_name,
                            "arguments": raw_args,
                        },
                    }

                    # Parse arguments
                    try:
                        parsed_args = json.loads(raw_args) if raw_args else {}
                    except json.JSONDecodeError:
                        parsed_args = {}

                    # Execute handler
                    tool_entry = self._tools.get(tool_name)
                    if tool_entry is None:
                        result = {"error": f"Unknown tool: {tool_name}"}
                    else:
                        try:
                            result = await tool_entry["handler"](**parsed_args)
                        except Exception as exc:
                            logger.exception(
                                "Tool %s raised an error", tool_name
                            )
                            result = {"error": str(exc)}

                    # Ensure result is a dict for consistency
                    if not isinstance(result, dict):
                        result = {"result": result}

                    # Collect references from tool results
                    if "references" in result:
                        refs = result["references"]
                        if isinstance(refs, dict):
                            for node_id in refs.get("nodes", []):
                                if node_id not in all_references["nodes"]:
                                    all_references["nodes"].append(node_id)
                            for edge_id in refs.get("edges", []):
                                if edge_id not in all_references["edges"]:
                                    all_references["edges"].append(edge_id)

                    yield {
                        "event": "tool_result",
                        "data": {
                            "id": tool_call_id,
                            "result": result,
                        },
                    }

                    # Inject tool result into message history
                    full_messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_call_id,
                            "content": json.dumps(result, default=str),
                        }
                    )

                # Reset content for next iteration (LLM will generate new text)
                content_parts = []
                logger.debug(
                    "Tool iteration %d/%d complete, continuing...",
                    iteration + 1,
                    MAX_ITERATIONS,
                )

            # If we exhausted all iterations, close out gracefully
            yield {
                "event": "end",
                "data": {
                    "content": "".join(content_parts),
                    "references": all_references,
                },
            }

        except Exception as exc:
            logger.exception("PiAgent.chat failed")
            yield {
                "event": "error",
                "data": {"message": str(exc)},
            }
