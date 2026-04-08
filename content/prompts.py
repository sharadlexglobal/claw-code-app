"""Custom prompt CRUD — per persona x per content type drafts."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .models import PromptDraft, PromptRecord

PROMPTS_DIR = Path(".claw/prompts")


def _prompt_path(persona_id: str, content_type: str) -> Path:
    return PROMPTS_DIR / persona_id / content_type / "prompt.json"


def _load_record(persona_id: str, content_type: str) -> Optional[PromptRecord]:
    p = _prompt_path(persona_id, content_type)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text())
        return PromptRecord(**data)
    except Exception:
        return None


def _save_record(record: PromptRecord) -> None:
    p = _prompt_path(record.persona_id, record.content_type)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(record.model_dump(), indent=2))


def list_prompts(persona_id: Optional[str] = None) -> list[PromptRecord]:
    """List all custom prompt records, optionally filtered by persona."""
    records: list[PromptRecord] = []
    if not PROMPTS_DIR.exists():
        return records
    for prompt_file in PROMPTS_DIR.glob("*/*/prompt.json"):
        try:
            data = json.loads(prompt_file.read_text())
            rec = PromptRecord(**data)
            if persona_id and rec.persona_id != persona_id:
                continue
            records.append(rec)
        except Exception:
            continue
    return records


def get_prompt(persona_id: str, content_type: str) -> Optional[PromptRecord]:
    """Get a specific prompt record with all drafts."""
    return _load_record(persona_id, content_type)


def get_active_prompt_text(persona_id: str, content_type: str) -> Optional[str]:
    """Return the active draft's prompt text, or None if no active custom prompt."""
    record = _load_record(persona_id, content_type)
    if not record or not record.active_draft_id:
        return None
    for draft in record.drafts:
        if draft.draft_id == record.active_draft_id and draft.is_active:
            return draft.prompt_text
    return None


def create_prompt_draft(
    persona_id: str, content_type: str, prompt_text: str
) -> PromptDraft:
    """Create a new draft for a persona/content_type slot."""
    record = _load_record(persona_id, content_type)
    if not record:
        record = PromptRecord(persona_id=persona_id, content_type=content_type)

    draft = PromptDraft(
        draft_id=uuid.uuid4().hex[:12],
        prompt_text=prompt_text,
        created_at=datetime.now(timezone.utc).isoformat(),
        is_active=False,
    )
    record.drafts.append(draft)
    _save_record(record)
    return draft


def update_prompt_draft(
    persona_id: str,
    content_type: str,
    draft_id: str,
    prompt_text: Optional[str] = None,
    is_active: Optional[bool] = None,
) -> Optional[PromptDraft]:
    """Update a draft's text or activation status."""
    record = _load_record(persona_id, content_type)
    if not record:
        return None

    target: Optional[PromptDraft] = None
    for draft in record.drafts:
        if draft.draft_id == draft_id:
            target = draft
            break
    if not target:
        return None

    if prompt_text is not None:
        target.prompt_text = prompt_text

    if is_active is True:
        # Deactivate all others
        for d in record.drafts:
            d.is_active = False
        target.is_active = True
        record.active_draft_id = draft_id
    elif is_active is False:
        target.is_active = False
        if record.active_draft_id == draft_id:
            record.active_draft_id = None

    _save_record(record)
    return target


def delete_prompt_draft(
    persona_id: str, content_type: str, draft_id: str
) -> bool:
    """Delete a specific draft."""
    record = _load_record(persona_id, content_type)
    if not record:
        return False

    original_len = len(record.drafts)
    record.drafts = [d for d in record.drafts if d.draft_id != draft_id]
    if len(record.drafts) == original_len:
        return False

    if record.active_draft_id == draft_id:
        record.active_draft_id = None

    _save_record(record)
    return True


def set_test_output(
    persona_id: str, content_type: str, draft_id: str, output: str
) -> None:
    """Store the last test output for a draft."""
    record = _load_record(persona_id, content_type)
    if not record:
        return
    for draft in record.drafts:
        if draft.draft_id == draft_id:
            draft.test_output = output
            break
    _save_record(record)
