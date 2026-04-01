"""FastAPI web API for the Claw Code workspace."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

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
    description="REST API for the Claw Code workspace — a Python port of Claude Code.",
    version="1.0.0",
)

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


# ── Run ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", 10000))
    uvicorn.run("app:app", host="0.0.0.0", port=port)
