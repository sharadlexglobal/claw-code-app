"""Settings management for Claw Code — persists config to disk."""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from typing import Optional

from pydantic import BaseModel

SETTINGS_PATH = Path(os.environ.get("CLAW_SETTINGS_PATH", ".claw/settings.json"))

# Simple XOR-based obfuscation key (not cryptographic — sufficient for single-user server)
_OBF_KEY = os.environ.get("CLAW_ENCRYPTION_KEY", "claw-code-obfuscation-key-2024")

SENSITIVE_FIELDS = {"github_token", "render_api_key", "r2_access_key", "r2_secret_key"}


class Settings(BaseModel):
    github_token: Optional[str] = None
    render_api_key: Optional[str] = None
    default_model: str = "claude-opus-4-6"
    fallback_model: str = "claude-sonnet-4-6"
    max_iterations: int = 10
    skills_directory: str = ".claw/skills"
    r2_account_id: Optional[str] = None
    r2_access_key: Optional[str] = None
    r2_secret_key: Optional[str] = None
    r2_bucket_name: Optional[str] = None
    r2_public_url: Optional[str] = None


class SettingsUpdate(BaseModel):
    github_token: Optional[str] = None
    render_api_key: Optional[str] = None
    default_model: Optional[str] = None
    fallback_model: Optional[str] = None
    max_iterations: Optional[int] = None
    skills_directory: Optional[str] = None
    r2_account_id: Optional[str] = None
    r2_access_key: Optional[str] = None
    r2_secret_key: Optional[str] = None
    r2_bucket_name: Optional[str] = None
    r2_public_url: Optional[str] = None


def _obfuscate(text: str) -> str:
    """Simple XOR + base64 obfuscation for stored tokens."""
    key_bytes = _OBF_KEY.encode()
    xored = bytes(b ^ key_bytes[i % len(key_bytes)] for i, b in enumerate(text.encode()))
    return base64.b64encode(xored).decode()


def _deobfuscate(encoded: str) -> str:
    """Reverse XOR + base64 obfuscation."""
    key_bytes = _OBF_KEY.encode()
    xored = base64.b64decode(encoded)
    return bytes(b ^ key_bytes[i % len(key_bytes)] for i, b in enumerate(xored)).decode()


def load_settings() -> Settings:
    """Load settings from disk. Returns defaults if file doesn't exist."""
    if not SETTINGS_PATH.exists():
        return Settings()
    try:
        raw = json.loads(SETTINGS_PATH.read_text())
        # Deobfuscate sensitive fields
        for field in SENSITIVE_FIELDS:
            if raw.get(field) and raw[field].startswith("obf:"):
                raw[field] = _deobfuscate(raw[field][4:])
        return Settings(**raw)
    except Exception as e:
        print(f"[SETTINGS] Error loading settings: {e}")
        return Settings()


def save_settings(settings: Settings) -> None:
    """Save settings to disk with obfuscated sensitive fields."""
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    raw = settings.model_dump()
    # Obfuscate sensitive fields
    for field in SENSITIVE_FIELDS:
        if raw.get(field):
            raw[field] = "obf:" + _obfuscate(raw[field])
    SETTINGS_PATH.write_text(json.dumps(raw, indent=2))


def mask_token(token: Optional[str]) -> Optional[str]:
    """Mask a token for display: show only last 4 chars."""
    if not token:
        return None
    if len(token) <= 4:
        return "****"
    return "****" + token[-4:]
