"""FastAPI web API for Claw Code — an autonomous AI coding agent."""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from openai import OpenAI
from pydantic import BaseModel

from src.commands import (
    command_names,
    execute_command,
    find_commands,
    get_command,
    get_commands,
)
from src.models import PortingModule
from src.port_manifest import build_port_manifest
from src.tools import find_tools, get_tool, get_tools, tool_names
from agent.loop import (
    run_agent,
    run_agent_stream,
    get_or_create_session as get_agent_session,
    get_session as get_agent_session_data,
    list_sessions as list_agent_sessions,
    delete_session as delete_agent_session,
)
from agent.tools import WORKSPACE_ROOT, read_file as agent_read_file, list_directory as agent_list_dir

app = FastAPI(
    title="Claw Code",
    description="Autonomous AI coding agent — build apps from your browser.",
    version="3.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Orbit AI Client ──────────────────────────────────────────────────────────

ORBIT_BASE_URL = os.environ.get("ORBIT_BASE_URL", "https://api.orbit-provider.com/v1")
ORBIT_API_KEY = os.environ.get("ORBIT_API_KEY", "")
DEFAULT_MODEL = os.environ.get("ORBIT_MODEL", "claude-sonnet-4-6")

sessions: Dict[str, List[dict]] = {}

SYSTEM_PROMPT = """You are Claw Code — an AI-powered coding assistant. You help users with:
- Writing, reviewing, and debugging code
- Explaining programming concepts
- Answering technical questions
- Generating code snippets, scripts, and full applications
- Software architecture and design decisions

Be concise, accurate, and helpful. Format code with markdown code blocks."""


def get_orbit_client() -> OpenAI:
    if not ORBIT_API_KEY:
        raise HTTPException(status_code=500, detail="ORBIT_API_KEY not configured")
    return OpenAI(base_url=ORBIT_BASE_URL, api_key=ORBIT_API_KEY)


class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None
    model: Optional[str] = None
    system_prompt: Optional[str] = None


class ChatResponse(BaseModel):
    session_id: str
    response: str
    model: str
    usage: Optional[dict] = None


class AgentRequest(BaseModel):
    message: str
    session_id: Optional[str] = None
    model: Optional[str] = None
    max_iterations: Optional[int] = None


def _module_dict(m: PortingModule) -> dict:
    return {
        "name": m.name,
        "responsibility": m.responsibility,
        "source_hint": m.source_hint,
        "status": m.status,
    }


# ── Health ───────────────────────────────────────────────────────────────────


@app.get("/health")
def health():
    return {"status": "healthy"}


# ── Manifest ─────────────────────────────────────────────────────────────────


@app.get("/manifest")
def manifest():
    m = build_port_manifest()
    return {
        "src_root": str(m.src_root),
        "total_python_files": m.total_python_files,
        "modules": [
            {
                "name": s.name,
                "path": s.path,
                "file_count": s.file_count,
                "notes": s.notes,
            }
            for s in m.top_level_modules
        ],
    }


# ── Commands ─────────────────────────────────────────────────────────────────


@app.get("/commands")
def list_commands(
    query: Optional[str] = Query(None, description="Filter commands by keyword"),
    limit: int = Query(20, ge=1, le=100),
):
    if query:
        results = find_commands(query, limit=limit)
    else:
        results = list(get_commands())[:limit]
    return {"count": len(results), "commands": [_module_dict(c) for c in results]}


@app.get("/commands/{name}")
def get_single_command(name: str):
    cmd = get_command(name)
    if cmd is None:
        raise HTTPException(status_code=404, detail=f"Command '{name}' not found")
    return _module_dict(cmd)


@app.post("/commands/{name}/execute")
def run_command(name: str, prompt: str = ""):
    result = execute_command(name, prompt)
    return {
        "name": result.name,
        "source_hint": result.source_hint,
        "prompt": result.prompt,
        "handled": result.handled,
        "message": result.message,
    }


# ── Tools ────────────────────────────────────────────────────────────────────


@app.get("/tools")
def list_tools(
    query: Optional[str] = Query(None, description="Filter tools by keyword"),
    limit: int = Query(20, ge=1, le=100),
    simple_mode: bool = Query(False),
    include_mcp: bool = Query(True),
):
    if query:
        results = find_tools(query, limit=limit)
    else:
        results = list(get_tools(simple_mode=simple_mode, include_mcp=include_mcp))[:limit]
    return {"count": len(results), "tools": [_module_dict(t) for t in results]}


@app.get("/tools/{name}")
def get_single_tool(name: str):
    tool = get_tool(name)
    if tool is None:
        raise HTTPException(status_code=404, detail=f"Tool '{name}' not found")
    return _module_dict(tool)


# ── AI Chat (Orbit) ─────────────────────────────────────────────────────────


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    """Simple chat — no tools, just conversation."""
    client = get_orbit_client()
    model = req.model or DEFAULT_MODEL
    sid = req.session_id or str(uuid.uuid4())

    if sid not in sessions:
        sessions[sid] = []
    sessions[sid].append({"role": "user", "content": req.message})

    messages = [
        {"role": "system", "content": req.system_prompt or SYSTEM_PROMPT},
        *sessions[sid],
    ]

    try:
        completion = client.chat.completions.create(model=model, messages=messages, max_tokens=4096)
        assistant_msg = completion.choices[0].message.content
        sessions[sid].append({"role": "assistant", "content": assistant_msg})

        usage = None
        if completion.usage:
            usage = {
                "prompt_tokens": completion.usage.prompt_tokens,
                "completion_tokens": completion.usage.completion_tokens,
                "total_tokens": completion.usage.total_tokens,
            }
        return ChatResponse(session_id=sid, response=assistant_msg, model=model, usage=usage)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Orbit API error: {str(e)}")


@app.post("/chat/stream")
def chat_stream(req: ChatRequest):
    """Stream AI response token by token."""
    client = get_orbit_client()
    model = req.model or DEFAULT_MODEL
    sid = req.session_id or str(uuid.uuid4())

    if sid not in sessions:
        sessions[sid] = []
    sessions[sid].append({"role": "user", "content": req.message})

    messages = [
        {"role": "system", "content": req.system_prompt or SYSTEM_PROMPT},
        *sessions[sid],
    ]

    def generate():
        try:
            collected = []
            stream = client.chat.completions.create(model=model, messages=messages, max_tokens=4096, stream=True)
            for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    token = chunk.choices[0].delta.content
                    collected.append(token)
                    yield f"data: {token}\n\n"
            full_response = "".join(collected)
            sessions[sid].append({"role": "assistant", "content": full_response})
            yield "data: [DONE]\n\n"
        except Exception as e:
            yield f"data: [ERROR] {str(e)}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


@app.get("/chat/models")
def list_models():
    return {
        "default": DEFAULT_MODEL,
        "available": ["claude-sonnet-4-6", "claude-opus-4-6-thinking"],
    }


# ── Agent (Autonomous Tool-Calling) ─────────────────────────────────────────


@app.post("/agent/run")
def agent_run(req: AgentRequest):
    """Run the autonomous agent. It will think, call tools, and iterate until done."""
    try:
        result = run_agent(
            session_id=req.session_id,
            user_message=req.message,
            model=req.model,
            max_iterations=req.max_iterations,
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/agent/stream")
def agent_stream(req: AgentRequest):
    """Run the agent with streaming events (SSE)."""
    def generate():
        try:
            for event in run_agent_stream(
                session_id=req.session_id,
                user_message=req.message,
                model=req.model,
                max_iterations=req.max_iterations,
            ):
                yield f"data: {json.dumps(event, default=str)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'event': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


@app.get("/agent/sessions")
def agent_sessions():
    """List all agent sessions."""
    return {"sessions": list_agent_sessions()}


@app.get("/agent/sessions/{session_id}")
def agent_session_detail(session_id: str):
    """Get agent session details."""
    session = get_agent_session_data(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return {
        "session_id": session.session_id,
        "turns": len(session.turns),
        "iterations": session.total_iterations,
        "tokens": session.total_input_tokens + session.total_output_tokens,
        "workspace": session.workspace,
    }


@app.delete("/agent/sessions/{session_id}")
def agent_session_delete(session_id: str):
    """Delete an agent session."""
    deleted = delete_agent_session(session_id)
    return {"deleted": deleted}


@app.get("/agent/files/{session_id}")
def agent_files(session_id: str):
    """List files in an agent session's workspace."""
    session = get_agent_session_data(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    workspace = Path(session.workspace)
    if not workspace.exists():
        return {"entries": []}

    entries = []
    for item in sorted(workspace.iterdir()):
        entries.append({
            "name": item.name,
            "path": item.name,
            "type": "directory" if item.is_dir() else "file",
            "size": item.stat().st_size if item.is_file() else None,
        })
    return {"entries": entries}


@app.get("/agent/file/{session_id}")
def agent_file_content(session_id: str, path: str = Query(...)):
    """Read a file from an agent session's workspace."""
    session = get_agent_session_data(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    file_path = Path(session.workspace) / path
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    # Security: ensure path doesn't escape workspace
    if not str(file_path.resolve()).startswith(str(Path(session.workspace).resolve())):
        raise HTTPException(status_code=403, detail="Access denied")

    try:
        content = file_path.read_text(errors="replace")
        return {"path": path, "content": content[:50000], "size": file_path.stat().st_size}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Static Files & UI ───────────────────────────────────────────────────────

# Mount static files LAST to avoid catching API routes
app.mount("/", StaticFiles(directory="static", html=True), name="static")


# ── Run ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", 10000))
    uvicorn.run("app:app", host="0.0.0.0", port=port)
