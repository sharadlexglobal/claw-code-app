"""Agent loop — the nervous system of Claw Code.

Uses prompt-based tool calling for maximum compatibility with any
OpenAI-compatible provider (including Orbit).

Flow: User message → Claude thinks → outputs <tool_call> → we parse & execute → feed result → loop
"""

from __future__ import annotations

import json
import os
import re
import uuid
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional

from openai import OpenAI

from .tools import TOOL_SCHEMAS, execute_tool, WORKSPACE_ROOT

# ── Config ───────────────────────────────────────────────────────────────────

ORBIT_BASE_URL = os.environ.get("ORBIT_BASE_URL", "https://api.orbit-provider.com/v1")
ORBIT_API_KEY = os.environ.get("ORBIT_API_KEY", "")
DEFAULT_MODEL = os.environ.get("ORBIT_MODEL", "claude-sonnet-4-6")
MAX_ITERATIONS = int(os.environ.get("CLAW_MAX_ITERATIONS", "25"))
MAX_TOKENS = int(os.environ.get("CLAW_MAX_TOKENS", "8192"))

AGENT_SYSTEM_PROMPT = """You are Claw Code, an autonomous AI coding agent. You EXECUTE tasks by calling tools.

CRITICAL: You MUST use <tool_call> XML tags to call tools. This is NOT optional. Without these tags, NOTHING happens.

# Tool Call Format (MANDATORY)

<tool_call>{{"name": "TOOL_NAME", "arguments": {{"key": "value"}}}}</tool_call>

# Available Tools

- write_file: {{"name":"write_file","arguments":{{"file_path":"path","content":"file content"}}}}
- read_file: {{"name":"read_file","arguments":{{"file_path":"path"}}}}
- edit_file: {{"name":"edit_file","arguments":{{"file_path":"path","old_string":"old","new_string":"new"}}}}
- bash: {{"name":"bash","arguments":{{"command":"shell command here"}}}}
- list_directory: {{"name":"list_directory","arguments":{{"directory":"."}}}}
- search_files: {{"name":"search_files","arguments":{{"pattern":"regex","directory":"."}}}}

# Rules
1. EVERY action MUST be a <tool_call> block. Text alone does NOTHING.
2. Use multiple <tool_call> blocks in one response.
3. After writing code, ALWAYS run it with bash to verify.
4. If something fails, fix it and retry.
5. Install dependencies via bash (pip install, npm install, etc.)
6. Write complete, production-quality code.

# Workspace: {workspace_root}

# Example

User: Create and run a hello world Python script

Response:
I'll create hello.py and run it.

<tool_call>{{"name": "write_file", "arguments": {{"file_path": "hello.py", "content": "print('Hello World!')\\n"}}}}</tool_call>

<tool_call>{{"name": "bash", "arguments": {{"command": "python3 hello.py"}}}}</tool_call>
"""

# ── Parse Tool Calls from Text ───────────────────────────────────────────────

TOOL_CALL_PATTERN = re.compile(
    r'<tool_call>\s*(\{.*?\})\s*</tool_call>',
    re.DOTALL
)

TOOL_NAMES = {"read_file", "write_file", "edit_file", "bash", "list_directory", "search_files"}


def _extract_json_objects(text: str) -> list[dict]:
    """Extract all valid JSON objects from text using brace matching."""
    objects = []
    i = 0
    while i < len(text):
        if text[i] == '{':
            depth = 0
            start = i
            for j in range(i, len(text)):
                if text[j] == '{':
                    depth += 1
                elif text[j] == '}':
                    depth -= 1
                    if depth == 0:
                        raw = text[start:j + 1]
                        try:
                            parsed = json.loads(raw)
                            if isinstance(parsed, dict):
                                objects.append(parsed)
                        except json.JSONDecodeError:
                            pass
                        i = j + 1
                        break
            else:
                i += 1
        else:
            i += 1
    return objects


def parse_tool_calls(text: str) -> list[dict]:
    """Extract tool calls from the assistant's response text.

    Tries multiple strategies:
    1. <tool_call> XML tags (ideal)
    2. Any JSON object with "name" matching a known tool
    """
    calls = []

    # Strategy 1: <tool_call> XML tags
    for match in TOOL_CALL_PATTERN.finditer(text):
        try:
            parsed = json.loads(match.group(1))
            if isinstance(parsed, dict) and parsed.get("name") in TOOL_NAMES:
                calls.append({
                    "name": parsed["name"],
                    "arguments": parsed.get("arguments", {}),
                })
        except json.JSONDecodeError:
            continue

    if calls:
        return calls

    # Strategy 2: Find any JSON object that looks like a tool call
    for obj in _extract_json_objects(text):
        name = obj.get("name", "")
        if name in TOOL_NAMES:
            arguments = obj.get("arguments", {})
            if not arguments:
                arguments = {k: v for k, v in obj.items() if k != "name"}
            calls.append({"name": name, "arguments": arguments})

    return calls


def strip_tool_calls(text: str) -> str:
    """Remove tool_call blocks from text to get the prose."""
    return TOOL_CALL_PATTERN.sub('', text).strip()


# ── Data Structures ──────────────────────────────────────────────────────────

@dataclass
class ToolCallRecord:
    name: str
    arguments: dict
    result: dict


@dataclass
class AgentTurn:
    role: str
    content: Optional[str] = None
    tool_calls: List[ToolCallRecord] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)


@dataclass
class AgentSession:
    session_id: str
    messages: List[dict] = field(default_factory=list)
    turns: List[AgentTurn] = field(default_factory=list)
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_iterations: int = 0
    workspace: str = ""

    def __post_init__(self):
        if not self.workspace:
            self.workspace = str(WORKSPACE_ROOT / self.session_id)
            os.makedirs(self.workspace, exist_ok=True)


# ── Session Store ────────────────────────────────────────────────────────────

_sessions: Dict[str, AgentSession] = {}


def get_or_create_session(session_id: Optional[str] = None) -> AgentSession:
    sid = session_id or str(uuid.uuid4())
    if sid not in _sessions:
        _sessions[sid] = AgentSession(session_id=sid)
    return _sessions[sid]


def get_session(session_id: str) -> Optional[AgentSession]:
    return _sessions.get(session_id)


def list_sessions() -> List[dict]:
    return [
        {
            "session_id": s.session_id,
            "turns": len(s.turns),
            "iterations": s.total_iterations,
            "tokens": s.total_input_tokens + s.total_output_tokens,
        }
        for s in _sessions.values()
    ]


def delete_session(session_id: str) -> bool:
    return _sessions.pop(session_id, None) is not None


# ── Agent Loop ───────────────────────────────────────────────────────────────

def _get_client() -> OpenAI:
    if not ORBIT_API_KEY:
        raise RuntimeError("ORBIT_API_KEY not configured")
    return OpenAI(base_url=ORBIT_BASE_URL, api_key=ORBIT_API_KEY)


def run_agent(
    session_id: Optional[str],
    user_message: str,
    model: Optional[str] = None,
    max_iterations: Optional[int] = None,
) -> dict:
    """Run the agent loop. Parses tool_call blocks from the model's response."""

    client = _get_client()
    session = get_or_create_session(session_id)
    model = model or DEFAULT_MODEL
    max_iter = max_iterations or MAX_ITERATIONS

    workspace_path = session.workspace
    os.makedirs(workspace_path, exist_ok=True)

    # Override workspace root for tool execution
    import agent.tools as tools_mod
    tools_mod.WORKSPACE_ROOT = Path(workspace_path)

    system_prompt = AGENT_SYSTEM_PROMPT.format(workspace_root=workspace_path)

    # Add user message
    session.messages.append({"role": "user", "content": user_message})
    session.turns.append(AgentTurn(role="user", content=user_message))

    iterations = 0
    all_tool_calls = []
    final_response = ""

    while iterations < max_iter:
        iterations += 1
        session.total_iterations += 1

        # Call the model
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    *session.messages,
                ],
                max_tokens=MAX_TOKENS,
            )
        except Exception as e:
            return {
                "session_id": session.session_id,
                "error": f"API error: {str(e)}",
                "iterations": iterations,
                "tool_calls": all_tool_calls,
            }

        # Track usage
        if response.usage:
            session.total_input_tokens += response.usage.prompt_tokens or 0
            session.total_output_tokens += response.usage.completion_tokens or 0

        assistant_text = response.choices[0].message.content or ""

        # Parse tool calls from the response
        tool_calls = parse_tool_calls(assistant_text)
        prose = strip_tool_calls(assistant_text)

        # Add assistant message to history
        session.messages.append({"role": "assistant", "content": assistant_text})

        if not tool_calls:
            # No tool calls — agent is done
            final_response = prose or assistant_text
            session.turns.append(AgentTurn(role="assistant", content=final_response))
            break

        # Execute each tool call
        turn_records = []
        results_text = []

        for tc in tool_calls:
            result = execute_tool(tc["name"], tc["arguments"])

            record = ToolCallRecord(name=tc["name"], arguments=tc["arguments"], result=result)
            turn_records.append(record)
            all_tool_calls.append({
                "tool": tc["name"],
                "arguments": tc["arguments"],
                "result": result,
            })

            results_text.append(
                f'Tool `{tc["name"]}` result:\n```json\n{json.dumps(result, default=str, indent=2)}\n```'
            )

        session.turns.append(AgentTurn(role="assistant", content=prose, tool_calls=turn_records))

        # Feed results back to the model
        session.messages.append({
            "role": "user",
            "content": "Tool execution results:\n\n" + "\n\n".join(results_text) + "\n\nContinue with the task. If done, provide a final summary WITHOUT any tool_call blocks.",
        })

        final_response = prose

    return {
        "session_id": session.session_id,
        "response": final_response,
        "iterations": iterations,
        "tool_calls": all_tool_calls,
        "usage": {
            "input_tokens": session.total_input_tokens,
            "output_tokens": session.total_output_tokens,
        },
        "workspace": workspace_path,
    }


# ── Streaming Agent Loop ────────────────────────────────────────────────────

def run_agent_stream(
    session_id: Optional[str],
    user_message: str,
    model: Optional[str] = None,
    max_iterations: Optional[int] = None,
) -> Generator[dict, None, None]:
    """Run the agent loop with streaming events."""

    client = _get_client()
    session = get_or_create_session(session_id)
    model = model or DEFAULT_MODEL
    max_iter = max_iterations or MAX_ITERATIONS

    workspace_path = session.workspace
    os.makedirs(workspace_path, exist_ok=True)

    import agent.tools as tools_mod
    tools_mod.WORKSPACE_ROOT = Path(workspace_path)

    system_prompt = AGENT_SYSTEM_PROMPT.format(workspace_root=workspace_path)

    session.messages.append({"role": "user", "content": user_message})

    yield {"event": "session", "session_id": session.session_id, "workspace": workspace_path}

    iterations = 0
    while iterations < max_iter:
        iterations += 1
        session.total_iterations += 1

        yield {"event": "thinking", "iteration": iterations}

        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    *session.messages,
                ],
                max_tokens=MAX_TOKENS,
            )
        except Exception as e:
            yield {"event": "error", "message": str(e)}
            return

        if response.usage:
            session.total_input_tokens += response.usage.prompt_tokens or 0
            session.total_output_tokens += response.usage.completion_tokens or 0

        assistant_text = response.choices[0].message.content or ""
        tool_calls = parse_tool_calls(assistant_text)
        prose = strip_tool_calls(assistant_text)

        session.messages.append({"role": "assistant", "content": assistant_text})

        if prose:
            yield {"event": "text", "content": prose}

        if not tool_calls:
            yield {
                "event": "done",
                "iterations": iterations,
                "usage": {
                    "input_tokens": session.total_input_tokens,
                    "output_tokens": session.total_output_tokens,
                },
            }
            return

        results_text = []
        for tc in tool_calls:
            yield {"event": "tool_call", "tool": tc["name"], "arguments": tc["arguments"]}

            result = execute_tool(tc["name"], tc["arguments"])

            yield {"event": "tool_result", "tool": tc["name"], "result": result}

            results_text.append(
                f'Tool `{tc["name"]}` result:\n```json\n{json.dumps(result, default=str, indent=2)}\n```'
            )

        session.messages.append({
            "role": "user",
            "content": "Tool execution results:\n\n" + "\n\n".join(results_text) + "\n\nContinue with the task. If done, provide a final summary WITHOUT any tool_call blocks.",
        })

    yield {"event": "max_iterations", "iterations": iterations}
