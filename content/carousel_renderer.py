"""Carousel PNG renderer — bridges Content Factory with Remotion.

Takes carousel slide text from LLM output, converts to structured
slide data, and calls Remotion to render PNGs.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

# Path to the Remotion renderer
REMOTION_DIR = Path(__file__).parent.parent / "remotion"
RENDER_SCRIPT = REMOTION_DIR / "render.mjs"
NODE_BIN = os.environ.get("NODE_PATH", "node")


def _find_node() -> str:
    """Find Node.js binary."""
    for candidate in [NODE_BIN, "node", "/usr/local/bin/node", "/usr/bin/node"]:
        try:
            result = subprocess.run(
                [candidate, "--version"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                return candidate
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
    raise RuntimeError("Node.js not found. Install Node.js to render carousel PNGs.")


def parse_carousel_to_slides(carousel_text: str) -> list[dict]:
    """Parse LLM carousel output ([SLIDE N] format) into structured slide data.

    The LLM outputs carousel text with markers like:
    [SLIDE 1]
    TYPE: PROVOCATION
    HEADLINE: ...
    BODY: ...

    This parses that into Remotion-compatible slide props.
    """
    slides = []

    # Split on [SLIDE N] markers
    slide_pattern = re.compile(r'\[SLIDE\s*(\d+)\]', re.IGNORECASE)
    parts = slide_pattern.split(carousel_text)

    # parts[0] is text before first slide, then alternating: number, content
    i = 1
    while i < len(parts) - 1:
        slide_num = int(parts[i])
        content = parts[i + 1].strip()
        i += 2

        slide = _parse_single_slide(content, slide_num)
        slides.append(slide)

    # If no [SLIDE] markers found, create a single provocation slide
    if not slides and carousel_text.strip():
        slides.append({
            "type": "provocation",
            "slideNumber": 1,
            "totalSlides": 1,
            "headline": carousel_text.strip()[:100],
        })

    # Set totalSlides
    total = len(slides)
    for s in slides:
        s["totalSlides"] = total

    return slides


def _parse_single_slide(content: str, slide_num: int) -> dict:
    """Parse a single slide's content into structured data."""
    lines = content.strip().split("\n")
    fields = {}

    # Extract key: value pairs
    for line in lines:
        line = line.strip()
        if not line:
            continue
        # Match patterns like "TYPE: PROVOCATION" or "HEADLINE: ..."
        match = re.match(r'^(TYPE|HEADLINE|HEADING|BODY|TAG|SUBTITLE|STATUTE|ACT|CITATION|NUMBER|NUMBER_CAPTION|MYTH|FACT|POINT\s*\d+|STEP\s*\d+|CTA|BRAND|TAGLINE)\s*:\s*(.+)', line, re.IGNORECASE)
        if match:
            key = match.group(1).strip().upper()
            value = match.group(2).strip()
            fields[key] = value
        elif not fields:
            # First non-empty line without a key — treat as body
            if "BODY" not in fields:
                fields["BODY"] = line

    # Determine slide type
    slide_type = fields.get("TYPE", "insight").lower().strip()
    type_map = {
        "provocation": "provocation",
        "context": "context",
        "statute": "statute",
        "insight": "insight",
        "data": "data",
        "contrast": "contrast",
        "synthesis": "synthesis",
        "action": "action",
        "brand": "brand",
    }
    resolved_type = type_map.get(slide_type, "insight")

    slide: dict = {
        "type": resolved_type,
        "slideNumber": slide_num,
        "totalSlides": 0,  # set later
    }

    # Map fields to slide props based on type
    if fields.get("HEADLINE") or fields.get("HEADING"):
        slide["headline"] = fields.get("HEADLINE") or fields.get("HEADING")
    if fields.get("SUBTITLE"):
        slide["subheadline"] = fields["SUBTITLE"]
    if fields.get("BODY"):
        slide["body"] = fields["BODY"]
    if fields.get("TAG"):
        slide["tag"] = fields["TAG"]
    if fields.get("STATUTE"):
        slide["statute"] = fields["STATUTE"]
    if fields.get("ACT"):
        slide["actName"] = fields["ACT"]
    if fields.get("CITATION"):
        slide["citation"] = fields["CITATION"]
    if fields.get("NUMBER"):
        slide["number"] = fields["NUMBER"]
    if fields.get("NUMBER_CAPTION"):
        slide["numberCaption"] = fields["NUMBER_CAPTION"]
    if fields.get("MYTH"):
        slide["myth"] = fields["MYTH"]
    if fields.get("FACT"):
        slide["fact"] = fields["FACT"]
    if fields.get("CTA"):
        slide["cta"] = fields["CTA"]

    # Collect POINT entries for synthesis
    points = []
    for key, val in sorted(fields.items()):
        if key.startswith("POINT"):
            points.append(val)
    if points:
        slide["points"] = points

    # Collect STEP entries for action
    steps = []
    for key, val in sorted(fields.items()):
        if key.startswith("STEP"):
            steps.append(val)
    if steps:
        slide["steps"] = steps

    return slide


def render_carousel(
    carousel_text: str,
    output_dir: Optional[str] = None,
) -> dict:
    """Render carousel text into PNG slides using Remotion.

    Args:
        carousel_text: LLM output with [SLIDE N] markers
        output_dir: Directory to save PNGs (auto-generated if None)

    Returns:
        dict with: total, rendered, outputDir, files[]
    """
    # Parse text into structured slides
    slides = parse_carousel_to_slides(carousel_text)
    if not slides:
        return {"total": 0, "rendered": 0, "outputDir": "", "files": [], "error": "No slides parsed"}

    # Create output directory
    if output_dir is None:
        output_dir = tempfile.mkdtemp(prefix="sulah-carousel-")
    else:
        Path(output_dir).mkdir(parents=True, exist_ok=True)

    # Find Node.js
    node = _find_node()

    # Prepare JSON props
    props_json = json.dumps({"slides": slides})

    # Call Remotion renderer
    print(f"[CAROUSEL] Rendering {len(slides)} slides to {output_dir}")
    try:
        result = subprocess.run(
            [node, str(RENDER_SCRIPT), props_json, output_dir],
            capture_output=True,
            text=True,
            timeout=300,  # 5 min max for all slides
            cwd=str(REMOTION_DIR),
        )

        # stderr has progress logs, stdout has JSON result
        if result.stderr:
            for line in result.stderr.strip().split("\n"):
                print(f"[CAROUSEL] {line}")

        if result.returncode != 0:
            return {
                "total": len(slides),
                "rendered": 0,
                "outputDir": output_dir,
                "files": [],
                "error": result.stderr or "Remotion render failed",
            }

        # Parse JSON result from stdout
        output = json.loads(result.stdout)
        return output

    except subprocess.TimeoutExpired:
        return {
            "total": len(slides),
            "rendered": 0,
            "outputDir": output_dir,
            "files": [],
            "error": "Render timed out after 5 minutes",
        }
    except json.JSONDecodeError:
        return {
            "total": len(slides),
            "rendered": 0,
            "outputDir": output_dir,
            "files": [],
            "error": f"Failed to parse Remotion output: {result.stdout[:200]}",
        }
    except Exception as e:
        return {
            "total": len(slides),
            "rendered": 0,
            "outputDir": output_dir,
            "files": [],
            "error": str(e),
        }
