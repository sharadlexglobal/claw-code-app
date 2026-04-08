"""Content Factory models, constants, and schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PERSONAS = {
    "barkha_gupta": {
        "name": "Barkha Gupta",
        "title": "District & Sessions Judge (Retd.)",
        "service": "Delhi Higher Judicial Services",
        "experience": "32 years",
        "tone": "Authoritative, warm, judicial wisdom, accessible language",
        "podcast": "OFF THE RECORD",
        "services": [
            "Mediation",
            "Arbitration",
            "Legal Consultation",
            "Evidence Strategy",
            "Draft Settlement",
            "Legal Strategy",
        ],
        "social_handle": None,
        "bio": (
            "Barkha Gupta is a retired District & Sessions Judge from Delhi Higher "
            "Judicial Services with 32 years of experience on the bench. She now offers "
            "mediation, arbitration, legal consultation, evidence strategy, draft "
            "settlement, and legal strategy services. Host of the podcast 'OFF THE RECORD'."
        ),
    },
    "sharad_bansal": {
        "name": "Sharad Bansal",
        "title": "Advocate, Delhi High Court",
        "service": "Independent Litigation Practice",
        "experience": "20+ years",
        "tone": "Strategic, confident, street-smart, Hindi-English mix acceptable",
        "podcast": None,
        "services": [
            "Criminal Litigation",
            "Bail Matters",
            "Trial Strategy",
            "High Court Appeals",
            "Legal Strategy",
        ],
        "social_handle": "@vaqalatbysharad",
        "bio": (
            "Sharad Bansal is an Advocate at the Delhi High Court with over 20 years of "
            "litigation experience. Criminal cases strategy and litigation is his forte. "
            "He has independently handled many high-profile cases and serves as a legal "
            "strategist. Follow on Instagram: @vaqalatbysharad."
        ),
    },
}

CONTENT_TYPES = [
    "instagram_post",
    "instagram_carousel",
    "instagram_reel_script",
    "linkedin_post",
    "x_twitter_thread",
    "blog_article",
    "quora_answer",
    "reddit_post",
    "google_business_update",
    "podcast_notes",
]

LEGAL_DOMAINS = [
    "criminal",
    "civil",
    "matrimonial_family",
    "bail",
    "ipr",
    "property",
    "consumer",
    "labour",
    "tax",
    "corporate",
    "constitutional",
    "arbitration",
    "cyber_crime",
    "cheque_bounce",
    "motor_accident",
    "environmental",
    "banking",
    "procedural_law",
    "evidence",
    "rera",
    "insolvency",
    "ndps",
    "pocso",
    "rti",
    "general",
]

# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class ContentGenerateRequest(BaseModel):
    persona_id: str
    raw_input: str
    legal_domain: str = "general"
    content_types: Optional[list[str]] = None  # None = all types
    model: Optional[str] = None


class ContentPiece(BaseModel):
    content_type: str
    title: str = ""
    body: str = ""
    hashtags: Optional[list[str]] = None
    cta: Optional[str] = None
    word_count: int = 0
    slides: Optional[list[str]] = None  # carousel slides


class ContentGenerateResponse(BaseModel):
    model_config = {"protected_namespaces": ()}

    content_id: str
    persona_id: str
    legal_domain: str
    topic: str
    created_at: str
    pieces: list[ContentPiece] = []
    model_used: str = ""
    usage: Optional[dict] = None


# ---------------------------------------------------------------------------
# Prompt models
# ---------------------------------------------------------------------------


class PromptDraft(BaseModel):
    draft_id: str
    prompt_text: str
    created_at: str
    is_active: bool = False
    test_output: Optional[str] = None


class PromptRecord(BaseModel):
    persona_id: str
    content_type: str
    drafts: list[PromptDraft] = []
    active_draft_id: Optional[str] = None


class PromptCreateRequest(BaseModel):
    persona_id: str
    content_type: str
    prompt_text: str


class PromptUpdateRequest(BaseModel):
    prompt_text: Optional[str] = None
    is_active: Optional[bool] = None


class PromptTestRequest(BaseModel):
    persona_id: str
    content_type: str
    draft_id: Optional[str] = None
    prompt_text: Optional[str] = None
    sample_input: str
    model: Optional[str] = None


class PromptTestResponse(BaseModel):
    model_config = {"protected_namespaces": ()}

    draft_id: Optional[str] = None
    output: str
    model_used: str = ""
    usage: Optional[dict] = None


# ---------------------------------------------------------------------------
# Library models
# ---------------------------------------------------------------------------


class LibraryItem(BaseModel):
    content_id: str
    persona_id: str
    legal_domain: str
    topic: str
    created_at: str
    content_types: list[str] = []
    r2_base_key: Optional[str] = None
    public_url: Optional[str] = None


class LibraryListResponse(BaseModel):
    items: list[LibraryItem] = []
    total: int = 0
    offset: int = 0
    limit: int = 20
