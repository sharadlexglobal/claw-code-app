"""Auto-apply relevant skills to content generation prompts.

Maps content types to skills and injects skill instructions into the
system prompt. Skills are loaded from .claw/skills/ directory.
"""

from __future__ import annotations

from agent.skills import list_skills, get_skill, render_skill

# Mapping: content_type -> list of skill names to auto-apply
CONTENT_SKILL_MAP: dict[str, list[str]] = {
    "instagram_post": ["hormozi-hooks", "feynman-legal", "indian-legal-authority"],
    "instagram_carousel": ["hormozi-hooks", "carousel-architect", "feynman-legal", "indian-legal-authority"],
    "instagram_reel_script": ["hormozi-hooks", "tts-script-clean", "feynman-legal", "indian-legal-authority"],
    "linkedin_post": ["hormozi-hooks", "feynman-legal", "indian-legal-authority"],
    "x_twitter_thread": ["hormozi-hooks", "feynman-legal", "indian-legal-authority"],
    "blog_article": ["feynman-legal", "indian-legal-authority"],
    "quora_answer": ["feynman-legal", "indian-legal-authority"],
    "reddit_post": ["feynman-legal", "indian-legal-authority"],
    "google_business_update": ["indian-legal-authority"],
    "podcast_notes": ["feynman-legal", "indian-legal-authority"],
}

# Skills that apply to ALL content types (the repurpose engine context)
UNIVERSAL_SKILLS = ["content-repurpose"]


def get_skill_instructions(content_type: str) -> str:
    """Build skill injection block for a content type.

    Returns a string containing all relevant skill instructions to be
    appended to the system prompt during content generation.
    """
    skill_names = CONTENT_SKILL_MAP.get(content_type, [])
    # Add universal skills
    all_skills = skill_names + UNIVERSAL_SKILLS

    injections = []
    for name in all_skills:
        skill = get_skill(name)
        if skill:
            rendered = render_skill(skill)
            injections.append(
                f"\n## SKILL: {skill.name.upper()}\n{rendered}"
            )

    if not injections:
        return ""

    return "\n\n# AUTO-APPLIED CONTENT SKILLS\n" + "\n".join(injections)


def list_applied_skills(content_type: str) -> list[str]:
    """Return list of skill names that would be applied for a content type."""
    skill_names = CONTENT_SKILL_MAP.get(content_type, []) + UNIVERSAL_SKILLS
    available = []
    for name in skill_names:
        skill = get_skill(name)
        if skill:
            available.append(name)
    return available
