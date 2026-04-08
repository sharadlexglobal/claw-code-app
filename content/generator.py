"""Content generation via LLM API (Orbit primary, code0.ai fallback)."""

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
        timeout=15.0,
    )


def _get_code0_client() -> Optional[OpenAI]:
    """Get code0.ai fallback client. Returns None if not configured."""
    settings = load_settings()
    api_key = settings.code0_api_key
    if not api_key:
        return None
    return OpenAI(
        base_url=settings.code0_base_url or "https://code0.ai/v1",
        api_key=api_key,
        timeout=90.0,
    )


def _llm_call(messages: list[dict], model: str, temperature: float = 0.7, max_tokens: int = 4096) -> tuple[str, str]:
    """Call LLM with provider strategy based on content_llm_provider setting.
    Modes: "auto" (Orbit→code0 fallback), "orbit" (Orbit only), "code0" (code0 only).
    Returns (output_text, model_used).
    """
    settings = load_settings()
    provider = settings.content_llm_provider or "auto"

    # code0-only mode — skip Orbit entirely
    if provider == "code0":
        code0 = _get_code0_client()
        if not code0:
            raise RuntimeError("code0.ai selected but API key not configured in Settings.")
        code0_model = settings.code0_default_model or "gemini-2.5-flash"
        print(f"[CONTENT] Using code0.ai directly ({code0_model})")
        resp = code0.chat.completions.create(
            model=code0_model, messages=messages,
            temperature=temperature, max_tokens=max_tokens,
        )
        return (resp.choices[0].message.content or "", f"code0:{code0_model}")

    # Try Orbit (for "auto" and "orbit" modes)
    orbit_key = os.environ.get("ORBIT_API_KEY", "")
    if orbit_key:
        try:
            client = _get_orbit_client()
            resp = client.chat.completions.create(
                model=model, messages=messages,
                temperature=temperature, max_tokens=max_tokens,
            )
            return (resp.choices[0].message.content or "", model)
        except Exception as e:
            print(f"[CONTENT] Orbit failed ({model}): {e}")
            if provider == "orbit":
                raise RuntimeError(f"Orbit failed and provider set to orbit-only: {e}")

    # Fallback to code0.ai (auto mode)
    code0 = _get_code0_client()
    if code0:
        code0_model = settings.code0_default_model or "gemini-2.5-flash"
        try:
            print(f"[CONTENT] Falling back to code0.ai ({code0_model})")
            resp = code0.chat.completions.create(
                model=code0_model, messages=messages,
                temperature=temperature, max_tokens=max_tokens,
            )
            return (resp.choices[0].message.content or "", f"code0:{code0_model}")
        except Exception as e2:
            print(f"[CONTENT] code0.ai also failed ({code0_model}): {e2}")
            raise RuntimeError(f"All LLM providers failed. code0.ai: {e2}")

    raise RuntimeError("No LLM provider configured. Set ORBIT_API_KEY or code0.ai API key in Settings.")


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

    # Check for active custom prompt
    custom_prompt = get_active_prompt_text(persona_id, content_type)
    system_prompt = build_full_prompt(persona_id, content_type, custom_prompt)

    # Auto-apply relevant skills
    skill_block = get_skill_instructions(content_type)
    if skill_block:
        system_prompt += skill_block

    user_msg = f"Legal Domain: {legal_domain.replace('_', ' ').title()}\n\nRaw Input:\n{raw_input}"

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_msg},
    ]

    raw_output, _model_used = _llm_call(messages, model)
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
    model_req = model or settings.default_model

    system_prompt = build_full_prompt(persona_id, content_type, prompt_text)
    user_msg = f"Raw Input:\n{sample_input}"

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_msg},
    ]

    output, model_used = _llm_call(messages, model_req)

    return PromptTestResponse(
        output=output,
        model_used=model_used,
        usage=None,
    )
