"""Render deploy — create/update web services via the Render REST API.

Detects runtime from workspace files and configures the service accordingly.
Requires a GitHub repo (push to GitHub first, then deploy to Render from it).
"""

from __future__ import annotations

import json
import os
import urllib.request
import urllib.error
from pathlib import Path
from typing import Optional

from settings import load_settings

API = "https://api.render.com/v1"


def _get_key() -> str:
    settings = load_settings()
    key = settings.render_api_key
    if not key:
        raise RuntimeError("Render API key not configured. Set it in Settings.")
    return key


def _api(method: str, path: str, key: str, body: Optional[dict] = None):
    """Make a Render API request."""
    url = f"{API}{path}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {key}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        error_body = e.read().decode() if e.fp else ""
        raise RuntimeError(f"Render API {method} {path}: {e.code} {error_body[:500]}")


def _detect_runtime(workspace: str) -> dict:
    """Detect the runtime and build/start commands from workspace files."""
    root = Path(workspace)

    # Python (FastAPI/Flask)
    if (root / "requirements.txt").exists():
        # Check for common frameworks
        reqs = (root / "requirements.txt").read_text(errors="replace").lower()
        if "fastapi" in reqs or "uvicorn" in reqs:
            start_cmd = "uvicorn app:app --host 0.0.0.0 --port $PORT"
        elif "flask" in reqs:
            start_cmd = "gunicorn app:app --bind 0.0.0.0:$PORT"
        else:
            start_cmd = "python app.py"
        return {
            "runtime": "python",
            "build_command": "pip install -r requirements.txt",
            "start_command": start_cmd,
        }

    # Node.js
    if (root / "package.json").exists():
        try:
            pkg = json.loads((root / "package.json").read_text())
            start = pkg.get("scripts", {}).get("start", "node index.js")
            build = pkg.get("scripts", {}).get("build", "npm install")
            return {
                "runtime": "node",
                "build_command": f"npm install && npm run build" if "build" in pkg.get("scripts", {}) else "npm install",
                "start_command": f"npm start" if "start" in pkg.get("scripts", {}) else start,
            }
        except Exception:
            return {
                "runtime": "node",
                "build_command": "npm install",
                "start_command": "npm start",
            }

    # Static site (HTML only)
    html_files = list(root.glob("*.html"))
    if html_files:
        return {
            "runtime": "static",
            "build_command": "",
            "start_command": "",
        }

    return {
        "runtime": "unknown",
        "build_command": "",
        "start_command": "",
    }


def _find_existing_service(name: str, key: str) -> Optional[dict]:
    """Find an existing Render service by name."""
    try:
        result = _api("GET", f"/services?name={name}&limit=1", key)
        if isinstance(result, list) and result:
            return result[0].get("service", result[0])
        return None
    except RuntimeError:
        return None


def deploy_to_render(
    workspace: str,
    service_name: str = "",
    repo: str = "",
) -> dict:
    """Deploy workspace to Render.

    Requires the code to be pushed to GitHub first.

    Args:
        workspace: Path to workspace directory
        service_name: Name for the Render service (auto-generated if empty)
        repo: GitHub repo in "owner/repo" format

    Returns:
        dict with status, service_id, url, and dashboard_url
    """
    key = _get_key()

    if not repo:
        raise ValueError("GitHub repo required. Push to GitHub first, then deploy to Render.")

    runtime = _detect_runtime(workspace)
    print(f"[RENDER] Detected runtime: {runtime}")

    if not service_name:
        # Generate from repo name
        service_name = repo.split("/")[-1] if "/" in repo else repo

    # Check for existing service
    existing = _find_existing_service(service_name, key)

    if existing:
        # Trigger a new deploy on existing service
        service_id = existing.get("id", "")
        print(f"[RENDER] Found existing service: {service_id}. Triggering deploy...")
        try:
            deploy = _api("POST", f"/services/{service_id}/deploys", key, {})
            return {
                "status": "deploying",
                "service_id": service_id,
                "deploy_id": deploy.get("id", ""),
                "url": existing.get("serviceDetails", {}).get("url", ""),
                "dashboard_url": f"https://dashboard.render.com/web/{service_id}",
                "action": "redeploy",
            }
        except RuntimeError as e:
            return {
                "status": "error",
                "message": f"Failed to trigger deploy: {e}",
                "service_id": service_id,
            }

    # Create new service — Render v1 API uses nested serviceDetails
    if runtime["runtime"] == "static":
        service_payload = {
            "type": "static_site",
            "name": service_name,
            "autoDeploy": "yes",
            "repo": f"https://github.com/{repo}",
            "branch": "main",
            "serviceDetails": {
                "buildCommand": runtime["build_command"] or "echo 'No build needed'",
                "publishPath": ".",
            },
        }
    else:
        rt = runtime["runtime"] if runtime["runtime"] in ("python", "node") else "python"
        service_payload = {
            "type": "web_service",
            "name": service_name,
            "autoDeploy": "yes",
            "repo": f"https://github.com/{repo}",
            "branch": "main",
            "serviceDetails": {
                "region": "singapore",
                "plan": "free",
                "runtime": rt,
                "buildCommand": runtime["build_command"],
                "startCommand": runtime["start_command"],
                "envSpecificDetails": {"envVarGroups": []},
            },
        }

    print(f"[RENDER] Creating service: {service_name}")
    try:
        result = _api("POST", "/services", key, service_payload)
        service = result.get("service", result)
        service_id = service.get("id", "")
        url = service.get("serviceDetails", {}).get("url", "")
        return {
            "status": "created",
            "service_id": service_id,
            "url": url,
            "dashboard_url": f"https://dashboard.render.com/web/{service_id}",
            "runtime": runtime["runtime"],
            "action": "create",
        }
    except RuntimeError as e:
        return {
            "status": "error",
            "message": str(e),
        }
