"""Tool definitions and execution for the Claw Code agent.

Each tool is defined as an OpenAI-compatible function schema and has
an execute() handler that performs the actual operation on the server workspace.
"""

from __future__ import annotations

import json
import os
import subprocess
import glob as glob_module
import re
from pathlib import Path
from typing import Any

# ── Workspace Sandbox ────────────────────────────────────────────────────────
# All file operations are restricted to WORKSPACE_ROOT.

WORKSPACE_ROOT = Path(os.environ.get("CLAW_WORKSPACE", "/tmp/claw-workspace"))
WORKSPACE_ROOT.mkdir(parents=True, exist_ok=True)

BASH_TIMEOUT = int(os.environ.get("CLAW_BASH_TIMEOUT", "30"))
BASH_BLOCKED_COMMANDS = {"rm -rf /", "mkfs", "dd if=", ":(){ :|:& };:", "shutdown", "reboot", "poweroff"}


def _safe_path(requested: str) -> Path:
    """Resolve *requested* path inside the workspace, blocking escapes."""
    if requested.startswith("/"):
        resolved = Path(requested).resolve()
    else:
        resolved = (WORKSPACE_ROOT / requested).resolve()
    if not str(resolved).startswith(str(WORKSPACE_ROOT.resolve())):
        raise PermissionError(f"Path escapes workspace: {requested}")
    return resolved


# ── Tool: read_file ──────────────────────────────────────────────────────────

def read_file(file_path: str, offset: int = 0, limit: int = 2000) -> dict:
    """Read a file from the workspace."""
    path = _safe_path(file_path)
    if not path.exists():
        return {"error": f"File not found: {file_path}"}
    if not path.is_file():
        return {"error": f"Not a file: {file_path}"}
    lines = path.read_text(errors="replace").splitlines()
    selected = lines[offset:offset + limit]
    numbered = [f"{i + offset + 1}\t{line}" for i, line in enumerate(selected)]
    return {
        "file_path": str(path.relative_to(WORKSPACE_ROOT)),
        "total_lines": len(lines),
        "offset": offset,
        "lines_returned": len(selected),
        "content": "\n".join(numbered),
    }


# ── Tool: write_file ────────────────────────────────────────────────────────

def write_file(file_path: str, content: str) -> dict:
    """Write (create or overwrite) a file in the workspace."""
    path = _safe_path(file_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return {
        "file_path": str(path.relative_to(WORKSPACE_ROOT)),
        "bytes_written": len(content.encode()),
        "status": "ok",
    }


# ── Tool: edit_file ─────────────────────────────────────────────────────────

def edit_file(file_path: str, old_string: str, new_string: str) -> dict:
    """Replace the first occurrence of old_string with new_string in a file."""
    path = _safe_path(file_path)
    if not path.exists():
        return {"error": f"File not found: {file_path}"}
    text = path.read_text(errors="replace")
    if old_string not in text:
        return {"error": "old_string not found in file"}
    count = text.count(old_string)
    updated = text.replace(old_string, new_string, 1)
    path.write_text(updated)
    return {
        "file_path": str(path.relative_to(WORKSPACE_ROOT)),
        "occurrences_found": count,
        "replaced": 1,
        "status": "ok",
    }


# ── Tool: list_directory ────────────────────────────────────────────────────

def list_directory(directory: str = ".") -> dict:
    """List files and directories in a workspace path."""
    path = _safe_path(directory)
    if not path.exists():
        return {"error": f"Directory not found: {directory}"}
    if not path.is_dir():
        return {"error": f"Not a directory: {directory}"}
    entries = []
    for item in sorted(path.iterdir()):
        rel = str(item.relative_to(WORKSPACE_ROOT))
        entries.append({
            "name": item.name,
            "path": rel,
            "type": "directory" if item.is_dir() else "file",
            "size": item.stat().st_size if item.is_file() else None,
        })
    return {"directory": str(path.relative_to(WORKSPACE_ROOT)), "entries": entries}


# ── Tool: search_files ──────────────────────────────────────────────────────

def search_files(pattern: str, directory: str = ".", file_glob: str = "*") -> dict:
    """Search for a regex pattern in files under directory."""
    path = _safe_path(directory)
    if not path.is_dir():
        return {"error": f"Not a directory: {directory}"}
    regex = re.compile(pattern, re.IGNORECASE)
    matches = []
    for fpath in path.rglob(file_glob):
        if not fpath.is_file():
            continue
        try:
            for i, line in enumerate(fpath.read_text(errors="replace").splitlines(), 1):
                if regex.search(line):
                    matches.append({
                        "file": str(fpath.relative_to(WORKSPACE_ROOT)),
                        "line_number": i,
                        "content": line.strip()[:200],
                    })
                    if len(matches) >= 50:
                        return {"pattern": pattern, "matches": matches, "truncated": True}
        except Exception:
            continue
    return {"pattern": pattern, "matches": matches, "truncated": False}


# ── Tool: bash ───────────────────────────────────────────────────────────────

def run_bash(command: str, timeout: int | None = None) -> dict:
    """Execute a bash command inside the workspace directory."""
    for blocked in BASH_BLOCKED_COMMANDS:
        if blocked in command:
            return {"error": f"Blocked dangerous command: {blocked}"}
    try:
        result = subprocess.run(
            ["bash", "-c", command],
            capture_output=True,
            text=True,
            timeout=timeout or BASH_TIMEOUT,
            cwd=str(WORKSPACE_ROOT),
            env={**os.environ, "HOME": str(WORKSPACE_ROOT)},
        )
        return {
            "stdout": result.stdout[-5000:] if len(result.stdout) > 5000 else result.stdout,
            "stderr": result.stderr[-2000:] if len(result.stderr) > 2000 else result.stderr,
            "exit_code": result.returncode,
        }
    except subprocess.TimeoutExpired:
        return {"error": f"Command timed out after {timeout or BASH_TIMEOUT}s"}
    except Exception as e:
        return {"error": str(e)}


# ── Tool Registry ────────────────────────────────────────────────────────────

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a file from the workspace. Returns numbered lines.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Path to the file (relative to workspace root)"},
                    "offset": {"type": "integer", "description": "Start reading from this line (0-indexed)", "default": 0},
                    "limit": {"type": "integer", "description": "Max lines to read", "default": 2000},
                },
                "required": ["file_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Create or overwrite a file in the workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Path to the file (relative to workspace root)"},
                    "content": {"type": "string", "description": "Full file content to write"},
                },
                "required": ["file_path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": "Replace the first occurrence of old_string with new_string in a file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Path to the file"},
                    "old_string": {"type": "string", "description": "Text to find"},
                    "new_string": {"type": "string", "description": "Text to replace with"},
                },
                "required": ["file_path", "old_string", "new_string"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_directory",
            "description": "List files and directories in a workspace path.",
            "parameters": {
                "type": "object",
                "properties": {
                    "directory": {"type": "string", "description": "Directory path (relative to workspace root)", "default": "."},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_files",
            "description": "Search for a regex pattern in files under a directory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Regex pattern to search for"},
                    "directory": {"type": "string", "description": "Directory to search in", "default": "."},
                    "file_glob": {"type": "string", "description": "File glob pattern (e.g. '*.py')", "default": "*"},
                },
                "required": ["pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "bash",
            "description": "Execute a bash command in the workspace. Use for: installing packages, running code, git operations, build commands, etc.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "The bash command to execute"},
                    "timeout": {"type": "integer", "description": "Timeout in seconds (default 30)", "default": 30},
                },
                "required": ["command"],
            },
        },
    },
]


def execute_tool(name: str, arguments: dict[str, Any]) -> dict:
    """Dispatch a tool call to the appropriate handler."""
    handlers = {
        "read_file": read_file,
        "write_file": write_file,
        "edit_file": edit_file,
        "list_directory": list_directory,
        "search_files": search_files,
        "bash": run_bash,
    }
    handler = handlers.get(name)
    if handler is None:
        return {"error": f"Unknown tool: {name}"}
    try:
        # Map 'command' param for bash tool
        if name == "bash":
            return handler(command=arguments.get("command", ""), timeout=arguments.get("timeout"))
        return handler(**arguments)
    except Exception as e:
        return {"error": f"Tool execution error: {str(e)}"}
