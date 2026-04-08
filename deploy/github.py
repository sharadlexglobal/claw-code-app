"""GitHub deploy — push workspace files via GitHub Git Data API.

Uses the REST API (blobs → tree → commit → ref) for atomic multi-file
commits without requiring the git CLI on the server.
"""

from __future__ import annotations

import base64
import json
import os
import urllib.request
import urllib.error
from pathlib import Path
from typing import Optional

from settings import load_settings

API = "https://api.github.com"

# Files/dirs to skip when pushing
SKIP_DIRS = {"__pycache__", ".git", "node_modules", ".venv", "venv", ".DS_Store"}
SKIP_FILES = {".DS_Store", "Thumbs.db"}


def _get_token() -> str:
    settings = load_settings()
    token = settings.github_token
    if not token:
        raise RuntimeError("GitHub token not configured. Set it in Settings.")
    return token


def _api(method: str, path: str, token: str, body: Optional[dict] = None) -> dict:
    """Make a GitHub API request."""
    url = f"{API}{path}" if path.startswith("/") else path
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3+json",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        error_body = e.read().decode() if e.fp else ""
        raise RuntimeError(f"GitHub API {method} {path}: {e.code} {error_body[:500]}")


def _collect_files(workspace: str) -> list[tuple[str, bytes]]:
    """Collect all files from workspace, returns list of (relative_path, content_bytes)."""
    files = []
    root = Path(workspace)
    for p in sorted(root.rglob("*")):
        if p.is_dir():
            continue
        # Skip unwanted files/dirs
        parts = p.relative_to(root).parts
        if any(part in SKIP_DIRS for part in parts):
            continue
        if p.name in SKIP_FILES:
            continue
        try:
            content = p.read_bytes()
        except Exception:
            continue
        rel = str(p.relative_to(root))
        files.append((rel, content))
    return files


def _ensure_repo(owner: str, repo: str, token: str) -> bool:
    """Check if repo exists, return True if it does."""
    try:
        _api("GET", f"/repos/{owner}/{repo}", token)
        return True
    except RuntimeError:
        return False


def _create_repo(name: str, token: str, private: bool = False) -> dict:
    """Create a new GitHub repository."""
    return _api("POST", "/user/repos", token, {
        "name": name,
        "private": private,
        "auto_init": True,
    })


def push_to_github(
    workspace: str,
    repo_full_name: str,
    branch: str = "main",
    commit_message: str = "Deploy from Claw Code",
) -> dict:
    """Push all workspace files to a GitHub repo using Git Data API.

    Args:
        workspace: Path to the workspace directory
        repo_full_name: "owner/repo" format
        branch: Target branch (default: main)
        commit_message: Commit message

    Returns:
        dict with status, commit_sha, and url
    """
    token = _get_token()

    if "/" not in repo_full_name:
        raise ValueError("repo must be in 'owner/repo' format")

    owner, repo = repo_full_name.split("/", 1)

    # Create repo if it doesn't exist
    if not _ensure_repo(owner, repo, token):
        print(f"[GITHUB] Repo {repo_full_name} not found, creating...")
        _create_repo(repo, token)

    # Collect workspace files
    files = _collect_files(workspace)
    if not files:
        return {"status": "error", "message": "No files to push"}

    print(f"[GITHUB] Pushing {len(files)} files to {repo_full_name}/{branch}")

    # Step 1: Create blobs for each file
    tree_items = []
    for rel_path, content in files:
        blob = _api("POST", f"/repos/{owner}/{repo}/git/blobs", token, {
            "content": base64.b64encode(content).decode(),
            "encoding": "base64",
        })
        tree_items.append({
            "path": rel_path,
            "mode": "100644",
            "type": "blob",
            "sha": blob["sha"],
        })
        print(f"[GITHUB]   Blob: {rel_path} -> {blob['sha'][:8]}")

    # Step 2: Get current commit SHA (if branch exists)
    parent_sha = None
    try:
        ref = _api("GET", f"/repos/{owner}/{repo}/git/ref/heads/{branch}", token)
        parent_sha = ref["object"]["sha"]
    except RuntimeError:
        # Branch doesn't exist yet — try default branch
        try:
            repo_info = _api("GET", f"/repos/{owner}/{repo}", token)
            default_branch = repo_info.get("default_branch", "main")
            if default_branch != branch:
                ref = _api("GET", f"/repos/{owner}/{repo}/git/ref/heads/{default_branch}", token)
                parent_sha = ref["object"]["sha"]
        except RuntimeError:
            pass

    # Step 3: Create tree
    tree_payload = {"tree": tree_items}
    if parent_sha:
        # Get the tree of the parent commit to use as base
        parent_commit = _api("GET", f"/repos/{owner}/{repo}/git/commits/{parent_sha}", token)
        tree_payload["base_tree"] = parent_commit["tree"]["sha"]

    tree = _api("POST", f"/repos/{owner}/{repo}/git/trees", token, tree_payload)
    print(f"[GITHUB]   Tree: {tree['sha'][:8]}")

    # Step 4: Create commit
    commit_payload = {
        "message": commit_message,
        "tree": tree["sha"],
    }
    if parent_sha:
        commit_payload["parents"] = [parent_sha]

    commit = _api("POST", f"/repos/{owner}/{repo}/git/commits", token, commit_payload)
    print(f"[GITHUB]   Commit: {commit['sha'][:8]}")

    # Step 5: Update or create ref
    try:
        _api("PATCH", f"/repos/{owner}/{repo}/git/refs/heads/{branch}", token, {
            "sha": commit["sha"],
            "force": True,
        })
    except RuntimeError:
        # Branch doesn't exist, create it
        _api("POST", f"/repos/{owner}/{repo}/git/refs", token, {
            "ref": f"refs/heads/{branch}",
            "sha": commit["sha"],
        })

    url = f"https://github.com/{owner}/{repo}"
    print(f"[GITHUB] Done! {url}")

    return {
        "status": "success",
        "commit_sha": commit["sha"],
        "url": url,
        "files_pushed": len(files),
        "branch": branch,
    }
