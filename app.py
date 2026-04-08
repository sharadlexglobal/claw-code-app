"""FastAPI web API for Claw Code — an autonomous AI coding agent."""

from __future__ import annotations

import io
import json
import os
import uuid
import zipfile
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
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
from settings import Settings, SettingsUpdate, load_settings, save_settings, mask_token
from agent.skills import (
    list_skills as skill_list_all,
    get_skill as skill_get,
    create_skill as skill_create,
    update_skill as skill_update,
    delete_skill as skill_delete,
)

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
DEFAULT_MODEL = os.environ.get("ORBIT_MODEL", "claude-opus-4-6")
FALLBACK_MODEL = os.environ.get("ORBIT_FALLBACK_MODEL", "claude-sonnet-4-6")

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
    return OpenAI(base_url=ORBIT_BASE_URL, api_key=ORBIT_API_KEY, timeout=80.0)


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


class Attachment(BaseModel):
    filename: str
    content_type: str  # e.g. "image/png", "text/plain"
    data: str  # base64 for images, raw text for text files


class AgentRequest(BaseModel):
    message: str
    session_id: Optional[str] = None
    model: Optional[str] = None
    max_iterations: Optional[int] = None
    attachments: Optional[List[Attachment]] = None


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
    return {"status": "healthy", "version": "2.1.0"}


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

    used_model = model
    try:
        completion = client.chat.completions.create(model=model, messages=messages, max_tokens=4096)
        assistant_msg = completion.choices[0].message.content
    except Exception as e:
        if model != FALLBACK_MODEL:
            print(f"[CHAT] Primary model {model} failed: {e}. Falling back to {FALLBACK_MODEL}")
            try:
                used_model = FALLBACK_MODEL
                completion = client.chat.completions.create(model=FALLBACK_MODEL, messages=messages, max_tokens=4096)
                assistant_msg = completion.choices[0].message.content
            except Exception as e2:
                raise HTTPException(status_code=502, detail=f"Orbit API error (both models failed): {str(e2)}")
        else:
            raise HTTPException(status_code=502, detail=f"Orbit API error: {str(e)}")

    sessions[sid].append({"role": "assistant", "content": assistant_msg})
    usage = None
    if completion.usage:
        usage = {
            "prompt_tokens": completion.usage.prompt_tokens,
            "completion_tokens": completion.usage.completion_tokens,
            "total_tokens": completion.usage.total_tokens,
        }
    return ChatResponse(session_id=sid, response=assistant_msg, model=used_model, usage=usage)


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
        used_model = model
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
            if model != FALLBACK_MODEL:
                print(f"[CHAT-STREAM] Primary model {model} failed: {e}. Falling back to {FALLBACK_MODEL}")
                try:
                    collected = []
                    stream = client.chat.completions.create(model=FALLBACK_MODEL, messages=messages, max_tokens=4096, stream=True)
                    for chunk in stream:
                        if chunk.choices and chunk.choices[0].delta.content:
                            token = chunk.choices[0].delta.content
                            collected.append(token)
                            yield f"data: {token}\n\n"
                    full_response = "".join(collected)
                    sessions[sid].append({"role": "assistant", "content": full_response})
                    yield "data: [DONE]\n\n"
                except Exception as e2:
                    yield f"data: [ERROR] Both models failed: {str(e2)}\n\n"
            else:
                yield f"data: [ERROR] {str(e)}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


@app.get("/chat/models")
def list_models():
    return {
        "default": DEFAULT_MODEL,
        "fallback": FALLBACK_MODEL,
        "available": ["claude-opus-4-6", "claude-sonnet-4-6"],
    }


# ── Agent (Autonomous Tool-Calling) ─────────────────────────────────────────


def _serialize_attachments(attachments: Optional[List[Attachment]]) -> Optional[list]:
    """Convert Attachment models to dicts for the agent loop."""
    if not attachments:
        return None
    return [{"filename": a.filename, "content_type": a.content_type, "data": a.data} for a in attachments]


@app.post("/agent/run")
def agent_run(req: AgentRequest):
    """Run the autonomous agent. It will think, call tools, and iterate until done."""
    try:
        result = run_agent(
            session_id=req.session_id,
            user_message=req.message,
            model=req.model,
            max_iterations=req.max_iterations,
            attachments=_serialize_attachments(req.attachments),
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
                attachments=_serialize_attachments(req.attachments),
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
    """List ALL files in an agent session's workspace (recursive)."""
    session = get_agent_session_data(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    workspace = Path(session.workspace)
    if not workspace.exists():
        return {"entries": []}

    entries = []
    # Recursive listing — find ALL files in workspace
    for item in sorted(workspace.rglob("*")):
        if item.is_file():
            rel = str(item.relative_to(workspace))
            entries.append({
                "name": item.name,
                "path": rel,
                "type": "file",
                "size": item.stat().st_size,
            })
    # Also add top-level directories for context
    for item in sorted(workspace.iterdir()):
        if item.is_dir():
            entries.insert(0, {
                "name": item.name,
                "path": item.name,
                "type": "directory",
                "size": None,
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


# ── Live Preview ─────────────────────────────────────────────────────────────


@app.get("/agent/preview/{session_id}")
def agent_preview(session_id: str, file: str = Query("index.html")):
    """Serve an HTML file from the workspace for live preview.

    Finds index.html or the first .html file in the workspace.
    Rewrites relative asset paths to serve via the API.
    """
    session = get_agent_session_data(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    workspace = Path(session.workspace)

    # Find the HTML file
    target = workspace / file
    if not target.exists():
        # Try to find any HTML file
        html_files = list(workspace.rglob("*.html"))
        if not html_files:
            return HTMLResponse("<html><body><h2>No HTML files found in workspace</h2></body></html>")
        target = html_files[0]
        file = str(target.relative_to(workspace))

    if not str(target.resolve()).startswith(str(workspace.resolve())):
        raise HTTPException(status_code=403, detail="Access denied")

    content = target.read_text(errors="replace")

    # Inject a <base> tag so relative CSS/JS/image paths resolve via our asset endpoint
    # IMPORTANT: include the subdirectory of the HTML file so relative paths resolve correctly
    file_dir = str(Path(file).parent)
    if file_dir == ".":
        base_url = f"/agent/asset/{session_id}/"
    else:
        base_url = f"/agent/asset/{session_id}/{file_dir}/"
    base_tag = f'<base href="{base_url}">'
    if "<head>" in content:
        content = content.replace("<head>", f"<head>{base_tag}", 1)
    elif "<HEAD>" in content:
        content = content.replace("<HEAD>", f"<HEAD>{base_tag}", 1)
    elif "<html" in content.lower():
        # No <head> tag — inject one after <html...>
        import re as _re
        content = _re.sub(r'(<html[^>]*>)', rf'\1<head>{base_tag}</head>', content, count=1, flags=_re.IGNORECASE)
    else:
        # Bare HTML — prepend base tag
        content = f"{base_tag}\n{content}"

    return HTMLResponse(content)


@app.get("/agent/asset/{session_id}/{path:path}")
def agent_asset(session_id: str, path: str):
    """Serve any asset (CSS, JS, images) from the workspace."""
    session = get_agent_session_data(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    file_path = Path(session.workspace) / path
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    if not str(file_path.resolve()).startswith(str(Path(session.workspace).resolve())):
        raise HTTPException(status_code=403, detail="Access denied")

    # Determine content type
    suffix = file_path.suffix.lower()
    content_types = {
        ".html": "text/html", ".css": "text/css", ".js": "application/javascript",
        ".json": "application/json", ".png": "image/png", ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg", ".gif": "image/gif", ".svg": "image/svg+xml",
        ".ico": "image/x-icon", ".woff": "font/woff", ".woff2": "font/woff2",
        ".ttf": "font/ttf",
    }
    ct = content_types.get(suffix, "application/octet-stream")

    if ct.startswith("text") or ct == "application/javascript" or ct == "application/json":
        return Response(content=file_path.read_text(errors="replace"), media_type=ct)
    else:
        return Response(content=file_path.read_bytes(), media_type=ct)


@app.get("/agent/preview-files/{session_id}")
def agent_preview_files(session_id: str):
    """List all previewable files (HTML, images, etc.) in the workspace."""
    session = get_agent_session_data(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    workspace = Path(session.workspace)
    if not workspace.exists():
        return {"html_files": [], "all_files": []}

    previewable = {".html", ".htm"}
    html_files = []
    all_files = []

    for f in workspace.rglob("*"):
        if f.is_file():
            rel = str(f.relative_to(workspace))
            all_files.append(rel)
            if f.suffix.lower() in previewable:
                html_files.append(rel)

    return {"html_files": html_files, "all_files": all_files}


# ── Skills ──────────────────────────────────────────────────────────────────


class SkillCreate(BaseModel):
    name: str
    description: str = ""
    content: str = ""
    allowed_tools: Optional[List[str]] = None
    disable_model_invocation: bool = False


class SkillUpdateReq(BaseModel):
    description: Optional[str] = None
    content: Optional[str] = None
    allowed_tools: Optional[List[str]] = None
    disable_model_invocation: Optional[bool] = None


@app.get("/skills")
def api_list_skills():
    """List all available skills."""
    skills = skill_list_all()
    return {
        "skills": [
            {
                "name": s.name,
                "description": s.description,
                "allowed_tools": s.allowed_tools,
                "disable_model_invocation": s.disable_model_invocation,
            }
            for s in skills
        ],
        "count": len(skills),
    }


@app.get("/skills/{name}")
def api_get_skill(name: str):
    """Get a skill by name (includes content)."""
    s = skill_get(name)
    if not s:
        raise HTTPException(status_code=404, detail=f"Skill '{name}' not found")
    return {
        "name": s.name,
        "description": s.description,
        "content": s.content,
        "allowed_tools": s.allowed_tools,
        "disable_model_invocation": s.disable_model_invocation,
    }


@app.post("/skills")
def api_create_skill(req: SkillCreate):
    """Create a new skill."""
    try:
        s = skill_create(
            name=req.name,
            description=req.description,
            content=req.content,
            allowed_tools=req.allowed_tools,
            disable_model_invocation=req.disable_model_invocation,
        )
        return {"name": s.name, "status": "created"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.put("/skills/{name}")
def api_update_skill(name: str, req: SkillUpdateReq):
    """Update an existing skill."""
    s = skill_update(
        name=name,
        description=req.description,
        content=req.content,
        allowed_tools=req.allowed_tools,
        disable_model_invocation=req.disable_model_invocation,
    )
    if not s:
        raise HTTPException(status_code=404, detail=f"Skill '{name}' not found")
    return {"name": s.name, "status": "updated"}


@app.delete("/skills/{name}")
def api_delete_skill(name: str):
    """Delete a skill."""
    deleted = skill_delete(name)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Skill '{name}' not found")
    return {"name": name, "status": "deleted"}


# ── Settings ────────────────────────────────────────────────────────────────


@app.get("/settings")
def get_settings():
    """Get current settings (tokens masked)."""
    s = load_settings()
    return {
        "github_token": mask_token(s.github_token),
        "render_api_key": mask_token(s.render_api_key),
        "default_model": s.default_model,
        "fallback_model": s.fallback_model,
        "max_iterations": s.max_iterations,
        "skills_directory": s.skills_directory,
        "github_connected": bool(s.github_token),
        "render_connected": bool(s.render_api_key),
        "r2_account_id": s.r2_account_id or "",
        "r2_access_key": mask_token(s.r2_access_key),
        "r2_secret_key": mask_token(s.r2_secret_key),
        "r2_bucket_name": s.r2_bucket_name or "",
        "r2_public_url": s.r2_public_url or "",
        "r2_connected": bool(s.r2_account_id and s.r2_access_key and s.r2_secret_key),
        # code0.ai fallback LLM
        "code0_base_url": s.code0_base_url or "https://code0.ai/v1",
        "code0_api_key": mask_token(s.code0_api_key),
        "code0_default_model": s.code0_default_model or "gemini-2.5-flash",
        "code0_connected": bool(os.environ.get("CODE0_API_KEY") or s.code0_api_key),
        "content_llm_provider": s.content_llm_provider or "auto",
    }


@app.put("/settings")
def update_settings(req: SettingsUpdate):
    """Update settings (merge with existing)."""
    current = load_settings()
    updates = req.model_dump(exclude_none=True)
    merged = current.model_dump()
    merged.update(updates)
    new_settings = Settings(**merged)
    save_settings(new_settings)
    return {"status": "saved"}


# ── Download ZIP ────────────────────────────────────────────────────────────


SKIP_DIRS = {"node_modules", ".git", "__pycache__", ".venv", "venv"}


@app.get("/agent/download/{session_id}")
def download_workspace(session_id: str):
    """Download all workspace files as a ZIP archive."""
    session = get_agent_session_data(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    workspace = Path(session.workspace)
    if not workspace.exists():
        raise HTTPException(status_code=404, detail="Workspace empty")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for file_path in sorted(workspace.rglob("*")):
            if file_path.is_file():
                # Skip large/irrelevant directories
                parts = file_path.relative_to(workspace).parts
                if any(p in SKIP_DIRS for p in parts):
                    continue
                rel = str(file_path.relative_to(workspace))
                zf.write(file_path, rel)

    buf.seek(0)
    filename = f"claw-code-{session_id[:8]}.zip"
    return Response(
        content=buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


# ── Content Factory ────────────────────────────────────────────────────────

from content.models import (
    PERSONAS,
    CONTENT_TYPES,
    LEGAL_DOMAINS,
    ContentGenerateRequest,
    PromptCreateRequest,
    PromptUpdateRequest,
    PromptTestRequest,
)


@app.get("/content/personas")
def content_personas():
    return PERSONAS


@app.get("/content/types")
def content_types():
    return {"types": CONTENT_TYPES}


@app.get("/content/domains")
def content_domains():
    return {"domains": LEGAL_DOMAINS}


@app.post("/content/generate")
def content_generate(req: ContentGenerateRequest):
    """Generate content for all (or selected) content types and save to library."""
    from content.generator import generate_all
    from content.library import add_to_library

    try:
        result = generate_all(
            persona_id=req.persona_id,
            raw_input=req.raw_input,
            legal_domain=req.legal_domain,
            content_types=req.content_types,
            model=req.model,
        )
        item = add_to_library(result)
        return {
            "content_id": result.content_id,
            "persona_id": result.persona_id,
            "legal_domain": result.legal_domain,
            "topic": result.topic,
            "created_at": result.created_at,
            "model_used": result.model_used,
            "pieces": [p.model_dump() for p in result.pieces],
            "library_item": item.model_dump(),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Content Prompts ────────────────────────────────────────────────────────


@app.get("/content/prompts")
def content_list_prompts(persona_id: Optional[str] = Query(None)):
    from content.prompts import list_prompts
    records = list_prompts(persona_id)
    return {"prompts": [r.model_dump() for r in records], "count": len(records)}


@app.get("/content/prompts/{persona_id}/{content_type}")
def content_get_prompt(persona_id: str, content_type: str):
    from content.prompts import get_prompt
    record = get_prompt(persona_id, content_type)
    if not record:
        return {"persona_id": persona_id, "content_type": content_type, "drafts": [], "active_draft_id": None}
    return record.model_dump()


@app.post("/content/prompts/{persona_id}/{content_type}/drafts")
def content_create_draft(persona_id: str, content_type: str, req: PromptCreateRequest):
    from content.prompts import create_prompt_draft
    draft = create_prompt_draft(persona_id, content_type, req.prompt_text)
    return {"draft": draft.model_dump(), "status": "created"}


@app.put("/content/prompts/{persona_id}/{content_type}/drafts/{draft_id}")
def content_update_draft(persona_id: str, content_type: str, draft_id: str, req: PromptUpdateRequest):
    from content.prompts import update_prompt_draft
    draft = update_prompt_draft(persona_id, content_type, draft_id, req.prompt_text, req.is_active)
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    return {"draft": draft.model_dump(), "status": "updated"}


@app.delete("/content/prompts/{persona_id}/{content_type}/drafts/{draft_id}")
def content_delete_draft(persona_id: str, content_type: str, draft_id: str):
    from content.prompts import delete_prompt_draft
    deleted = delete_prompt_draft(persona_id, content_type, draft_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Draft not found")
    return {"status": "deleted"}


@app.post("/content/prompts/test")
def content_test_prompt(req: PromptTestRequest):
    from content.generator import test_prompt
    try:
        result = test_prompt(
            persona_id=req.persona_id,
            content_type=req.content_type,
            prompt_text=req.prompt_text or "",
            sample_input=req.sample_input,
            model=req.model,
        )
        # If draft_id provided, store test output
        if req.draft_id:
            from content.prompts import set_test_output
            set_test_output(req.persona_id, req.content_type, req.draft_id, result.output)
        return result.model_dump()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Content Library ────────────────────────────────────────────────────────


@app.get("/content/library")
def content_list_library(
    persona_id: Optional[str] = Query(None),
    legal_domain: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
):
    from content.library import list_library
    result = list_library(persona_id, legal_domain, search, offset, limit)
    return result.model_dump()


@app.get("/content/library/{content_id}")
def content_get_library_item(content_id: str):
    from content.library import get_library_item
    item = get_library_item(content_id)
    if not item:
        raise HTTPException(status_code=404, detail="Content not found")
    return item.model_dump()


@app.get("/content/library/{content_id}/content")
def content_get_library_content(content_id: str):
    from content.library import get_library_content
    content = get_library_content(content_id)
    if not content:
        raise HTTPException(status_code=404, detail="Content not found")
    return content.model_dump()


@app.delete("/content/library/{content_id}")
def content_delete_library_item(content_id: str):
    from content.library import delete_from_library
    deleted = delete_from_library(content_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Content not found")
    return {"status": "deleted"}


@app.post("/content/library/{content_id}/upload")
def content_upload_to_r2(content_id: str):
    from content.library import upload_to_r2
    try:
        public_url = upload_to_r2(content_id)
        return {"status": "uploaded", "public_url": public_url, "content_id": content_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/content/skills")
def content_skills():
    """List all content skills and their mappings."""
    from content.skill_injector import CONTENT_SKILL_MAP, UNIVERSAL_SKILLS, list_applied_skills
    from agent.skills import list_skills as skill_list_all
    all_skills = skill_list_all()
    return {
        "skills": [
            {"name": s.name, "description": s.description}
            for s in all_skills
        ],
        "mapping": CONTENT_SKILL_MAP,
        "universal": UNIVERSAL_SKILLS,
    }


@app.get("/content/skills/{content_type}")
def content_skills_for_type(content_type: str):
    """Get skills that auto-apply for a specific content type."""
    from content.skill_injector import list_applied_skills
    return {"content_type": content_type, "skills": list_applied_skills(content_type)}


@app.get("/content/r2/status")
def content_r2_status():
    from content.r2 import check_connection
    return check_connection()


# ── Deploy: GitHub Push ────────────────────────────────────────────────────


class GitHubPushRequest(BaseModel):
    session_id: str
    repo: str  # "owner/repo" format
    branch: str = "main"
    commit_message: str = "Deploy from Claw Code"


@app.post("/agent/deploy/github")
def deploy_github(req: GitHubPushRequest):
    """Push workspace files to a GitHub repository."""
    session = get_agent_session_data(req.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    try:
        from deploy.github import push_to_github
        result = push_to_github(
            workspace=session.workspace,
            repo_full_name=req.repo,
            branch=req.branch,
            commit_message=req.commit_message,
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Deploy: Render ─────────────────────────────────────────────────────────


class RenderDeployRequest(BaseModel):
    session_id: str
    service_name: str = ""
    repo: str = ""  # GitHub repo to deploy from


@app.post("/agent/deploy/render")
def deploy_render(req: RenderDeployRequest):
    """Deploy to Render from a GitHub repo."""
    session = get_agent_session_data(req.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    try:
        from deploy.render import deploy_to_render
        result = deploy_to_render(
            workspace=session.workspace,
            service_name=req.service_name,
            repo=req.repo,
        )
        return result
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
