"""LLM provider abstraction: OpenAI or a local Ollama server, selected
via the LLM_PROVIDER env var. Every other module calls only pick_url()
and extract_staff() and never branches on provider itself."""
import json
import logging
import os

import requests
from openai import OpenAI

logger = logging.getLogger(__name__)

_VALID_PROVIDERS = {"openai", "ollama"}
OPENAI_MODEL = "gpt-4.1-mini"
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "mistral-small3.1:24b")
OLLAMA_NUM_CTX = int(os.environ.get("OLLAMA_NUM_CTX", "24576"))

# Large staff directories (60-80+ people) easily produce cleaned page text
# well past 8000 characters; truncating there was silently dropping most of
# the roster before any LLM (OpenAI or Ollama) ever saw it. Keep this in
# sync with OLLAMA_NUM_CTX headroom if raised further.
_MAX_PAGE_TEXT_CHARS = int(os.environ.get("MAX_PAGE_TEXT_CHARS", "32000"))
# _MAX_PAGE_TEXT_CHARS = 32000

CATEGORIES = {"coach", "admin", "sports_medicine", "sports_info"}

_PICK_URL_PROMPTS = {
    "general_athletics": (
        "You identify the correct general athletics staff directory URL for "
        "a college from a list of search results. This should be a page "
        "listing multiple athletics department staff (coaches, athletic "
        "director, athletic trainers, sports information staff), not a "
        "single-sport roster or a news article. "
        'Respond ONLY with JSON: {"url": "...", "confidence": "high|medium|low", "notes": "..."}. '
        "If none of the results look like a staff directory, set url to null."
    ),
    "track_field": (
        "You identify the correct track & field/cross country coaching "
        "staff URL for a college from a list of search results. Prefer a "
        "page specific to track & field/cross country coaching staff. "
        'Respond ONLY with JSON: {"url": "...", "confidence": "high|medium|low", "notes": "..."}. '
        "If none of the results look like a staff directory, set url to null."
    ),
}

_EXTRACT_STAFF_SYSTEM_PROMPT = (
    "You extract athletics department staff listings from web page text. "
    "For each staff member found, classify them into exactly one of these "
    "categories: 'coach' (track & field or cross country coaching staff "
    "only — ignore coaches of other sports), 'admin' (athletic director, "
    "associate/assistant athletic director, compliance, business "
    "operations), 'sports_medicine' (athletic trainers, strength & "
    "conditioning coaches), 'sports_info' (sports information director, "
    "media relations, communications, marketing). If a staff member doesn't "
    "clearly fit one of these four categories, omit them entirely. "
    "Respond ONLY with a JSON array of objects, each with keys: "
    '"name", "title", "category", "sport" (empty string unless category is '
    '"coach"), "email" (empty string if not found), "phone" (empty string '
    'if not found), "bio_url" (empty string if no individual bio link is '
    "present). No commentary, no markdown fences."
)


class LLMError(Exception):
    """Raised when LLM_PROVIDER is set to an unrecognized value."""


def get_provider(override=None):
    """Return the active provider name ('openai' or 'ollama'): `override`
    if given, else the LLM_PROVIDER env var, defaulting to 'openai'.
    Raises LLMError if the resolved value isn't a known provider."""
    name = (override or os.environ.get("LLM_PROVIDER", "openai")).strip().lower()
    if name not in _VALID_PROVIDERS:
        raise LLMError(f"Unknown LLM_PROVIDER: {name!r} (expected 'openai' or 'ollama')")
    return name


def _strip_code_fence(raw):
    return raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()


def _repair_truncated_json(text):
    """Best-effort repair for JSON that got cut off mid-structure — observed
    with Ollama, which occasionally degenerates into emitting a long run of
    trailing whitespace instead of the closing bracket(s). Scans for any
    unclosed '{'/'[' (ignoring bracket-like characters inside strings) and
    appends the matching closers after trimming trailing whitespace. Returns
    None if the text isn't a simple case of missing closers (e.g. an
    unterminated string), so the caller can fall back to the original error."""
    stack = []
    in_string = False
    escape = False
    for ch in text:
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch in "{[":
            stack.append(ch)
        elif ch in "}]":
            if stack:
                stack.pop()
    if in_string or not stack:
        return None
    closing = {"{": "}", "[": "]"}
    return text.rstrip() + "".join(closing[b] for b in reversed(stack))


def _parse_llm_json(raw):
    """Parse `raw` (already stripped of code fences) as JSON, falling back
    to `_repair_truncated_json` if the model's output was cut off before a
    closing bracket. Raises json.JSONDecodeError if neither works."""
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        repaired = _repair_truncated_json(raw)
        if repaired is None:
            raise
        return json.loads(repaired)


def _call_openai(system, user):
    client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
    completion = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=0,
    )
    return completion.choices[0].message.content


def _call_ollama(system, user):
    host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
    resp = requests.post(
        f"{host}/api/chat",
        json={
            "model": OLLAMA_MODEL,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "stream": False,
            "format": "json",
            # Server default (-c 4096) is too small to hold a large staff-directory
            # prompt plus a full JSON listing in the output; without headroom the
            # response gets cut off mid-generation, producing invalid JSON.
            "options": {"num_ctx": OLLAMA_NUM_CTX,
                        "temperature": 0,
                        "seed": 42,
                        },
        },
        timeout=300,
    )
    resp.raise_for_status()
    return resp.json()["message"]["content"]


def _call_llm(system, user, provider):
    if provider == "openai":
        return _call_openai(system, user)
    return _call_ollama(system, user)


def pick_url(school_name, purpose, search_results, provider=None):
    """Ask the configured LLM to choose the best URL out of `search_results`
    (each a dict with 'url', 'title', 'content') for the given `purpose`
    ('general_athletics' or 'track_field'). Returns
    {"url": str|None, "confidence": "high|medium|low|none", "notes": str}."""
    if not search_results:
        return {"url": None, "confidence": "none", "notes": "no search results"}

    resolved_provider = get_provider(provider)
    system = _PICK_URL_PROMPTS[purpose]
    listing = "\n\n".join(
        f"[{i}] URL: {r['url']}\nTitle: {r.get('title', '')}\nSnippet: {r.get('content', '')[:300]}"
        for i, r in enumerate(search_results)
    )
    user = f"School: {school_name}\n\nSearch results:\n{listing}"

    raw = None
    try:
        raw = _call_llm(system, user, resolved_provider)
        result = json.loads(_strip_code_fence(raw))
        if not isinstance(result, dict) or "url" not in result:
            logger.warning(
                "pick_url(%r, %r): LLM response parsed but wrong shape: %r",
                school_name, purpose, raw,
            )
            return {"url": None, "confidence": "none", "notes": "LLM output not parseable"}
        confidence = result.get("confidence")
        if confidence not in {"high", "medium", "low", "none"}:
            confidence = "none"
        return {"url": result.get("url"), "confidence": confidence, "notes": result.get("notes") or ""}
    except (requests.RequestException, KeyError, ValueError, json.JSONDecodeError):
        logger.warning(
            "pick_url(%r, %r): LLM call/parse failed; raw response=%r",
            school_name, purpose, raw, exc_info=True,
        )
        return {"url": None, "confidence": "none", "notes": "LLM output not parseable"}


def extract_staff(school_name, page_text, source_url, provider=None):
    """Ask the configured LLM to extract categorized staff rows from
    already-cleaned `page_text`. Returns a list of dicts with keys name,
    title, category, sport, email, phone, bio_url. Rows the LLM can't
    place into a known category (see CATEGORIES) are dropped. Returns []
    for blank page_text or an unparseable LLM response."""
    if not page_text or not page_text.strip():
        return []

    resolved_provider = get_provider(provider)
    user = f"School: {school_name}\nSource URL: {source_url}\n\nPage text:\n{page_text[:_MAX_PAGE_TEXT_CHARS]}"

    raw = None
    try:
        raw = _call_llm(_EXTRACT_STAFF_SYSTEM_PROMPT, user, resolved_provider)
        rows = _parse_llm_json(_strip_code_fence(raw))
    except (requests.RequestException, KeyError, ValueError, json.JSONDecodeError):
        logger.warning(
            "extract_staff(%r, %r): LLM call/parse failed; raw response=%r",
            school_name, source_url, raw, exc_info=True,
        )
        return []

    if isinstance(rows, dict):
        if "name" in rows or "category" in rows:
            # When only one staff member is found, the model sometimes
            # returns a bare staff object instead of a one-item array.
            rows = [rows]
        else:
            # Despite being told to respond with a bare JSON array, the
            # model sometimes wraps it in an object (observed:
            # {"staff": [...]}). Unwrap if exactly one value is a list.
            list_values = [v for v in rows.values() if isinstance(v, list)]
            if len(list_values) == 1:
                rows = list_values[0]

    if not isinstance(rows, list):
        logger.warning(
            "extract_staff(%r, %r): LLM response parsed but not a list: %r",
            school_name, source_url, rows,
        )
        return []

    out = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        category = row.get("category")
        if category not in CATEGORIES:
            continue
        out.append({
            "name": row.get("name") or "",
            "title": row.get("title") or "",
            "category": category,
            "sport": (row.get("sport") or "") if category == "coach" else "",
            "email": row.get("email") or "",
            "phone": row.get("phone") or "",
            "bio_url": row.get("bio_url") or "",
        })
    return out
