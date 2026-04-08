"""Content Library — local index + R2 storage."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .models import ContentGenerateResponse, LibraryItem, LibraryListResponse

INDEX_PATH = Path(".claw/library/index.json")
CACHE_DIR = Path(".claw/library")


def _load_index() -> list[dict]:
    if not INDEX_PATH.exists():
        return []
    try:
        return json.loads(INDEX_PATH.read_text())
    except Exception:
        return []


def _save_index(items: list[dict]) -> None:
    INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    INDEX_PATH.write_text(json.dumps(items, ensure_ascii=False, indent=2))


def add_to_library(response: ContentGenerateResponse) -> LibraryItem:
    """Add a generated content response to the library."""
    item = LibraryItem(
        content_id=response.content_id,
        persona_id=response.persona_id,
        legal_domain=response.legal_domain,
        topic=response.topic,
        created_at=response.created_at,
        content_types=[p.content_type for p in response.pieces],
    )

    # Save to local cache
    cache_path = CACHE_DIR / response.content_id / "content.json"
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        json.dumps(response.model_dump(), ensure_ascii=False, indent=2)
    )

    # Append to index
    index = _load_index()
    index.insert(0, item.model_dump())  # newest first
    _save_index(index)

    return item


def upload_to_r2(content_id: str) -> str:
    """Upload content to R2 and return the base public URL."""
    from .r2 import upload_json, upload_text, get_public_url

    content = get_library_content(content_id)
    if not content:
        raise ValueError(f"Content {content_id} not found in library.")

    date_str = content.created_at[:10]  # YYYY-MM-DD
    base_key = f"content/{content.persona_id}/{content.legal_domain}/{date_str}/{content_id}"

    # Upload metadata
    meta = {
        "content_id": content.content_id,
        "persona_id": content.persona_id,
        "legal_domain": content.legal_domain,
        "topic": content.topic,
        "created_at": content.created_at,
        "model_used": content.model_used,
        "content_types": [p.content_type for p in content.pieces],
    }
    upload_json(f"{base_key}/metadata.json", meta)

    # Upload each piece as markdown
    for piece in content.pieces:
        md_content = f"# {piece.title}\n\n{piece.body}"
        if piece.hashtags:
            md_content += f"\n\n---\n{' '.join(piece.hashtags)}"
        upload_text(f"{base_key}/{piece.content_type}.md", md_content)

    # Update index with R2 info
    public_url = get_public_url(base_key)
    index = _load_index()
    for item_data in index:
        if item_data.get("content_id") == content_id:
            item_data["r2_base_key"] = base_key
            item_data["public_url"] = public_url
            break
    _save_index(index)

    return public_url


def list_library(
    persona_id: Optional[str] = None,
    legal_domain: Optional[str] = None,
    search: Optional[str] = None,
    offset: int = 0,
    limit: int = 20,
) -> LibraryListResponse:
    """Browse library with optional filters."""
    index = _load_index()
    filtered = index

    if persona_id:
        filtered = [i for i in filtered if i.get("persona_id") == persona_id]
    if legal_domain:
        filtered = [i for i in filtered if i.get("legal_domain") == legal_domain]
    if search:
        q = search.lower()
        filtered = [i for i in filtered if q in (i.get("topic", "") + " " + i.get("legal_domain", "")).lower()]

    total = len(filtered)
    page = filtered[offset : offset + limit]
    items = [LibraryItem(**d) for d in page]

    return LibraryListResponse(items=items, total=total, offset=offset, limit=limit)


def get_library_item(content_id: str) -> Optional[LibraryItem]:
    """Get a single library item by content_id."""
    index = _load_index()
    for item_data in index:
        if item_data.get("content_id") == content_id:
            return LibraryItem(**item_data)
    return None


def get_library_content(content_id: str) -> Optional[ContentGenerateResponse]:
    """Get full generated content from local cache."""
    cache_path = CACHE_DIR / content_id / "content.json"
    if not cache_path.exists():
        return None
    try:
        data = json.loads(cache_path.read_text())
        return ContentGenerateResponse(**data)
    except Exception:
        return None


def delete_from_library(content_id: str) -> bool:
    """Delete from index, local cache, and R2."""
    index = _load_index()
    item_data = None
    for d in index:
        if d.get("content_id") == content_id:
            item_data = d
            break
    if not item_data:
        return False

    # Remove from index
    index = [d for d in index if d.get("content_id") != content_id]
    _save_index(index)

    # Delete local cache
    cache_dir = CACHE_DIR / content_id
    if cache_dir.exists():
        import shutil
        shutil.rmtree(cache_dir, ignore_errors=True)

    # Delete from R2 if uploaded
    r2_key = item_data.get("r2_base_key")
    if r2_key:
        try:
            from .r2 import delete_prefix
            delete_prefix(r2_key + "/")
        except Exception:
            pass  # R2 delete failure shouldn't block local delete

    return True
