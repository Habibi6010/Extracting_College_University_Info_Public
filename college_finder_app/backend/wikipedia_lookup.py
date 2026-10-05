"""Wikipedia fallback lookup for a school's athletics staff/roster link,
used when Tavily search doesn't turn up a confident directory URL, or
when the Tavily search call itself fails (e.g. credits exhausted)."""
import logging
import os

import requests

WIKIPEDIA_API_URL = "https://en.wikipedia.org/w/api.php"
DEFAULT_WIKIPEDIA_USER_AGENT = "CollegeFinderApp/1.0 (https://github.com/your-username/college-athletics-staff-finder)"
_LINK_KEYWORDS = ("staff", "coach", "roster", "directory")
logger = logging.getLogger(__name__)


def find_staff_link(school_name, timeout=15):
    """Look up the Wikipedia article for '{school_name} athletics', then
    scan its external links for one whose URL contains a staff/roster
    keyword. Returns the first matching URL, or None if no article is
    found, none of its external links match, or Wikipedia rejects/fails
    the fallback request."""
    try:
        title = _find_article_title(school_name, timeout)
    except (requests.RequestException, KeyError, ValueError) as exc:
        logger.warning("Wikipedia fallback lookup failed for %s: %s", school_name, exc)
        return None

    if not title:
        return None

    try:
        for link in _external_links(title, timeout):
            if any(kw in link.lower() for kw in _LINK_KEYWORDS):
                return link
    except (requests.RequestException, KeyError, ValueError) as exc:
        logger.warning("Wikipedia external-link lookup failed for %s: %s", title, exc)
    return None


def _headers():
    return {
        "Accept": "application/json",
        "User-Agent": os.environ.get("WIKIPEDIA_USER_AGENT", DEFAULT_WIKIPEDIA_USER_AGENT),
    }


def _find_article_title(school_name, timeout):
    resp = requests.get(
        WIKIPEDIA_API_URL,
        params={
            "action": "query",
            "list": "search",
            "srsearch": f"{school_name} athletics",
            "format": "json",
            "srlimit": 1,
        },
        headers=_headers(),
        timeout=timeout,
    )
    resp.raise_for_status()
    hits = resp.json().get("query", {}).get("search", [])
    return hits[0]["title"] if hits else None


def _external_links(title, timeout):
    resp = requests.get(
        WIKIPEDIA_API_URL,
        params={
            "action": "query",
            "prop": "extlinks",
            "titles": title,
            "format": "json",
            "ellimit": 500,
        },
        headers=_headers(),
        timeout=timeout,
    )
    resp.raise_for_status()
    pages = resp.json().get("query", {}).get("pages", {})
    links = []
    for page in pages.values():
        for entry in page.get("extlinks", []):
            url = entry.get("*")
            if url:
                links.append(url)
    return links
