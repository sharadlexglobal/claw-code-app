"""Skills system for Claw Code — SKILL.md based extensibility.

Skills are markdown files with YAML frontmatter that inject instructions
into the agent's system prompt. They enable reusable, customizable behaviors.

Storage: .claw/skills/<skill-name>/SKILL.md
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

SKILLS_DIR = Path(os.environ.get("CLAW_SKILLS_DIR", ".claw/skills"))


@dataclass
class Skill:
    name: str
    description: str = ""
    allowed_tools: List[str] = field(default_factory=list)
    disable_model_invocation: bool = False
    content: str = ""


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """Parse YAML-like frontmatter from SKILL.md content.

    Simple key: value parser — no PyYAML dependency needed.
    Supports: name, description, allowed-tools, disable-model-invocation
    """
    lines = text.strip().split("\n")
    if not lines or lines[0].strip() != "---":
        return {}, text

    end_idx = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end_idx = i
            break

    if end_idx is None:
        return {}, text

    meta = {}
    for line in lines[1:end_idx]:
        if ":" in line:
            key, val = line.split(":", 1)
            key = key.strip().lower()
            val = val.strip()
            # Remove surrounding quotes
            if val and val[0] in ('"', "'") and val[-1] == val[0]:
                val = val[1:-1]
            meta[key] = val

    body = "\n".join(lines[end_idx + 1:]).strip()
    return meta, body


def _skill_from_meta(name: str, meta: dict, body: str) -> Skill:
    """Build a Skill from parsed frontmatter and body."""
    allowed = meta.get("allowed-tools", "")
    allowed_list = [t.strip() for t in allowed.split() if t.strip()] if allowed else []

    disable = meta.get("disable-model-invocation", "false")
    disable_bool = disable.lower() in ("true", "yes", "1")

    return Skill(
        name=meta.get("name", name),
        description=meta.get("description", ""),
        allowed_tools=allowed_list,
        disable_model_invocation=disable_bool,
        content=body,
    )


def _ensure_skills_dir():
    """Create skills directory if it doesn't exist."""
    SKILLS_DIR.mkdir(parents=True, exist_ok=True)


def list_skills() -> List[Skill]:
    """List all available skills."""
    _ensure_skills_dir()
    skills = []

    for item in sorted(SKILLS_DIR.iterdir()):
        skill = None
        # Directory-based: .claw/skills/<name>/SKILL.md
        if item.is_dir():
            skill_file = item / "SKILL.md"
            if skill_file.exists():
                try:
                    text = skill_file.read_text(errors="replace")
                    meta, body = _parse_frontmatter(text)
                    skill = _skill_from_meta(item.name, meta, body)
                except Exception as e:
                    print(f"[SKILLS] Error parsing {skill_file}: {e}")
        # Flat-file: .claw/skills/<name>.md (legacy format)
        elif item.is_file() and item.suffix == ".md":
            try:
                text = item.read_text(errors="replace")
                meta, body = _parse_frontmatter(text)
                skill = _skill_from_meta(item.stem, meta, body)
            except Exception as e:
                print(f"[SKILLS] Error parsing {item}: {e}")

        if skill:
            skills.append(skill)

    return skills


def get_skill(name: str) -> Optional[Skill]:
    """Get a specific skill by name."""
    _ensure_skills_dir()

    # Try directory-based first
    skill_dir = SKILLS_DIR / name
    skill_file = skill_dir / "SKILL.md"
    if skill_file.exists():
        text = skill_file.read_text(errors="replace")
        meta, body = _parse_frontmatter(text)
        return _skill_from_meta(name, meta, body)

    # Try flat-file
    flat_file = SKILLS_DIR / f"{name}.md"
    if flat_file.exists():
        text = flat_file.read_text(errors="replace")
        meta, body = _parse_frontmatter(text)
        return _skill_from_meta(name, meta, body)

    return None


def create_skill(
    name: str,
    description: str = "",
    content: str = "",
    allowed_tools: Optional[List[str]] = None,
    disable_model_invocation: bool = False,
) -> Skill:
    """Create a new skill on disk."""
    _ensure_skills_dir()

    # Validate name
    if not re.match(r"^[a-z0-9][a-z0-9-]*$", name):
        raise ValueError("Skill name must be lowercase letters, numbers, and hyphens only")

    skill_dir = SKILLS_DIR / name
    if skill_dir.exists() or (SKILLS_DIR / f"{name}.md").exists():
        raise ValueError(f"Skill '{name}' already exists")

    skill_dir.mkdir(parents=True, exist_ok=True)

    # Build SKILL.md content
    frontmatter_lines = [
        "---",
        f"name: {name}",
        f"description: {description}",
    ]
    if allowed_tools:
        frontmatter_lines.append(f"allowed-tools: {' '.join(allowed_tools)}")
    if disable_model_invocation:
        frontmatter_lines.append("disable-model-invocation: true")
    frontmatter_lines.append("---")
    frontmatter_lines.append("")

    full_content = "\n".join(frontmatter_lines) + content
    (skill_dir / "SKILL.md").write_text(full_content)

    return Skill(
        name=name,
        description=description,
        allowed_tools=allowed_tools or [],
        disable_model_invocation=disable_model_invocation,
        content=content,
    )


def update_skill(
    name: str,
    description: Optional[str] = None,
    content: Optional[str] = None,
    allowed_tools: Optional[List[str]] = None,
    disable_model_invocation: Optional[bool] = None,
) -> Optional[Skill]:
    """Update an existing skill."""
    existing = get_skill(name)
    if not existing:
        return None

    new_desc = description if description is not None else existing.description
    new_content = content if content is not None else existing.content
    new_tools = allowed_tools if allowed_tools is not None else existing.allowed_tools
    new_disable = disable_model_invocation if disable_model_invocation is not None else existing.disable_model_invocation

    # Rebuild SKILL.md
    frontmatter_lines = [
        "---",
        f"name: {name}",
        f"description: {new_desc}",
    ]
    if new_tools:
        frontmatter_lines.append(f"allowed-tools: {' '.join(new_tools)}")
    if new_disable:
        frontmatter_lines.append("disable-model-invocation: true")
    frontmatter_lines.append("---")
    frontmatter_lines.append("")

    full_content = "\n".join(frontmatter_lines) + new_content

    # Write to directory-based path
    skill_dir = SKILLS_DIR / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(full_content)

    return Skill(
        name=name,
        description=new_desc,
        allowed_tools=new_tools,
        disable_model_invocation=new_disable,
        content=new_content,
    )


def delete_skill(name: str) -> bool:
    """Delete a skill from disk."""
    import shutil

    # Try directory-based
    skill_dir = SKILLS_DIR / name
    if skill_dir.is_dir():
        shutil.rmtree(skill_dir)
        return True

    # Try flat-file
    flat_file = SKILLS_DIR / f"{name}.md"
    if flat_file.exists():
        flat_file.unlink()
        return True

    return False


def find_matching_skills(message: str, skills: List[Skill]) -> List[Skill]:
    """Find skills whose description keywords match the user message.

    Returns skills sorted by match score (number of matching keywords).
    """
    lower_msg = message.lower()
    scored = []

    for skill in skills:
        if not skill.description:
            continue
        # Extract keywords from description (words > 3 chars)
        keywords = [w.strip(".,;:!?()") for w in skill.description.lower().split()]
        keywords = [w for w in keywords if len(w) > 3]
        matches = sum(1 for kw in keywords if kw in lower_msg)
        if matches > 0:
            scored.append((matches, skill))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [s for _, s in scored]


def render_skill(skill: Skill, arguments: str = "") -> str:
    """Render a skill's content with $ARGUMENTS substitution."""
    content = skill.content
    content = content.replace("$ARGUMENTS", arguments)
    return content
