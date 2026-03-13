"""
pi-mono RPC-backed agent runtime.

Bridges the Python FastAPI backend to ``@mariozechner/pi-coding-agent`` running
in RPC mode. Custom memory tools are registered via a local TypeScript
extension, so the LLM can still call ``memory_search`` and ``memory_capture``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any, AsyncGenerator

from ..config import Config

logger = logging.getLogger("studio.pi_rpc_agent")


class PiRpcAgent:
    """RPC-backed agent compatible with the local ``PiAgent`` interface."""

    def __init__(
        self,
        *,
        project_id: str,
        thread_id: str,
        provider: str,
        model: str,
        api_key: str,
    ) -> None:
        self._project_id = project_id
        self._thread_id = thread_id
        self._provider = provider
        self._model = model
        self._api_key = api_key

    async def chat(
        self,
        messages: list[dict],
        system_prompt: str | None = None,
    ) -> AsyncGenerator[dict, None]:
        """Run a single prompt against pi-coding-agent RPC mode."""
        if not self._api_key:
            yield {
                "event": "error",
                "data": {"message": "Pi RPC API key is not configured."},
            }
            return

        session_file = self._session_file()
        session_file.parent.mkdir(parents=True, exist_ok=True)

        prompt_message = self._build_prompt_message(messages, session_file.exists())
        command = [
            *Config.pi_agent_cli_args(),
            "--mode",
            "rpc",
            "--provider",
            self._provider,
            "--model",
            self._model,
            "--no-tools",
            "--session",
            str(session_file),
            "--extension",
            Config.PI_EXTENSION_PATH,
        ]
        if system_prompt:
            command.extend(["--system-prompt", system_prompt])

        env = os.environ.copy()
        env.update(self._provider_env())
        env["GRAPHITI_STUDIO_BACKEND_URL"] = f"http://127.0.0.1:{Config.STUDIO_PORT}"
        env["GRAPHITI_STUDIO_PROJECT_ID"] = self._project_id

        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
                cwd=str(Path(__file__).resolve().parents[3]),
            )
        except FileNotFoundError as exc:
            yield {
                "event": "error",
                "data": {"message": f"Failed to launch pi-coding-agent: {exc}"},
            }
            return

        stderr_task = asyncio.create_task(self._drain_stderr(process))
        final_content = ""
        references = {"nodes": [], "edges": []}
        yielded_start = False
        ended = False

        try:
            assert process.stdin is not None
            process.stdin.write(
                (json.dumps({"type": "prompt", "message": prompt_message}, ensure_ascii=False) + "\n").encode("utf-8")
            )
            await process.stdin.drain()

            assert process.stdout is not None
            async for raw_line in process.stdout:
                line = raw_line.decode("utf-8", errors="replace").rstrip("\n")
                if line.endswith("\r"):
                    line = line[:-1]
                if not line:
                    continue

                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    logger.debug("Ignoring non-JSON RPC line: %s", line)
                    continue

                event_type = event.get("type")
                if event_type == "response":
                    if event.get("command") == "prompt" and not event.get("success", False):
                        yield {
                            "event": "error",
                            "data": {"message": event.get("error") or "pi prompt failed"},
                        }
                        return
                    continue

                if event_type == "extension_ui_request":
                    continue

                if not yielded_start:
                    yielded_start = True
                    yield {"event": "start", "data": {"role": "assistant"}}

                if event_type == "message_update":
                    delta = event.get("assistantMessageEvent", {})
                    delta_type = delta.get("type")
                    if delta_type == "text_delta":
                        text = delta.get("delta", "")
                        final_content += text
                        yield {"event": "text_chunk", "data": {"text": text}}
                    elif delta_type == "toolcall_end":
                        tool_call = delta.get("toolCall", {})
                        yield {
                            "event": "tool_call",
                            "data": {
                                "id": tool_call.get("id", ""),
                                "name": tool_call.get("name", ""),
                                "arguments": json.dumps(
                                    tool_call.get("arguments", {}),
                                    ensure_ascii=False,
                                ),
                            },
                        }
                    elif delta_type == "error":
                        yield {
                            "event": "error",
                            "data": {"message": delta.get("error") or "pi runtime error"},
                        }
                        return
                    continue

                if event_type == "tool_execution_end":
                    result = self._normalize_tool_result(event.get("result", {}))
                    refs = result.get("references", {})
                    if isinstance(refs, dict):
                        for node_id in refs.get("nodes", []):
                            if node_id not in references["nodes"]:
                                references["nodes"].append(node_id)
                        for edge_id in refs.get("edges", []):
                            if edge_id not in references["edges"]:
                                references["edges"].append(edge_id)

                    yield {
                        "event": "tool_result",
                        "data": {
                            "id": event.get("toolCallId", ""),
                            "result": result,
                        },
                    }
                    continue

                if event_type == "agent_end":
                    yield {
                        "event": "end",
                        "data": {
                            "content": final_content,
                            "references": references,
                        },
                    }
                    ended = True
                    return

            if not ended:
                yield {
                    "event": "end",
                    "data": {
                        "content": final_content,
                        "references": references,
                    },
                }
        finally:
            if process.returncode is None:
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), timeout=2)
                except asyncio.TimeoutError:
                    process.kill()
                    await process.wait()
            await stderr_task

    def _session_file(self) -> Path:
        return Path(Config.PI_SESSION_DIR) / self._project_id / f"{self._thread_id}.jsonl"

    def _provider_env(self) -> dict[str, str]:
        if self._provider == "kimi-coding":
            return {"KIMI_API_KEY": self._api_key}
        if self._provider == "openai-codex":
            return {"OPENAI_API_KEY": self._api_key}
        return {"PI_API_KEY": self._api_key}

    def _build_prompt_message(self, messages: list[dict], session_exists: bool) -> str:
        if not messages:
            return ""

        latest_message = messages[-1].get("content", "")
        if session_exists or len(messages) == 1:
            return latest_message

        transcript_lines = [
            f"{msg.get('role', 'user').title()}: {msg.get('content', '')}"
            for msg in messages[:-1]
            if msg.get("content")
        ]
        transcript = "\n".join(transcript_lines)
        return (
            "Conversation history so far:\n"
            f"{transcript}\n\n"
            "Continue this conversation naturally. "
            "The latest user message is:\n"
            f"{latest_message}"
        )

    def _normalize_tool_result(self, result: dict[str, Any]) -> dict[str, Any]:
        details = result.get("details")
        if isinstance(details, dict):
            return details

        text_parts: list[str] = []
        for block in result.get("content", []) or []:
            if isinstance(block, dict) and block.get("type") == "text":
                text_parts.append(block.get("text", ""))

        return {
            "content": "\n".join(part for part in text_parts if part).strip(),
            "references": {"nodes": [], "edges": []},
        }

    async def _drain_stderr(self, process: asyncio.subprocess.Process) -> None:
        if process.stderr is None:
            return
        async for raw_line in process.stderr:
            line = raw_line.decode("utf-8", errors="replace").rstrip()
            if line:
                logger.debug("pi-rpc stderr: %s", line)
