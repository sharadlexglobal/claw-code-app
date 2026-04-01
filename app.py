"""FastAPI web API for the Claw Code workspace."""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
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

app = FastAPI(
    title="Claw Code API",
    description="REST API for the Claw Code workspace — AI-powered coding assistant via Orbit.",
    version="2.0.0",
)

# ── Orbit AI Client ──────────────────────────────────────────────────────────

ORBIT_BASE_URL = os.environ.get("ORBIT_BASE_URL", "https://api.orbit-provider.com/v1")
ORBIT_API_KEY = os.environ.get("ORBIT_API_KEY", "")
DEFAULT_MODEL = os.environ.get("ORBIT_MODEL", "claude-sonnet-4-6")

# In-memory session store (conversation history per session)
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


# ── Chat Models ──────────────────────────────────────────────────────────────


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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _module_dict(m: PortingModule) -> dict:
    return {
        "name": m.name,
        "responsibility": m.responsibility,
        "source_hint": m.source_hint,
        "status": m.status,
    }


# ── Health ───────────────────────────────────────────────────────────────────


@app.get("/")
def root():
    return {
        "service": "claw-code",
        "status": "ok",
        "docs": "/docs",
    }


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
    """Send a message and get an AI response. Maintains conversation history per session."""
    client = get_orbit_client()
    model = req.model or DEFAULT_MODEL
    sid = req.session_id or str(uuid.uuid4())

    # Initialize or retrieve session history
    if sid not in sessions:
        sessions[sid] = []

    # Add user message to history
    sessions[sid].append({"role": "user", "content": req.message})

    # Build messages with system prompt + history
    messages = [
        {"role": "system", "content": req.system_prompt or SYSTEM_PROMPT},
        *sessions[sid],
    ]

    try:
        completion = client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=4096,
        )
        assistant_msg = completion.choices[0].message.content
        sessions[sid].append({"role": "assistant", "content": assistant_msg})

        usage = None
        if completion.usage:
            usage = {
                "prompt_tokens": completion.usage.prompt_tokens,
                "completion_tokens": completion.usage.completion_tokens,
                "total_tokens": completion.usage.total_tokens,
            }

        return ChatResponse(
            session_id=sid,
            response=assistant_msg,
            model=model,
            usage=usage,
        )
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
            stream = client.chat.completions.create(
                model=model,
                messages=messages,
                max_tokens=4096,
                stream=True,
            )
            for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    token = chunk.choices[0].delta.content
                    collected.append(token)
                    yield f"data: {token}\n\n"

            # Save full response to session
            full_response = "".join(collected)
            sessions[sid].append({"role": "assistant", "content": full_response})
            yield "data: [DONE]\n\n"
        except Exception as e:
            yield f"data: [ERROR] {str(e)}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


@app.get("/chat/sessions/{session_id}")
def get_session(session_id: str):
    """Get conversation history for a session."""
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"session_id": session_id, "messages": sessions[session_id]}


@app.delete("/chat/sessions/{session_id}")
def delete_session(session_id: str):
    """Clear a conversation session."""
    if session_id in sessions:
        del sessions[session_id]
    return {"status": "deleted", "session_id": session_id}


@app.get("/chat/models")
def list_models():
    """List available models via Orbit."""
    return {
        "default": DEFAULT_MODEL,
        "available": [
            "claude-sonnet-4-6",
            "claude-opus-4-6-thinking",
        ],
    }


# ── Run ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", 10000))
    uvicorn.run("app:app", host="0.0.0.0", port=port)
