"""Agent loop — the nervous system of Claw Code.

This implements the core agent loop:
  User message → Claude thinks → Tool call → Execute → Result → Loop
  until Claude decides no more tools are needed.
"""

from __future__ import annotations

import json
import os
import uuid
import time
from dataclasses import dataclass, field
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

## Your Capabilities
- **read_file**: Read any file in the workspace
- **write_file**: Create or overwrite files
- **edit_file**: Make targeted edits to existing files
- **list_directory**: Browse the workspace
- **search_files**: Search for patterns in code
- **bash**: Run any shell command (install packages, run code, git, build, test, etc.)

## Rules
1. ALWAYS use tools to accomplish tasks — don't just describe what you'd do
2. Create complete, working code — not snippets or placeholders
3. After writing code, RUN it to verify it works
4. If a command fails, read the error, fix it, and retry
5. Install dependencies as needed via bash (pip, npm, cargo, etc.)
6. Organize projects with proper structure (directories, config files, etc.)
7. When building apps, include ALL necessary files (package.json, requirements.txt, etc.)
8. Test your work before saying you're done

## Workspace
Your workspace is at: {workspace_root}
All file paths are relative to this directory.
"""


# ── Data Structures ──────────────────────────────────────────────────────────

@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict
    result: Optional[dict] = None


@dataclass
class AgentTurn:
    role: str  # 'user', 'assistant', 'tool'
    content: Optional[str] = None
    tool_calls: List[ToolCall] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)


@dataclass
class AgentSession:
    session_id: str
    messages: List[dict] = field(default_factory=list)  # OpenAI-format messages
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
    """Run the agent loop synchronously. Returns the final result."""

    client = _get_client()
    session = get_or_create_session(session_id)
    model = model or DEFAULT_MODEL
    max_iter = max_iterations or MAX_ITERATIONS

    # Set workspace env for this session
    workspace_path = session.workspace
    os.makedirs(workspace_path, exist_ok=True)

    # Override workspace root for tool execution
    import agent.tools as tools_mod
    tools_mod.WORKSPACE_ROOT = __import__("pathlib").Path(workspace_path)

    # Build system prompt
    system_prompt = AGENT_SYSTEM_PROMPT.format(workspace_root=workspace_path)

    # Add user message
    session.messages.append({"role": "user", "content": user_message})
    session.turns.append(AgentTurn(role="user", content=user_message))

    iterations = 0
    all_tool_calls = []

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
                tools=TOOL_SCHEMAS,
                tool_choice="auto",
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

        choice = response.choices[0]
        assistant_msg = choice.message

        # Build assistant message for history
        msg_dict = {"role": "assistant", "content": assistant_msg.content or ""}
        if assistant_msg.tool_calls:
            msg_dict["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in assistant_msg.tool_calls
            ]
        session.messages.append(msg_dict)

        # If no tool calls, we're done
        if not assistant_msg.tool_calls:
            session.turns.append(AgentTurn(role="assistant", content=assistant_msg.content))
            return {
                "session_id": session.session_id,
                "response": assistant_msg.content or "",
                "iterations": iterations,
                "tool_calls": all_tool_calls,
                "usage": {
                    "input_tokens": session.total_input_tokens,
                    "output_tokens": session.total_output_tokens,
                },
                "workspace": workspace_path,
            }

        # Execute each tool call
        turn_tool_calls = []
        for tc in assistant_msg.tool_calls:
            try:
                args = json.loads(tc.function.arguments)
            except json.JSONDecodeError:
                args = {}

            # Execute the tool
            result = execute_tool(tc.function.name, args)

            tool_call_record = {
                "id": tc.id,
                "tool": tc.function.name,
                "arguments": args,
                "result": result,
            }
            all_tool_calls.append(tool_call_record)
            turn_tool_calls.append(ToolCall(
                id=tc.id, name=tc.function.name,
                arguments=args, result=result,
            ))

            # Add tool result to messages
            session.messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": json.dumps(result, default=str),
            })

        session.turns.append(AgentTurn(
            role="assistant",
            content=assistant_msg.content,
            tool_calls=turn_tool_calls,
        ))

    # Hit max iterations
    return {
        "session_id": session.session_id,
        "response": "Reached maximum iterations. The task may be incomplete.",
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
    tools_mod.WORKSPACE_ROOT = __import__("pathlib").Path(workspace_path)

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
                tools=TOOL_SCHEMAS,
                tool_choice="auto",
                max_tokens=MAX_TOKENS,
            )
        except Exception as e:
            yield {"event": "error", "message": str(e)}
            return

        if response.usage:
            session.total_input_tokens += response.usage.prompt_tokens or 0
            session.total_output_tokens += response.usage.completion_tokens or 0

        choice = response.choices[0]
        assistant_msg = choice.message

        msg_dict = {"role": "assistant", "content": assistant_msg.content or ""}
        if assistant_msg.tool_calls:
            msg_dict["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in assistant_msg.tool_calls
            ]
        session.messages.append(msg_dict)

        # Yield text if any
        if assistant_msg.content:
            yield {"event": "text", "content": assistant_msg.content}

        if not assistant_msg.tool_calls:
            yield {
                "event": "done",
                "iterations": iterations,
                "usage": {
                    "input_tokens": session.total_input_tokens,
                    "output_tokens": session.total_output_tokens,
                },
            }
            return

        # Execute tools
        for tc in assistant_msg.tool_calls:
            try:
                args = json.loads(tc.function.arguments)
            except json.JSONDecodeError:
                args = {}

            yield {"event": "tool_call", "tool": tc.function.name, "arguments": args}

            result = execute_tool(tc.function.name, args)

            yield {"event": "tool_result", "tool": tc.function.name, "result": result}

            session.messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": json.dumps(result, default=str),
            })

    yield {"event": "max_iterations", "iterations": iterations}
