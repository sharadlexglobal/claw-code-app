"""Agent loop — the nervous system of Claw Code.

Uses prompt-based tool calling for maximum compatibility with any
OpenAI-compatible provider (including Orbit).

Flow: User message → Claude thinks → outputs <tool_call> → we parse & execute → feed result → loop
"""

from __future__ import annotations

import json
import os
import re
import uuid
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional

from openai import OpenAI

from .tools import TOOL_SCHEMAS, execute_tool, WORKSPACE_ROOT

# ── Config ───────────────────────────────────────────────────────────────────

ORBIT_BASE_URL = os.environ.get("ORBIT_BASE_URL", "https://api.orbit-provider.com/v1")
ORBIT_API_KEY = os.environ.get("ORBIT_API_KEY", "")
DEFAULT_MODEL = os.environ.get("ORBIT_MODEL", "claude-opus-4-6")
FALLBACK_MODEL = os.environ.get("ORBIT_FALLBACK_MODEL", "claude-sonnet-4-6")
MAX_ITERATIONS = int(os.environ.get("CLAW_MAX_ITERATIONS", "10"))
MAX_TOKENS = int(os.environ.get("CLAW_MAX_TOKENS", "16000"))

AGENT_SYSTEM_PROMPT = """You are Claw Code, an autonomous AI coding agent running in a sandboxed workspace.

# ABSOLUTE RULE — READ THIS FIRST

You can ONLY affect the world through tool calls. Text you write is JUST a message to the user — it creates NO files, runs NO commands, changes NOTHING.

If you want to create index.html, you MUST call write_file. Typing HTML code in your response does absolutely nothing. The code vanishes. The user sees text, not a website.

NEVER write code as text. NEVER use markdown code blocks to show code. ALWAYS use write_file to create files.

# How to Call Tools

Wrap each call in XML tags exactly like this:

<tool_call>{{"name": "write_file", "arguments": {{"file_path": "index.html", "content": "<html>...</html>"}}}}</tool_call>

You can make multiple tool calls in one response.

# Available Tools

1. write_file(file_path, content) — Create/overwrite a file
2. read_file(file_path) — Read a file
3. edit_file(file_path, old_string, new_string) — Edit part of a file
4. bash(command) — Run a shell command
5. list_directory(directory) — List files
6. search_files(pattern, directory) — Search file contents

# Strategy for Building Websites/Apps

IMPORTANT: Break large tasks into MULTIPLE tool calls across iterations. Do NOT try to write everything in one giant response.

For a website:
1. First call: write_file index.html with the HTML structure
2. Second call: write_file styles.css with the CSS
3. Third call: write_file script.js with the JavaScript
4. Fourth call: bash to verify files exist

Keep each file under 200 lines. Split large files into separate tool calls.

# Workspace: {workspace_root}

# Example

User: Create a landing page

I'll create the HTML file first.

<tool_call>{{"name": "write_file", "arguments": {{"file_path": "index.html", "content": "<!DOCTYPE html>\\n<html>\\n<head>\\n<title>Landing Page</title>\\n<link rel=\\"stylesheet\\" href=\\"styles.css\\">\\n</head>\\n<body>\\n<h1>Welcome</h1>\\n</body>\\n</html>"}}}}</tool_call>

Now the CSS:

<tool_call>{{"name": "write_file", "arguments": {{"file_path": "styles.css", "content": "body {{ background: #1a1a2e; color: white; }}\\nh1 {{ text-align: center; }}"}}}}</tool_call>
"""

# ── Parse Tool Calls from Text ───────────────────────────────────────────────

TOOL_CALL_PATTERN = re.compile(
    r'<tool_call>\s*(\{.*?\})\s*</tool_call>',
    re.DOTALL
)

TOOL_NAMES = {"read_file", "write_file", "edit_file", "bash", "list_directory", "search_files"}


def _extract_json_objects(text: str) -> list[dict]:
    """Extract all valid JSON objects from text using string-aware brace matching.

    Unlike naive brace counting, this skips over { and } inside JSON strings
    (e.g. CSS rules like ``body { margin: 0; }`` inside a "content" field).
    """
    objects = []
    i = 0
    while i < len(text):
        if text[i] == '{':
            depth = 0
            in_string = False
            escape_next = False
            start = i
            found = False
            for j in range(i, len(text)):
                ch = text[j]
                if escape_next:
                    escape_next = False
                    continue
                if ch == '\\' and in_string:
                    escape_next = True
                    continue
                if ch == '"' and not escape_next:
                    in_string = not in_string
                    continue
                if in_string:
                    continue
                # Outside any string — count braces
                if ch == '{':
                    depth += 1
                elif ch == '}':
                    depth -= 1
                    if depth == 0:
                        raw = text[start:j + 1]
                        try:
                            parsed = json.loads(raw)
                            if isinstance(parsed, dict):
                                objects.append(parsed)
                        except json.JSONDecodeError:
                            pass
                        i = j + 1
                        found = True
                        break
            if not found:
                i += 1
        else:
            i += 1
    return objects


def _extract_write_file_raw(text: str) -> list[dict]:
    """Extract write_file calls even when the content field has broken JSON
    (e.g. unescaped double-quotes from HTML attributes like href="...").

    Looks for the pattern: {"name": "write_file", "arguments": {"file_path": "X", "content": "..."}}
    and extracts the content by matching the closing "}} pattern rather than relying on json.loads.
    """
    calls = []
    # Match the preamble up to the opening quote of content
    pattern = re.compile(
        r'\{\s*"name"\s*:\s*"write_file"\s*,\s*"arguments"\s*:\s*\{\s*"file_path"\s*:\s*"([^"]+)"\s*,\s*"content"\s*:\s*"',
        re.DOTALL,
    )
    print(f"[AGENT][RAW] Searching for write_file patterns in {len(text)} chars of text")
    for match in pattern.finditer(text):
        file_path = match.group(1)
        content_start = match.end()  # right after the opening " of content value

        # Find the closing of the JSON object: look for "}} or " } }
        # Use a non-greedy approach: find the FIRST "}} that closes this object
        rest = text[content_start:]
        end = re.search(r'"\s*\}\s*\}', rest)
        if not end:
            print(f"[AGENT][RAW] Found write_file {file_path} but no closing pattern")
            continue
        raw_content = rest[:end.start()]
        print(f"[AGENT][RAW] Extracted write_file {file_path}: content_len={len(raw_content)}, starts_with={repr(raw_content[:80])}")

        # Unescape JSON string escapes
        content = raw_content.replace('\\n', '\n').replace('\\t', '\t').replace('\\\\"', '"').replace('\\\\', '\\')
        # Also handle \" that was just a single-level escape
        content = content.replace('\\"', '"')

        calls.append({
            "name": "write_file",
            "arguments": {"file_path": file_path, "content": content},
        })
    print(f"[AGENT][RAW] Total extracted: {len(calls)} write_file calls")
    return calls


def parse_tool_calls(text: str) -> list[dict]:
    """Extract tool calls from the assistant's response text.

    Tries multiple strategies:
    1. <tool_call> XML tags (ideal)
    2. Raw write_file extraction (handles broken JSON from unescaped HTML quotes)
    3. Any JSON object with "name" matching a known tool
    4. Markdown code blocks as write_file calls (last resort)
    """
    calls = []

    # Strategy 1: <tool_call> XML tags
    for match in TOOL_CALL_PATTERN.finditer(text):
        try:
            parsed = json.loads(match.group(1))
            if isinstance(parsed, dict) and parsed.get("name") in TOOL_NAMES:
                calls.append({
                    "name": parsed["name"],
                    "arguments": parsed.get("arguments", {}),
                })
        except json.JSONDecodeError:
            continue

    if calls:
        return calls

    # Strategy 2: Raw write_file extraction + JSON objects for other tools
    # First, grab write_file calls using the raw extractor (handles broken JSON)
    write_calls = _extract_write_file_raw(text)
    write_paths = {c["arguments"]["file_path"] for c in write_calls}

    # Then grab other tool calls via JSON parsing
    json_calls = []
    for obj in _extract_json_objects(text):
        name = obj.get("name", "")
        if name in TOOL_NAMES:
            arguments = obj.get("arguments", {})
            if not arguments:
                arguments = {k: v for k, v in obj.items() if k != "name"}
            # Skip write_file calls already captured by raw extractor
            if name == "write_file" and arguments.get("file_path") in write_paths:
                continue
            json_calls.append({"name": name, "arguments": arguments})

    combined = write_calls + json_calls
    if combined:
        if write_calls:
            print(f"[AGENT] Raw extractor found {len(write_calls)} write_file calls: {list(write_paths)}")
        return combined

    # Strategy 3: Extract markdown code blocks as write_file calls (last resort)
    calls = extract_code_blocks_as_tools(text)
    if calls:
        print(f"[AGENT] Fallback: extracted {len(calls)} code blocks as write_file calls")

    return calls


def strip_tool_calls(text: str) -> str:
    """Remove tool_call blocks from text to get the prose."""
    cleaned = TOOL_CALL_PATTERN.sub('', text)
    # Also strip raw JSON tool calls that the brace parser found
    for obj in _extract_json_objects(text):
        name = obj.get("name", "")
        if name in TOOL_NAMES and "arguments" in obj:
            raw = json.dumps(obj)
            # Try to remove the JSON from the prose
            cleaned = cleaned.replace(raw, '')
    return cleaned.strip()


CODE_BLOCK_PATTERN = re.compile(
    r'```(html?|css|javascript|js|python|py|typescript|ts)\s*\n(.*?)```',
    re.DOTALL | re.IGNORECASE
)

LANG_TO_EXT = {
    'html': '.html', 'htm': '.html',
    'css': '.css',
    'javascript': '.js', 'js': '.js',
    'python': '.py', 'py': '.py',
    'typescript': '.ts', 'ts': '.ts',
}

def extract_code_blocks_as_tools(text: str) -> list[dict]:
    """Last-resort: extract markdown code blocks and convert to write_file calls."""
    calls = []
    seen_exts = {}
    for match in CODE_BLOCK_PATTERN.finditer(text):
        lang = match.group(1).lower()
        content = match.group(2).strip()
        if len(content) < 50:  # Skip tiny snippets
            continue
        ext = LANG_TO_EXT.get(lang, f'.{lang}')
        # Generate filename
        count = seen_exts.get(ext, 0)
        if ext == '.html' and count == 0:
            fname = 'index.html'
        elif ext == '.css' and count == 0:
            fname = 'styles.css'
        elif ext == '.js' and count == 0:
            fname = 'script.js'
        else:
            fname = f'file{count}{ext}'
        seen_exts[ext] = count + 1
        calls.append({"name": "write_file", "arguments": {"file_path": fname, "content": content}})
    return calls


# ── Data Structures ──────────────────────────────────────────────────────────

@dataclass
class ToolCallRecord:
    name: str
    arguments: dict
    result: dict


@dataclass
class AgentTurn:
    role: str
    content: Optional[str] = None
    tool_calls: List[ToolCallRecord] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)


@dataclass
class AgentSession:
    session_id: str
    messages: List[dict] = field(default_factory=list)
    turns: List[AgentTurn] = field(default_factory=list)
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_iterations: int = 0
    workspace: str = ""

    def __post_init__(self):
        if not self.workspace:
            self.workspace = str(WORKSPACE_ROOT / self.session_id)
            os.makedirs(self.workspace, exist_ok=True)


# ── Session Store ────────────────────────────────────────────────────────────

_sessions: Dict[str, AgentSession] = {}


def get_or_create_session(session_id: Optional[str] = None) -> AgentSession:
    sid = session_id or str(uuid.uuid4())
    if sid not in _sessions:
        _sessions[sid] = AgentSession(session_id=sid)
    return _sessions[sid]


def get_session(session_id: str) -> Optional[AgentSession]:
    return _sessions.get(session_id)


def list_sessions() -> List[dict]:
    return [
        {
            "session_id": s.session_id,
            "turns": len(s.turns),
            "iterations": s.total_iterations,
            "tokens": s.total_input_tokens + s.total_output_tokens,
        }
        for s in _sessions.values()
    ]


def delete_session(session_id: str) -> bool:
    return _sessions.pop(session_id, None) is not None


# ── Design Agent ─────────────────────────────────────────────────────────────

DESIGN_SYSTEM_PROMPT = """You are a world-class UI/UX designer. Your ONLY job is to produce a detailed visual design specification when a user asks for a website, app, or any frontend project.

You do NOT write code. You do NOT create files. You produce a design document that a developer will follow exactly.

# What you output

For every request, output a structured design spec covering:

## 1. Color Palette
- Primary, secondary, accent colors (exact hex values)
- Background colors (gradients if appropriate — specify stops and direction)
- Text colors for headings, body, muted text
- Card/surface colors, border colors
- Hover/active state colors

## 2. Typography
- Font families (use Google Fonts — specify exact names)
- Heading sizes (h1 through h3, using clamp() for responsiveness)
- Body text size, line-height, letter-spacing
- Font weights for headings vs body vs labels

## 3. Layout & Spacing
- Overall page structure (sections, their order, purpose)
- Max-width for content containers
- Section padding, gaps between elements
- Grid/flex layout for cards or multi-column sections
- How it should look on mobile (stacking, smaller padding)

## 4. Component Design
For each UI component (hero, cards, buttons, nav, footer, forms, etc.):
- Border-radius values
- Shadow styles (box-shadow with exact values)
- Padding/margin
- Hover effects (transforms, color changes, transitions)
- Border styles if any

## 5. Visual Personality
- Overall mood (e.g. "luxury minimalism", "playful startup", "corporate trust")
- Any decorative elements (subtle patterns, gradients, icons style)
- Image treatment if applicable (rounded, overlays, aspect ratios)

# Rules

- Be SPECIFIC — give exact hex codes, exact pixel/rem values, exact font names. Never say "a nice blue" — say "#2563EB".
- Be OPINIONATED — make bold design choices. No generic Bootstrap-looking defaults.
- Think like a Dribbble/Behance top designer — modern, polished, with personality.
- Consider visual hierarchy, whitespace, contrast ratios.
- If the user provides a reference image, analyze it and match/improve upon that style.
- Keep the spec concise but complete — under 800 words.
- Output ONLY the design spec, no pleasantries.
"""

# Keywords that suggest a frontend/visual task (triggers design agent)
_DESIGN_KEYWORDS = {
    "website", "webpage", "web page", "landing page", "homepage", "portfolio",
    "dashboard", "app", "application", "ui", "interface", "page", "site",
    "html", "frontend", "front-end", "layout", "design", "styled",
    "beautiful", "modern", "sleek", "responsive", "animation",
}


def _needs_design(message: str) -> bool:
    """Check if the user's request is a frontend/visual task that benefits from design planning."""
    lower = message.lower()
    # Must contain at least one design keyword
    return any(kw in lower for kw in _DESIGN_KEYWORDS)


# ── Agent Loop ───────────────────────────────────────────────────────────────

def _get_client() -> OpenAI:
    if not ORBIT_API_KEY:
        raise RuntimeError("ORBIT_API_KEY not configured")
    return OpenAI(base_url=ORBIT_BASE_URL, api_key=ORBIT_API_KEY, timeout=80.0)


def _run_design_agent(client, model: str, user_content) -> str:
    """Run the Design Agent to produce a visual design spec.
    Returns the design spec text, or empty string on failure.
    """
    messages = [
        {"role": "system", "content": DESIGN_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]
    print("[DESIGN-AGENT] Running design agent...")
    try:
        response = client.chat.completions.create(model=model, messages=messages, max_tokens=4096)
        spec = response.choices[0].message.content or ""
        print(f"[DESIGN-AGENT] Design spec generated: {len(spec)} chars")
        return spec
    except Exception as e:
        if model != FALLBACK_MODEL:
            print(f"[DESIGN-AGENT] Primary model {model} failed: {e}. Falling back to {FALLBACK_MODEL}")
            try:
                response = client.chat.completions.create(model=FALLBACK_MODEL, messages=messages, max_tokens=4096)
                spec = response.choices[0].message.content or ""
                print(f"[DESIGN-AGENT] Fallback design spec generated: {len(spec)} chars")
                return spec
            except Exception as e2:
                print(f"[DESIGN-AGENT] Fallback also failed: {e2}")
                return ""
        print(f"[DESIGN-AGENT] Error: {e}")
        return ""


IMAGE_CONTENT_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp"}


def _build_user_content(message: str, attachments: Optional[List[dict]] = None):
    """Build a user message content block, optionally multimodal.

    For plain text returns a string.
    For messages with image attachments returns an OpenAI-compatible
    content array with text and image_url blocks.
    For text file attachments, appends file content to the message text.
    """
    if not attachments:
        return message

    text_parts = [message]
    image_blocks = []

    for att in attachments:
        ct = att.get("content_type", "")
        fname = att.get("filename", "file")
        data = att.get("data", "")

        if ct in IMAGE_CONTENT_TYPES:
            # Image — add as vision block
            image_blocks.append({
                "type": "image_url",
                "image_url": {"url": f"data:{ct};base64,{data}"},
            })
        else:
            # Text/code file — decode base64 and append to message
            try:
                import base64
                decoded = base64.b64decode(data).decode("utf-8", errors="replace")
            except Exception:
                decoded = data  # might already be plain text
            text_parts.append(f"\n\n--- Attached file: {fname} ---\n{decoded[:30000]}")

    combined_text = "\n".join(text_parts)

    if not image_blocks:
        # No images — just return enriched text
        return combined_text

    # Multimodal: text + images
    content = [{"type": "text", "text": combined_text}]
    content.extend(image_blocks)
    return content


def run_agent(
    session_id: Optional[str],
    user_message: str,
    model: Optional[str] = None,
    max_iterations: Optional[int] = None,
    attachments: Optional[List[dict]] = None,
) -> dict:
    """Run the agent loop. Parses tool_call blocks from the model's response."""

    client = _get_client()
    session = get_or_create_session(session_id)
    model = model or DEFAULT_MODEL
    max_iter = max_iterations or MAX_ITERATIONS

    workspace_path = session.workspace
    os.makedirs(workspace_path, exist_ok=True)

    # Override workspace root for tool execution
    import agent.tools as tools_mod
    tools_mod.WORKSPACE_ROOT = Path(workspace_path)

    system_prompt = AGENT_SYSTEM_PROMPT.format(workspace_root=workspace_path)

    # Add user message (with attachments if any)
    user_content = _build_user_content(user_message, attachments)

    # ── Design Agent Phase ──
    if _needs_design(user_message):
        design_spec = _run_design_agent(client, model, user_content)
        if design_spec:
            system_prompt += f"\n\n# DESIGN SPECIFICATION (from Design Agent — follow this EXACTLY)\n\n{design_spec}\n\nYou MUST follow the above design spec precisely. Use the exact colors, fonts, spacing, and component styles specified. Do NOT use generic defaults."

    session.messages.append({"role": "user", "content": user_content})
    session.turns.append(AgentTurn(role="user", content=user_message))

    iterations = 0
    all_tool_calls = []
    final_response = ""

    while iterations < max_iter:
        iterations += 1
        session.total_iterations += 1

        # Call the model (with fallback)
        api_messages = [{"role": "system", "content": system_prompt}, *session.messages]
        try:
            response = client.chat.completions.create(model=model, messages=api_messages, max_tokens=MAX_TOKENS)
        except Exception as e:
            if model != FALLBACK_MODEL:
                print(f"[AGENT] Primary model {model} failed: {e}. Falling back to {FALLBACK_MODEL}")
                try:
                    model = FALLBACK_MODEL
                    response = client.chat.completions.create(model=FALLBACK_MODEL, messages=api_messages, max_tokens=MAX_TOKENS)
                except Exception as e2:
                    return {
                        "session_id": session.session_id,
                        "error": f"API error (both models failed): {str(e2)}",
                        "iterations": iterations,
                        "tool_calls": all_tool_calls,
                    }
            else:
                return {
                    "session_id": session.session_id,
                    "error": f"API error: {str(e)}",
                    "iterations": iterations,
                    "tool_calls": all_tool_calls,
                }

        # Track usage
        if response.usage:
            session.total_input_tokens += response.usage.prompt_tokens or 0
            session.total_output_tokens += response.usage.completion_tokens or 0

        assistant_text = response.choices[0].message.content or ""

        # Parse tool calls from the response
        tool_calls = parse_tool_calls(assistant_text)
        prose = strip_tool_calls(assistant_text)

        # Add assistant message to history
        session.messages.append({"role": "assistant", "content": assistant_text})

        if not tool_calls:
            # No tool calls — agent is done
            final_response = prose or assistant_text
            session.turns.append(AgentTurn(role="assistant", content=final_response))
            break

        # Execute each tool call
        turn_records = []
        results_text = []

        for tc in tool_calls:
            result = execute_tool(tc["name"], tc["arguments"])

            record = ToolCallRecord(name=tc["name"], arguments=tc["arguments"], result=result)
            turn_records.append(record)
            all_tool_calls.append({
                "tool": tc["name"],
                "arguments": tc["arguments"],
                "result": result,
            })

            results_text.append(
                f'Tool `{tc["name"]}` result:\n```json\n{json.dumps(result, default=str, indent=2)}\n```'
            )

        session.turns.append(AgentTurn(role="assistant", content=prose, tool_calls=turn_records))

        # Feed results back to the model
        session.messages.append({
            "role": "user",
            "content": "Tool execution results:\n\n" + "\n\n".join(results_text) + "\n\nContinue with the task. If done, provide a final summary WITHOUT any tool_call blocks.",
        })

        final_response = prose

    return {
        "session_id": session.session_id,
        "response": final_response,
        "iterations": iterations,
        "tool_calls": all_tool_calls,
        "usage": {
            "input_tokens": session.total_input_tokens,
            "output_tokens": session.total_output_tokens,
        },
        "workspace": workspace_path,
    }


# ── Streaming Agent Loop ────────────────────────────────────────────────────

def run_agent_stream(
    session_id: Optional[str],
    user_message: str,
    model: Optional[str] = None,
    max_iterations: Optional[int] = None,
    attachments: Optional[List[dict]] = None,
) -> Generator[dict, None, None]:
    """Run the agent loop with streaming events."""

    client = _get_client()
    session = get_or_create_session(session_id)
    model = model or DEFAULT_MODEL
    max_iter = max_iterations or MAX_ITERATIONS

    workspace_path = session.workspace
    os.makedirs(workspace_path, exist_ok=True)

    import agent.tools as tools_mod
    tools_mod.WORKSPACE_ROOT = Path(workspace_path)

    system_prompt = AGENT_SYSTEM_PROMPT.format(workspace_root=workspace_path)

    user_content = _build_user_content(user_message, attachments)

    yield {"event": "session", "session_id": session.session_id, "workspace": workspace_path}

    # ── Design Agent Phase ──────────────────────────────────────────────────
    design_spec = ""
    if _needs_design(user_message):
        yield {"event": "design", "status": "running"}
        design_spec = _run_design_agent(client, model, user_content)
        if design_spec:
            yield {"event": "design", "status": "done", "spec": design_spec[:2000]}
            # Inject design spec into the coding agent's system prompt
            system_prompt += f"\n\n# DESIGN SPECIFICATION (from Design Agent — follow this EXACTLY)\n\n{design_spec}\n\nYou MUST follow the above design spec precisely. Use the exact colors, fonts, spacing, and component styles specified. Do NOT use generic defaults."
        else:
            yield {"event": "design", "status": "skipped"}

    session.messages.append({"role": "user", "content": user_content})

    iterations = 0
    while iterations < max_iter:
        iterations += 1
        session.total_iterations += 1

        yield {"event": "thinking", "iteration": iterations}

        api_messages = [{"role": "system", "content": system_prompt}, *session.messages]

        # Stream LLM response — collect tokens and send them to browser in chunks
        assistant_text = ""
        stream_error = None
        try:
            collected = []
            stream = client.chat.completions.create(model=model, messages=api_messages, max_tokens=MAX_TOKENS, stream=True)
            buffer = []
            for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    token = chunk.choices[0].delta.content
                    collected.append(token)
                    buffer.append(token)
                    # Flush buffer every ~20 chars for real-time streaming
                    if sum(len(t) for t in buffer) >= 20:
                        yield {"event": "stream", "content": "".join(buffer)}
                        buffer = []
            if buffer:
                yield {"event": "stream", "content": "".join(buffer)}
            assistant_text = "".join(collected)
        except Exception as e:
            stream_error = e

        # Fallback if primary model failed
        if stream_error:
            if model != FALLBACK_MODEL:
                print(f"[AGENT-STREAM] Primary model {model} failed: {stream_error}. Falling back to {FALLBACK_MODEL}")
                yield {"event": "text", "content": f"(Switching to fallback model {FALLBACK_MODEL}...)"}
                try:
                    collected = []
                    stream = client.chat.completions.create(model=FALLBACK_MODEL, messages=api_messages, max_tokens=MAX_TOKENS, stream=True)
                    buffer = []
                    for chunk in stream:
                        if chunk.choices and chunk.choices[0].delta.content:
                            token = chunk.choices[0].delta.content
                            collected.append(token)
                            buffer.append(token)
                            if sum(len(t) for t in buffer) >= 20:
                                yield {"event": "stream", "content": "".join(buffer)}
                                buffer = []
                    if buffer:
                        yield {"event": "stream", "content": "".join(buffer)}
                    assistant_text = "".join(collected)
                    model = FALLBACK_MODEL
                except Exception as e2:
                    yield {"event": "error", "message": f"Both models failed: {str(e2)}"}
                    return
            else:
                yield {"event": "error", "message": str(stream_error)}
                return
        tool_calls = parse_tool_calls(assistant_text)
        prose = strip_tool_calls(assistant_text)

        # Debug logging
        print(f"[AGENT] Iteration {iterations}: text={len(assistant_text)} chars, tool_calls={len(tool_calls)}, prose={len(prose)} chars")
        if tool_calls:
            for tc in tool_calls:
                print(f"[AGENT]   Tool: {tc['name']} args_keys={list(tc['arguments'].keys())}")
        else:
            print(f"[AGENT]   No tool calls found. Raw text (first 500): {assistant_text[:500]}")

        session.messages.append({"role": "assistant", "content": assistant_text})

        if prose:
            yield {"event": "text", "content": prose}

        if not tool_calls:
            # Check 1: Truncated tool call (model started JSON but hit token limit)
            has_truncated_tool = '"name": "write_file"' in assistant_text or '"name":"write_file"' in assistant_text
            # Check 2: Code dumped as markdown text
            has_code = '```' in assistant_text or '<html' in assistant_text.lower() or 'function ' in assistant_text or '<div' in assistant_text.lower() or 'body {' in assistant_text

            if has_truncated_tool and iterations <= 3:
                # Model tried to use tool calls but response was cut off by token limit
                print(f"[AGENT] Truncated tool call detected. Asking model to retry with smaller files.")
                session.messages.append({
                    "role": "user",
                    "content": "Your response was cut off — the write_file tool call was incomplete and could NOT be executed. No files were created.\n\n"
                    "The file content was TOO LONG for a single response. You MUST split it:\n"
                    "1. First, write index.html with JUST the HTML structure (link to external CSS)\n"
                    "2. Then write styles.css with the CSS\n"
                    "3. Then write script.js if needed\n\n"
                    "Keep each file UNDER 150 lines. Use <tool_call> tags. Start NOW with index.html.",
                })
                yield {"event": "text", "content": "(Response was cut off — retrying with smaller files...)"}
                continue

            elif has_code and len(assistant_text) > 500 and iterations <= 3:
                # Model wrote code as text — force it to use tools
                print(f"[AGENT] Code-as-text detected ({len(assistant_text)} chars). Forcing tool usage.")
                session.messages.append({
                    "role": "user",
                    "content": "STOP. You wrote code as text — that does NOTHING. No files were created. "
                    "You MUST use <tool_call> tags to create files. Here's exactly what to do:\n\n"
                    "1. Take the code you just wrote\n"
                    "2. Put it inside a write_file tool call:\n"
                    "<tool_call>{\"name\": \"write_file\", \"arguments\": {\"file_path\": \"index.html\", \"content\": \"YOUR HTML HERE\"}}</tool_call>\n\n"
                    "Do this NOW. Create the files using write_file tool calls. Keep each file under 150 lines.",
                })
                yield {"event": "text", "content": "(Auto-correcting: forcing agent to use tool calls...)"}
                continue

            yield {
                "event": "done",
                "iterations": iterations,
                "usage": {
                    "input_tokens": session.total_input_tokens,
                    "output_tokens": session.total_output_tokens,
                },
            }
            return

        results_text = []
        for tc in tool_calls:
            yield {"event": "tool_call", "tool": tc["name"], "arguments": tc["arguments"]}

            result = execute_tool(tc["name"], tc["arguments"])
            print(f"[AGENT]   Result: {tc['name']} -> status={result.get('status', result.get('error', 'unknown'))} file_path={result.get('file_path', 'N/A')}")

            yield {"event": "tool_result", "tool": tc["name"], "result": result}

            results_text.append(
                f'Tool `{tc["name"]}` result:\n```json\n{json.dumps(result, default=str, indent=2)}\n```'
            )

        session.messages.append({
            "role": "user",
            "content": "Tool execution results:\n\n" + "\n\n".join(results_text) + "\n\nContinue with the task. If done, provide a final summary WITHOUT any tool_call blocks.",
        })

    yield {"event": "max_iterations", "iterations": iterations}
