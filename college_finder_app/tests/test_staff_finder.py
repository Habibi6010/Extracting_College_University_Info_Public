# college_finder_app/tests/test_staff_finder.py
import pytest
import requests

from backend import llm_provider, staff_finder, tavily_client, wikipedia_lookup


@pytest.fixture(autouse=True)
def disable_source_page_email_scan(monkeypatch):
    def fake_get(*a, **kw):
        raise requests.ConnectionError("source page HTML scan disabled in tests")

    monkeypatch.setattr(staff_finder.requests, "get", fake_get)


def test_find_staff_for_school_merges_general_and_track_field_rows(monkeypatch):
    monkeypatch.setattr(
        tavily_client, "search",
        lambda query, api_key, max_results=5, timeout=30: [{"url": "https://x", "title": "t", "content": "c"}],
    )

    def fake_pick_url(school_name, purpose, results, provider=None):
        if purpose == "general_athletics":
            return {"url": "https://general.example.com", "confidence": "high", "notes": ""}
        return {"url": "https://tf.example.com", "confidence": "high", "notes": ""}

    monkeypatch.setattr(llm_provider, "pick_url", fake_pick_url)
    monkeypatch.setattr(tavily_client, "extract", lambda url, api_key, timeout=30: f"text for {url}")

    def fake_extract_staff(school_name, page_text, source_url, provider=None):
        if "general" in source_url:
            return [{"name": "Alex AD", "title": "Athletic Director", "category": "admin",
                      "sport": "", "email": "alex@ex.edu", "phone": "", "bio_url": ""}]
        return [{"name": "Sam Coach", "title": "Head Coach", "category": "coach",
                  "sport": "track_field", "email": "", "phone": "", "bio_url": ""}]

    monkeypatch.setattr(llm_provider, "extract_staff", fake_extract_staff)

    result = staff_finder.find_staff_for_school("Example University", "TX", "tavily-key")

    assert result["school_name"] == "Example University"
    assert result["state"] == "TX"
    names = {row["name"] for row in result["staff"]}
    assert names == {"Alex AD", "Sam Coach"}
    coach_row = next(r for r in result["staff"] if r["name"] == "Sam Coach")
    assert coach_row["category"] == "coach"


def test_find_staff_for_school_falls_back_to_wikipedia_when_no_confident_url(monkeypatch):
    monkeypatch.setattr(tavily_client, "search", lambda *a, **kw: [])
    monkeypatch.setattr(llm_provider, "pick_url", lambda *a, **kw: {"url": None, "confidence": "none", "notes": ""})
    monkeypatch.setattr(wikipedia_lookup, "find_staff_link", lambda school_name: "https://wiki-found.example.com")
    monkeypatch.setattr(tavily_client, "extract", lambda url, api_key, timeout=30: "text")
    monkeypatch.setattr(llm_provider, "extract_staff", lambda *a, **kw: [
        {"name": "Wiki Found", "title": "Trainer", "category": "sports_medicine",
         "sport": "", "email": "", "phone": "", "bio_url": ""}
    ])

    result = staff_finder.find_staff_for_school("Small College", "TX", "tavily-key")
    assert [r["name"] for r in result["staff"]] == ["Wiki Found"]


def test_find_staff_for_school_falls_back_to_wikipedia_when_tavily_search_errors(monkeypatch):
    def raising_search(*a, **kw):
        raise requests.HTTPError("432 Client Error: usage limit exceeded")

    monkeypatch.setattr(tavily_client, "search", raising_search)
    monkeypatch.setattr(wikipedia_lookup, "find_staff_link", lambda school_name: "https://wiki-found.example.com")
    monkeypatch.setattr(tavily_client, "extract", lambda url, api_key, timeout=30: "text")
    monkeypatch.setattr(llm_provider, "extract_staff", lambda *a, **kw: [
        {"name": "Wiki Found", "title": "Trainer", "category": "sports_medicine",
         "sport": "", "email": "", "phone": "", "bio_url": ""}
    ])

    result = staff_finder.find_staff_for_school("Small College", "TX", "tavily-key")

    assert [r["name"] for r in result["staff"]] == ["Wiki Found"]


def test_find_staff_for_school_falls_back_to_direct_fetch_when_tavily_extract_errors(monkeypatch):
    monkeypatch.setattr(
        tavily_client, "search",
        lambda query, api_key, max_results=5, timeout=30: [{"url": "https://x", "title": "t", "content": "c"}],
    )
    monkeypatch.setattr(
        llm_provider, "pick_url",
        lambda school_name, purpose, results, provider=None: (
            {"url": "https://general.example.com", "confidence": "high", "notes": ""}
            if purpose == "general_athletics" else {"url": None, "confidence": "none", "notes": ""}
        ),
    )
    monkeypatch.setattr(wikipedia_lookup, "find_staff_link", lambda school_name: None)

    def raising_extract(url, api_key, timeout=30):
        raise requests.HTTPError("432 Client Error: usage limit exceeded")

    monkeypatch.setattr(tavily_client, "extract", raising_extract)

    class _HtmlResponse:
        text = (
            "<html><head><style>.x{color:red}</style></head><body>"
            "<script>var x=1;</script><p>Jane Trainer &amp; Co</p></body></html>"
        )

        def raise_for_status(self):
            pass

    monkeypatch.setattr(staff_finder.requests, "get", lambda *a, **kw: _HtmlResponse())

    captured = {}

    def fake_extract_staff(school_name, page_text, source_url, provider=None):
        captured["page_text"] = page_text
        return [{"name": "Jane Trainer", "title": "Athletic Trainer", "category": "sports_medicine",
                  "sport": "", "email": "jane@ex.edu", "phone": "", "bio_url": ""}]

    monkeypatch.setattr(llm_provider, "extract_staff", fake_extract_staff)

    result = staff_finder.find_staff_for_school("Example University", "TX", "tavily-key")

    assert [r["name"] for r in result["staff"]] == ["Jane Trainer"]
    # Script/style content must not leak into the text handed to the LLM,
    # and entities should be unescaped, same contract as Tavily's /extract.
    assert "var x=1" not in captured["page_text"]
    assert "color:red" not in captured["page_text"]
    assert "Jane Trainer & Co" in captured["page_text"]


def test_find_staff_for_school_dedupes_preferring_row_with_email(monkeypatch):
    monkeypatch.setattr(
        tavily_client, "search",
        lambda query, api_key, max_results=5, timeout=30: [{"url": "https://x", "title": "t", "content": "c"}],
    )
    monkeypatch.setattr(
        llm_provider, "pick_url",
        lambda school_name, purpose, results, provider=None: {
            "url": f"https://{purpose}.example.com", "confidence": "high", "notes": ""
        },
    )
    monkeypatch.setattr(tavily_client, "extract", lambda url, api_key, timeout=30: url)

    def fake_extract_staff(school_name, page_text, source_url, provider=None):
        if "general_athletics" in source_url:
            return [{"name": "Sam Coach", "title": "Coach", "category": "coach", "sport": "track_field",
                      "email": "", "phone": "", "bio_url": ""}]
        return [{"name": "Sam Coach", "title": "Head Coach", "category": "coach", "sport": "track_field",
                  "email": "sam@ex.edu", "phone": "", "bio_url": ""}]

    monkeypatch.setattr(llm_provider, "extract_staff", fake_extract_staff)

    result = staff_finder.find_staff_for_school("Example University", "TX", "tavily-key")
    assert len(result["staff"]) == 1
    assert result["staff"][0]["email"] == "sam@ex.edu"


def test_find_staff_for_school_fills_missing_email_from_bio_page(monkeypatch):
    monkeypatch.setattr(
        tavily_client, "search",
        lambda query, api_key, max_results=5, timeout=30: [{"url": "https://x", "title": "t", "content": "c"}],
    )

    def fake_pick_url(school_name, purpose, results, provider=None):
        if purpose == "general_athletics":
            return {"url": "https://general.example.com", "confidence": "high", "notes": ""}
        return {"url": None, "confidence": "none", "notes": ""}

    monkeypatch.setattr(llm_provider, "pick_url", fake_pick_url)
    monkeypatch.setattr(wikipedia_lookup, "find_staff_link", lambda school_name: None)

    def fake_extract(url, api_key, timeout=30):
        return "bio text" if url == "https://bio.example.com/sam" else "directory text"

    monkeypatch.setattr(tavily_client, "extract", fake_extract)

    def fake_extract_staff(school_name, page_text, source_url, provider=None):
        if source_url == "https://bio.example.com/sam":
            return [{"name": "Sam Coach", "title": "Head Coach", "category": "coach", "sport": "track_field",
                      "email": "sam@ex.edu", "phone": "", "bio_url": ""}]
        return [{"name": "Sam Coach", "title": "Head Coach", "category": "coach", "sport": "track_field",
                  "email": "", "phone": "", "bio_url": "https://bio.example.com/sam"}]

    monkeypatch.setattr(llm_provider, "extract_staff", fake_extract_staff)

    result = staff_finder.find_staff_for_school("Example University", "TX", "tavily-key")
    assert result["staff"][0]["email"] == "sam@ex.edu"


def test_find_staff_for_school_fills_email_from_source_page_html(monkeypatch):
    monkeypatch.setattr(
        tavily_client,
        "search",
        lambda query, api_key, max_results=5, timeout=30: [{"url": "https://x", "title": "t", "content": "c"}],
    )
    monkeypatch.setattr(
        llm_provider,
        "pick_url",
        lambda school_name, purpose, results, provider=None: (
            {"url": "https://utdcomets.com/staff-directory", "confidence": "high", "notes": ""}
            if purpose == "general_athletics" else {"url": None, "confidence": "none", "notes": ""}
        ),
    )
    monkeypatch.setattr(wikipedia_lookup, "find_staff_link", lambda school_name: None)
    monkeypatch.setattr(tavily_client, "extract", lambda url, api_key, timeout=30: "directory text")
    monkeypatch.setattr(llm_provider, "extract_staff", lambda *a, **kw: [
        {"name": "Bill Petitt", "title": "Associate Athletic Director - External Affairs", "category": "admin",
         "sport": "", "email": "", "phone": "", "bio_url": "https://wrong.example.com/not-bill"}
    ])

    class _HtmlResponse:
        text = """
        <tr class="sidearm-staff-member">
          <td headers="col-fullname category-0">
            <a href="/staff-directory/bill-petitt/2">Bill Petitt</a>
          </td>
          <td headers="col-staff_email category-0">
            <script type="text/javascript">
              var firstHalf = "jdoe";
              var secondHalf = "example.edu";
              var full_email = firstHalf + '@' + secondHalf;
            </script>
          </td>
          <td headers="col-staff_phone category-0">
            <a href="tel:972-883-2055">972-883-2055</a>
          </td>
        </tr>
        """

        def raise_for_status(self):
            pass

    monkeypatch.setattr(staff_finder.requests, "get", lambda *a, **kw: _HtmlResponse())

    result = staff_finder.find_staff_for_school("The University of Texas at Dallas", "TX", "tavily-key")

    assert result["staff"][0]["email"] == "jdoe@example.edu"
    assert result["staff"][0]["phone"] == "972-883-2055"
    assert result["staff"][0]["bio_url"] == "https://utdcomets.com/staff-directory/bill-petitt/2"


def test_find_staff_for_school_returns_error_row_on_exception(monkeypatch):
    def raising_search(*a, **kw):
        raise RuntimeError("tavily is down")

    monkeypatch.setattr(tavily_client, "search", raising_search)

    result = staff_finder.find_staff_for_school("Example University", "TX", "tavily-key")
    assert len(result["staff"]) == 1
    assert result["staff"][0]["category"] == "error"
    assert "tavily is down" in result["staff"][0]["notes"]


def test_find_staff_for_school_dedup_keeps_coach_category_from_track_field_page(monkeypatch):
    monkeypatch.setattr(
        tavily_client, "search",
        lambda query, api_key, max_results=5, timeout=30: [{"url": "https://x", "title": "t", "content": "c"}],
    )
    monkeypatch.setattr(
        llm_provider, "pick_url",
        lambda school_name, purpose, results, provider=None: {
            "url": f"https://{purpose}.example.com", "confidence": "high", "notes": ""
        },
    )
    monkeypatch.setattr(tavily_client, "extract", lambda url, api_key, timeout=30: url)

    def fake_extract_staff(school_name, page_text, source_url, provider=None):
        if "general_athletics" in source_url:
            # General page miscategorizes this person, but has their email.
            return [{"name": "Pat Dual", "title": "Staff", "category": "admin", "sport": "",
                      "email": "pat@ex.edu", "phone": "", "bio_url": ""}]
        # Track & field page correctly identifies them as a coach, but has no email.
        return [{"name": "Pat Dual", "title": "Assistant Coach", "category": "coach", "sport": "track_field",
                  "email": "", "phone": "", "bio_url": ""}]

    monkeypatch.setattr(llm_provider, "extract_staff", fake_extract_staff)

    result = staff_finder.find_staff_for_school("Example University", "TX", "tavily-key")
    assert len(result["staff"]) == 1
    row = result["staff"][0]
    assert row["category"] == "coach"
    assert row["sport"] == "track_field"
    assert row["email"] == "pat@ex.edu"


def test_find_staff_for_school_bio_fill_requires_matching_name(monkeypatch):
    monkeypatch.setattr(
        tavily_client, "search",
        lambda query, api_key, max_results=5, timeout=30: [{"url": "https://x", "title": "t", "content": "c"}],
    )
    monkeypatch.setattr(
        llm_provider, "pick_url",
        lambda school_name, purpose, results, provider=None: (
            {"url": "https://general.example.com", "confidence": "high", "notes": ""}
            if purpose == "general_athletics" else {"url": None, "confidence": "none", "notes": ""}
        ),
    )
    monkeypatch.setattr(wikipedia_lookup, "find_staff_link", lambda school_name: None)

    def fake_extract(url, api_key, timeout=30):
        return "bio text" if url == "https://bio.example.com/sam" else "directory text"

    monkeypatch.setattr(tavily_client, "extract", fake_extract)

    def fake_extract_staff(school_name, page_text, source_url, provider=None):
        if source_url == "https://bio.example.com/sam":
            # Bio page's extraction returns a different person's email, not Sam's.
            return [{"name": "Other Person", "title": "Coach", "category": "coach", "sport": "track_field",
                      "email": "other@ex.edu", "phone": "", "bio_url": ""}]
        return [{"name": "Sam Coach", "title": "Head Coach", "category": "coach", "sport": "track_field",
                  "email": "", "phone": "", "bio_url": "https://bio.example.com/sam"}]

    monkeypatch.setattr(llm_provider, "extract_staff", fake_extract_staff)

    result = staff_finder.find_staff_for_school("Example University", "TX", "tavily-key")
    assert result["staff"][0]["email"] == ""


def test_find_staff_for_school_keeps_row_when_bio_extract_fails(monkeypatch):
    monkeypatch.setattr(
        tavily_client, "search",
        lambda query, api_key, max_results=5, timeout=30: [{"url": "https://x", "title": "t", "content": "c"}],
    )
    monkeypatch.setattr(
        llm_provider,
        "pick_url",
        lambda school_name, purpose, results, provider=None: (
            {"url": "https://general.example.com/staff", "confidence": "high", "notes": ""}
            if purpose == "general_athletics" else {"url": None, "confidence": "none", "notes": ""}
        ),
    )
    monkeypatch.setattr(wikipedia_lookup, "find_staff_link", lambda school_name: None)

    def fake_extract(url, api_key, timeout=30):
        if "bio" in url:
            raise requests.HTTPError("400 Client Error: Bad Request for url: https://api.tavily.com/extract")
        return "directory text"

    monkeypatch.setattr(tavily_client, "extract", fake_extract)
    monkeypatch.setattr(llm_provider, "extract_staff", lambda *a, **kw: [
        {"name": "Sam Coach", "title": "Head Coach", "category": "coach", "sport": "track_field",
         "email": "", "phone": "", "bio_url": "https://general.example.com/bio/sam"}
    ])

    result = staff_finder.find_staff_for_school("Example University", "TX", "tavily-key")

    assert result["staff"][0]["name"] == "Sam Coach"
    assert result["staff"][0]["category"] == "coach"
    assert result["staff"][0]["email"] == ""


def test_find_staff_for_school_resolves_relative_bio_url(monkeypatch):
    monkeypatch.setattr(
        tavily_client, "search",
        lambda query, api_key, max_results=5, timeout=30: [{"url": "https://x", "title": "t", "content": "c"}],
    )
    monkeypatch.setattr(
        llm_provider,
        "pick_url",
        lambda school_name, purpose, results, provider=None: (
            {"url": "https://general.example.com/staff/index.html", "confidence": "high", "notes": ""}
            if purpose == "general_athletics" else {"url": None, "confidence": "none", "notes": ""}
        ),
    )
    monkeypatch.setattr(wikipedia_lookup, "find_staff_link", lambda school_name: None)

    def fake_extract(url, api_key, timeout=30):
        return "bio text" if url == "https://general.example.com/bio/sam" else "directory text"

    monkeypatch.setattr(tavily_client, "extract", fake_extract)

    def fake_extract_staff(school_name, page_text, source_url, provider=None):
        if source_url == "https://general.example.com/bio/sam":
            return [{"name": "Sam Coach", "title": "Head Coach", "category": "coach", "sport": "track_field",
                     "email": "sam@ex.edu", "phone": "", "bio_url": ""}]
        return [{"name": "Sam Coach", "title": "Head Coach", "category": "coach", "sport": "track_field",
                 "email": "", "phone": "", "bio_url": "../bio/sam"}]

    monkeypatch.setattr(llm_provider, "extract_staff", fake_extract_staff)

    result = staff_finder.find_staff_for_school("Example University", "TX", "tavily-key")

    assert result["staff"][0]["email"] == "sam@ex.edu"


def test_find_staff_for_school_wikipedia_fallback_for_track_field_does_not_force_coach_category(monkeypatch):
    monkeypatch.setattr(
        tavily_client, "search",
        lambda query, api_key, max_results=5, timeout=30: [{"url": "https://x", "title": "t", "content": "c"}],
    )

    def fake_pick_url(school_name, purpose, results, provider=None):
        if purpose == "general_athletics":
            return {"url": "https://general.example.com", "confidence": "high", "notes": ""}
        return {"url": None, "confidence": "none", "notes": ""}

    monkeypatch.setattr(llm_provider, "pick_url", fake_pick_url)
    # Only the track_field purpose falls through to Wikipedia here (general
    # already resolved via Tavily), returning a page that is NOT
    # track-field-specific.
    monkeypatch.setattr(wikipedia_lookup, "find_staff_link", lambda school_name: "https://wiki-fallback.example.com")
    monkeypatch.setattr(tavily_client, "extract", lambda url, api_key, timeout=30: url)

    def fake_extract_staff(school_name, page_text, source_url, provider=None):
        if "general" in source_url:
            return [{"name": "Alex AD", "title": "Athletic Director", "category": "admin",
                      "sport": "", "email": "", "phone": "", "bio_url": ""}]
        # Wikipedia-fallback page: a trainer, correctly classified by the
        # LLM's own prompt — must NOT be force-relabeled "coach".
        return [{"name": "Dana Trainer", "title": "Athletic Trainer", "category": "sports_medicine",
                  "sport": "", "email": "", "phone": "", "bio_url": ""}]

    monkeypatch.setattr(llm_provider, "extract_staff", fake_extract_staff)

    result = staff_finder.find_staff_for_school("Example University", "TX", "tavily-key")
    dana = next(r for r in result["staff"] if r["name"] == "Dana Trainer")
    assert dana["category"] == "sports_medicine"
