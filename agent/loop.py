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

AGENT_SYSTEM_PROMPT = """You are Claw Code — an autonomous AI coding agent running on a server.
You have access to a workspace directory where you can create, read, edit files and run bash commands.

## Available Tools

To use a tool, output a tool_call block in this EXACT format:

<tool_call>
{{"name": "tool_name", "arguments": {{"param1": "value1", "param2": "value2"}}}}
</tool_call>

### Tools:

1. **read_file** - Read a file from the workspace
   - Arguments: file_path (required), offset (optional, default 0), limit (optional, default 2000)

2. **write_file** - Create or overwrite a file
   - Arguments: file_path (required), content (required)

3. **edit_file** - Replace text in an existing file
   - Arguments: file_path (required), old_string (required), new_string (required)

4. **list_directory** - List files in a directory
   - Arguments: directory (optional, default ".")

5. **search_files** - Search for a regex pattern in files
   - Arguments: pattern (required), directory (optional), file_glob (optional)

6. **bash** - Execute a shell command
   - Arguments: command (required), timeout (optional, default 30)

## Rules
1. ALWAYS use tool_call blocks to accomplish tasks — don't just describe what you'd do
2. You can use MULTIPLE tool_call blocks in a single response
3. Create complete, working code — not snippets or placeholders
4. After writing code, RUN it to verify it works using bash
5. If a command fails, read the error, fix it, and retry
6. Install dependencies as needed via bash (pip install, npm install, etc.)
7. Organize projects with proper structure
8. When building apps, include ALL necessary files

## Workspace
Your workspace root is: {workspace_root}
All file paths are relative to this directory.

## Example

User: Create a Python script that prints fibonacci numbers

Your response:
I'll create a fibonacci script and run it.

<tool_call>
{{"name": "write_file", "arguments": {{"file_path": "fibonacci.py", "content": "def fibonacci(n):\\n    a, b = 0, 1\\n    for _ in range(n):\\n        print(a, end=' ')\\n        a, b = b, a + b\\n    print()\\n\\nfibonacci(10)\\n"}}}}
</tool_call>

Now let me run it:

<tool_call>
{{"name": "bash", "arguments": {{"command": "python3 fibonacci.py"}}}}
</tool_call>
"""

# ── Parse Tool Calls from Text ───────────────────────────────────────────────

TOOL_CALL_PATTERN = re.compile(
    r'<tool_call>\s*(\{.*?\})\s*</tool_call>',
    re.DOTALL
)


def parse_tool_calls(text: str) -> list[dict]:
    """Extract tool_call blocks from the assistant's response text."""
    calls = []
    for match in TOOL_CALL_PATTERN.finditer(text):
        try:
            parsed = json.loads(match.group(1))
            if "name" in parsed:
                calls.append({
                    "name": parsed["name"],
                    "arguments": parsed.get("arguments", {}),
                })
        except json.JSONDecodeError:
            continue
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
