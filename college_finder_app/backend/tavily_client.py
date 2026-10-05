"""Tavily search + extract API client."""
import requests

TAVILY_SEARCH_URL = "https://api.tavily.com/search"
TAVILY_EXTRACT_URL = "https://api.tavily.com/extract"


def search(query, api_key, max_results=5, timeout=30):
    """POST a query to Tavily /search. Returns the 'results' list (each a
    dict with at least 'url', 'title', 'content'); an empty list if the
    response has no 'results' key. Raises requests.RequestException on a
    network/HTTP error."""
    resp = requests.post(
        TAVILY_SEARCH_URL,
        json={"api_key": api_key, "query": query, "search_depth": "basic", "max_results": max_results},
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.json().get("results", [])


def extract(url, api_key, timeout=30):
    """Fetch clean text content for a single URL via Tavily /extract.
    Returns the raw_content string, or '' if Tavily couldn't extract that
    URL. Raises requests.RequestException on a network/HTTP error."""
    resp = requests.post(
        TAVILY_EXTRACT_URL,
        json={"api_key": api_key, "urls": [url]},
        timeout=timeout,
    )
    resp.raise_for_status()
    data = resp.json()
    for result in data.get("results", []):
        if result.get("url") == url:
            return result.get("raw_content", "") or ""
    return ""
