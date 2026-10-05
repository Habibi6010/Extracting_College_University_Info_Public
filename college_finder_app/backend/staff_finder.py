# college_finder_app/backend/staff_finder.py
"""Orchestrates the per-school athletics staff lookup pipeline: find the
general athletics + track & field staff directory URLs (Tavily search +
LLM pick, Wikipedia as fallback), extract each page's staff (Tavily
/extract, falling back to a plain fetch + tag-strip if Tavily itself
fails), de-dupe, and fill in missing emails from individual bio pages."""
import html
import logging
import os
import re
from urllib.parse import urljoin, urlparse

import requests

from backend import llm_provider, tavily_client, wikipedia_lookup

logger = logging.getLogger(__name__)

_GENERAL_QUERY = "{school} athletics staff directory"
_TRACK_FIELD_QUERY = "{school} track and field cross country coaching staff directory"
_EMAIL_RE = re.compile(r"[\w.!#$%&'*+/=?^`{|}~-]+@[\w.-]+\.[A-Za-z]{2,}")
_MAILTO_RE = re.compile(r"mailto:([^\"'?#>\s]+)", re.IGNORECASE)
_SIDEARM_ROW_RE = re.compile(
    r"<tr\b[^>]*class=[\"'][^\"']*sidearm-staff-member[^\"']*[\"'][^>]*>.*?</tr>",
    re.IGNORECASE | re.DOTALL,
)
_FIRST_SECOND_EMAIL_RE = re.compile(
    r"(?:var|let|const)\s+firstHalf\s*=\s*[\"']([^\"']+)[\"'];.*?"
    r"(?:var|let|const)\s+secondHalf\s*=\s*[\"']([^\"']+)[\"']",
    re.IGNORECASE | re.DOTALL,
)
_TAG_RE = re.compile(r"<[^>]+>")
_SCRIPT_STYLE_RE = re.compile(r"<(script|style)\b.*?</\1\s*>", re.IGNORECASE | re.DOTALL)


def find_staff_for_school(school_name, state, tavily_key, llm_provider_name=None):
    """Run the full staff-lookup pipeline for one school. Returns
    {"school_name": school_name, "state": state, "staff": [rows]}. Never
    raises: any step failure produces a single row with category='error'
    and a 'notes' field explaining why."""
    try:
        staff = _run_pipeline(school_name, tavily_key, llm_provider_name)
    except Exception as exc:
        logger.exception("Staff lookup failed for %s", school_name)
        notes = str(exc)
        if tavily_key:
            notes = notes.replace(tavily_key, "***")
        openai_key = os.environ.get("OPENAI_API_KEY")
        if openai_key:
            notes = notes.replace(openai_key, "***")
        staff = [_error_row(notes)]
    return {"school_name": school_name, "state": state, "staff": staff}


def _error_row(notes):
    return {
        "name": "", "title": "", "category": "error", "sport": "",
        "email": "", "phone": "", "source_url": "", "bio_url": "", "notes": notes,
    }


def _run_pipeline(school_name, tavily_key, llm_provider_name):
    general_url, _ = _find_url(school_name, "general_athletics", _GENERAL_QUERY, tavily_key, llm_provider_name)
    track_field_url, track_field_confirmed = _find_url(
        school_name, "track_field", _TRACK_FIELD_QUERY, tavily_key, llm_provider_name
    )

    rows = []
    if general_url:
        rows += _extract_from_url(school_name, general_url, tavily_key, llm_provider_name, force_category=None)
    if track_field_url and track_field_url != general_url:
        # Only force every row on this page to "coach" when the URL is a
        # confident, purpose-specific match from Tavily/the LLM — a
        # Wikipedia fallback link is a generic staff/roster match and may
        # not be track-field-specific at all, so trust extract_staff's own
        # per-row classification for it instead (same as the general page).
        force = "coach" if track_field_confirmed else None
        rows += _extract_from_url(school_name, track_field_url, tavily_key, llm_provider_name, force_category=force)

    rows = _dedupe(rows)
    return [_fill_missing_email(row, school_name, tavily_key, llm_provider_name) for row in rows]


def _find_url(school_name, purpose, query_template, tavily_key, llm_provider_name):
    """Returns (url, confirmed). confirmed is True only when the LLM
    confidently picked url from Tavily's own search results for this
    purpose; False when it came from the generic Wikipedia fallback
    (which is not purpose-specific and should not drive forced tagging) —
    used both when Tavily finds nothing and when the Tavily search call
    itself fails (e.g. credits exhausted, outage)."""
    try:
        results = tavily_client.search(query_template.format(school=school_name), tavily_key)
    except requests.RequestException as exc:
        logger.warning(
            "Tavily search failed for %s (%s); falling back to Wikipedia: %s",
            school_name, purpose, exc,
        )
        return wikipedia_lookup.find_staff_link(school_name), False

    picked = llm_provider.pick_url(school_name, purpose, results, provider=llm_provider_name)
    if picked.get("url"):
        return picked["url"], True
    return wikipedia_lookup.find_staff_link(school_name), False


def _extract_page_text(url, tavily_key):
    """Fetch cleaned text for `url`: Tavily's /extract first, falling back
    to a plain fetch + tag-strip if Tavily itself fails (outage, exhausted
    credits). The fallback is lower quality (keeps nav/footer boilerplate
    Tavily would normally strip) but keeps the pipeline working. Returns
    '' if both fail."""
    try:
        return tavily_client.extract(url, tavily_key)
    except requests.RequestException as exc:
        logger.warning("Tavily extract failed for %s; falling back to direct fetch: %s", url, exc)

    try:
        return _fallback_page_text(url)
    except requests.RequestException as exc:
        logger.warning("Fallback direct fetch also failed for %s: %s", url, exc)
        return ""


def _fallback_page_text(url, timeout=20):
    resp = requests.get(url, headers={"User-Agent": "CollegeFinderApp/1.0"}, timeout=timeout)
    resp.raise_for_status()
    text = _SCRIPT_STYLE_RE.sub(" ", resp.text)
    text = _TAG_RE.sub(" ", text)
    text = html.unescape(text)
    return " ".join(text.split())


def _extract_from_url(school_name, url, tavily_key, llm_provider_name, force_category):
    page_text = _extract_page_text(url, tavily_key)
    rows = llm_provider.extract_staff(school_name, page_text, url, provider=llm_provider_name)
    source_staff_by_name = _staff_map_from_source_page(url) if rows else {}
    out = []
    for row in rows:
        source_staff = source_staff_by_name.get(_name_key(row.get("name", "")), {})
        row = dict(row, source_url=url)
        row["bio_url"] = source_staff.get("bio_url") or _normalize_url(row.get("bio_url", ""), url) or ""
        if not row.get("email"):
            row["email"] = source_staff.get("email", "")
        if not row.get("phone"):
            row["phone"] = source_staff.get("phone", "")
        if force_category:
            row["category"] = force_category
        out.append(row)
    return out


def _dedupe(rows):
    by_name = {}
    for row in rows:
        key = row["name"].strip().lower()
        if not key:
            continue
        existing = by_name.get(key)
        if existing is None:
            by_name[key] = row
            continue
        merged = dict(existing)
        # A row categorized "coach" (i.e. force-tagged from the track & field
        # page) always wins the category/sport/source, regardless of which
        # side has the email — that tag is the one thing the two-URL design
        # guarantees is correct.
        if row.get("category") == "coach":
            merged["category"] = "coach"
            merged["sport"] = row.get("sport") or merged.get("sport", "")
            merged["source_url"] = row.get("source_url", merged.get("source_url", ""))
        if not merged.get("email") and row.get("email"):
            merged["email"] = row["email"]
        if not merged.get("bio_url") and row.get("bio_url"):
            merged["bio_url"] = row["bio_url"]
        by_name[key] = merged
    return list(by_name.values())


def _fill_missing_email(row, school_name, tavily_key, llm_provider_name):
    if row.get("email") or not row.get("bio_url"):
        return row

    bio_url = _normalize_url(row["bio_url"], row.get("source_url", ""))
    if not bio_url:
        logger.warning("Skipping invalid bio URL for %s: %r", row.get("name", ""), row.get("bio_url"))
        return row

    bio_text = _extract_page_text(bio_url, tavily_key)
    if not bio_text:
        return row

    bio_rows = llm_provider.extract_staff(school_name, bio_text, bio_url, provider=llm_provider_name)
    target_name = row["name"].strip().lower()
    for bio_row in bio_rows:
        if bio_row.get("email") and bio_row.get("name", "").strip().lower() == target_name:
            return dict(row, email=bio_row["email"])
    return row


def _normalize_url(url, base_url=""):
    url = str(url).strip()
    if not url:
        return None
    absolute_url = urljoin(base_url, url)
    parsed = urlparse(absolute_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return absolute_url


def _staff_map_from_source_page(url):
    try:
        resp = requests.get(url, headers={"User-Agent": "CollegeFinderApp/1.0"}, timeout=20)
        resp.raise_for_status()
    except requests.RequestException as exc:
        logger.warning("Source page staff scan failed for %s: %s", url, exc)
        return {}
    return _extract_staff_map(resp.text, url)


def _extract_staff_map(page_html, source_url=""):
    staff_by_name = {}
    for block in _SIDEARM_ROW_RE.findall(page_html):
        name = _extract_sidearm_name(block)
        if name:
            staff_by_name[_name_key(name)] = {
                "email": _extract_email(block),
                "bio_url": _extract_sidearm_bio_url(block, source_url),
                "phone": _extract_phone(block),
            }
    return staff_by_name


def _extract_sidearm_name(block):
    match = re.search(
        r"<td\b[^>]*headers=[\"'][^\"']*col-fullname[^\"']*[\"'][^>]*>(.*?)</td>",
        block,
        re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return ""
    text = html.unescape(_TAG_RE.sub(" ", match.group(1)))
    return " ".join(text.split())


def _extract_sidearm_bio_url(block, source_url):
    cell = _extract_sidearm_cell(block, "col-fullname")
    href = re.search(r"\bhref=[\"']([^\"']+)[\"']", cell, re.IGNORECASE)
    if not href:
        return ""
    return _normalize_url(html.unescape(href.group(1)), source_url) or ""


def _extract_email(block):
    mailto = _MAILTO_RE.search(block)
    if mailto:
        return html.unescape(mailto.group(1))

    js_parts = _FIRST_SECOND_EMAIL_RE.search(block)
    if js_parts:
        return f"{html.unescape(js_parts.group(1))}@{html.unescape(js_parts.group(2))}"

    email_match = _EMAIL_RE.search(html.unescape(block))
    return email_match.group(0) if email_match else ""


def _extract_phone(block):
    cell = _extract_sidearm_cell(block, "col-staff_phone")
    tel = re.search(r"\bhref=[\"']tel:([^\"']+)[\"']", cell, re.IGNORECASE)
    if tel:
        return html.unescape(tel.group(1))
    text = html.unescape(_TAG_RE.sub(" ", cell))
    return " ".join(text.split())


def _extract_sidearm_cell(block, header):
    match = re.search(
        rf"<td\b[^>]*headers=[\"'][^\"']*{re.escape(header)}[^\"']*[\"'][^>]*>(.*?)</td>",
        block,
        re.IGNORECASE | re.DOTALL,
    )
    return match.group(1) if match else ""


def _name_key(name):
    return " ".join(str(name).strip().lower().split())
