"""Content generation via Orbit API (OpenAI-compatible)."""

from __future__ import annotations

import os
import re
import uuid
from datetime import datetime, timezone
from typing import Optional

from openai import OpenAI

from settings import load_settings
from .defaults import build_full_prompt
from .models import (
    CONTENT_TYPES,
    ContentGenerateResponse,
    ContentPiece,
    PromptTestResponse,
)
from .prompts import get_active_prompt_text
from .skill_injector import get_skill_instructions


def _get_orbit_client() -> OpenAI:
    return OpenAI(
        base_url=os.environ.get("ORBIT_BASE_URL", "https://api.orbit-provider.com/v1"),
        api_key=os.environ.get("ORBIT_API_KEY", ""),
    )


def _extract_topic(raw_input: str) -> str:
    """Extract a short topic from raw input (first 80 chars or first sentence)."""
    first_line = raw_input.strip().split("\n")[0]
    if len(first_line) <= 80:
        return first_line
    dot = first_line.find(".", 0, 80)
    if dot > 10:
        return first_line[: dot + 1]
    return first_line[:80] + "..."


def _parse_content_piece(content_type: str, raw_output: str) -> ContentPiece:
    """Parse raw LLM output into a structured ContentPiece."""
    body = raw_output.strip()
    title = ""
    hashtags: list[str] = []
    cta = None
    slides: Optional[list[str]] = None

    # Extract title (first # header or first line)
    lines = body.split("\n")
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("# "):
            title = stripped[2:].strip()
            break
        elif stripped.startswith("**") and stripped.endswith("**"):
            title = stripped.strip("* ")
            break
    if not title and lines:
        title = lines[0].strip()[:100]

    # Extract hashtags
    hashtag_pattern = re.compile(r"#\w+")
    found_tags = hashtag_pattern.findall(body)
    if found_tags:
        hashtags = list(dict.fromkeys(found_tags))  # dedupe, preserve order

    # Extract slides for carousel
    if content_type == "instagram_carousel":
        slide_pattern = re.compile(r"\[SLIDE\s*\d+\]", re.IGNORECASE)
        parts = slide_pattern.split(body)
        if len(parts) > 1:
            slides = [p.strip() for p in parts[1:] if p.strip()]

    # Word count
    word_count = len(body.split())

    return ContentPiece(
        content_type=content_type,
        title=title,
        body=body,
        hashtags=hashtags if hashtags else None,
        cta=cta,
        word_count=word_count,
        slides=slides,
    )


def generate_single(
    persona_id: str,
    content_type: str,
    raw_input: str,
    legal_domain: str = "general",
    model: Optional[str] = None,
) -> ContentPiece:
    """Generate a single content piece."""
    settings = load_settings()
    model = model or settings.default_model
    client = _get_orbit_client()

    # Check for active custom prompt
    custom_prompt = get_active_prompt_text(persona_id, content_type)
    system_prompt = build_full_prompt(persona_id, content_type, custom_prompt)

    # Auto-apply relevant skills
    skill_block = get_skill_instructions(content_type)
    if skill_block:
        system_prompt += skill_block

    user_msg = f"Legal Domain: {legal_domain.replace('_', ' ').title()}\n\nRaw Input:\n{raw_input}"

    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_msg},
        ],
        temperature=0.7,
        max_tokens=4096,
    )

    raw_output = resp.choices[0].message.content or ""
    return _parse_content_piece(content_type, raw_output)


def generate_all(
    persona_id: str,
    raw_input: str,
    legal_domain: str = "general",
    content_types: Optional[list[str]] = None,
    model: Optional[str] = None,
) -> ContentGenerateResponse:
    """Generate content for all (or selected) content types."""
    types_to_gen = content_types if content_types else CONTENT_TYPES
    settings = load_settings()
    model_used = model or settings.default_model
    content_id = uuid.uuid4().hex[:16]
    topic = _extract_topic(raw_input)

    pieces: list[ContentPiece] = []
    for ct in types_to_gen:
        if ct not in CONTENT_TYPES:
            continue
        try:
            piece = generate_single(persona_id, ct, raw_input, legal_domain, model_used)
            pieces.append(piece)
        except Exception as e:
            # Add error piece so caller knows what failed
            pieces.append(ContentPiece(
                content_type=ct,
                title=f"Error: {ct}",
                body=f"Generation failed: {e}",
                word_count=0,
            ))

    return ContentGenerateResponse(
        content_id=content_id,
        persona_id=persona_id,
        legal_domain=legal_domain,
        topic=topic,
        created_at=datetime.now(timezone.utc).isoformat(),
        pieces=pieces,
        model_used=model_used,
    )


def test_prompt(
    persona_id: str,
    content_type: str,
    prompt_text: str,
    sample_input: str,
    model: Optional[str] = None,
) -> PromptTestResponse:
    """Test a prompt without saving — returns raw LLM output."""
    settings = load_settings()
    model_used = model or settings.default_model
    client = _get_orbit_client()

    system_prompt = build_full_prompt(persona_id, content_type, prompt_text)
    user_msg = f"Raw Input:\n{sample_input}"

    resp = client.chat.completions.create(
        model=model_used,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_msg},
        ],
        temperature=0.7,
        max_tokens=4096,
    )

    output = resp.choices[0].message.content or ""
    usage = None
    if resp.usage:
        usage = {
            "prompt_tokens": resp.usage.prompt_tokens,
            "completion_tokens": resp.usage.completion_tokens,
            "total_tokens": resp.usage.total_tokens,
        }

    return PromptTestResponse(
        output=output,
        model_used=model_used,
        usage=usage,
    )
