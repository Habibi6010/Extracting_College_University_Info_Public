import pytest

from backend import llm_provider


class _FakeMessage:
    def __init__(self, content):
        self.content = content


class _FakeChoice:
    def __init__(self, content):
        self.message = _FakeMessage(content)


class _FakeCompletion:
    def __init__(self, content):
        self.choices = [_FakeChoice(content)]


def _make_fake_openai(content):
    """Returns a class that stands in for openai.OpenAI, whose instances
    expose .chat.completions.create(**kwargs) -> _FakeCompletion(content)."""

    class FakeCompletions:
        def create(self, **kwargs):
            return _FakeCompletion(content)

    class FakeChat:
        completions = FakeCompletions()

    class FakeClient:
        def __init__(self, api_key=None):
            self.chat = FakeChat()

    return FakeClient


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def test_get_provider_defaults_to_openai(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    assert llm_provider.get_provider() == "openai"


def test_get_provider_rejects_unknown(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "bogus")
    with pytest.raises(llm_provider.LLMError):
        llm_provider.get_provider()


def test_pick_url_no_results_skips_llm_call():
    result = llm_provider.pick_url("Test U", "general_athletics", [])
    assert result == {"url": None, "confidence": "none", "notes": "no search results"}


def test_pick_url_openai_parses_response(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(
        llm_provider, "OpenAI",
        _make_fake_openai('{"url": "https://x", "confidence": "high", "notes": "ok"}'),
    )
    result = llm_provider.pick_url(
        "Test U", "general_athletics", [{"url": "https://x", "title": "t", "content": "c"}]
    )
    assert result == {"url": "https://x", "confidence": "high", "notes": "ok"}


def test_pick_url_ollama_parses_response(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "ollama")

    def fake_post(url, json, timeout):
        assert url.endswith("/api/chat")
        return _FakeResponse({"message": {"content": '{"url": "https://y", "confidence": "medium", "notes": "ok"}'}})

    monkeypatch.setattr(llm_provider.requests, "post", fake_post)
    result = llm_provider.pick_url(
        "Test U", "general_athletics", [{"url": "https://y", "title": "t", "content": "c"}]
    )
    assert result == {"url": "https://y", "confidence": "medium", "notes": "ok"}


def test_pick_url_unparseable_response_returns_none(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(llm_provider, "OpenAI", _make_fake_openai("not json"))
    result = llm_provider.pick_url(
        "Test U", "general_athletics", [{"url": "https://y", "title": "t", "content": "c"}]
    )
    assert result == {"url": None, "confidence": "none", "notes": "LLM output not parseable"}


def test_pick_url_wrong_shape_response_returns_none(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(llm_provider, "OpenAI", _make_fake_openai('["not", "a", "dict"]'))
    result = llm_provider.pick_url(
        "Test U", "general_athletics", [{"url": "https://y", "title": "t", "content": "c"}]
    )
    assert result == {"url": None, "confidence": "none", "notes": "LLM output not parseable"}


def test_pick_url_missing_url_key_returns_none(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(llm_provider, "OpenAI", _make_fake_openai('{"confidence": "high"}'))
    result = llm_provider.pick_url(
        "Test U", "general_athletics", [{"url": "https://y", "title": "t", "content": "c"}]
    )
    assert result == {"url": None, "confidence": "none", "notes": "LLM output not parseable"}


def test_extract_staff_blank_page_text_skips_llm_call():
    assert llm_provider.extract_staff("Test U", "", "https://x") == []
    assert llm_provider.extract_staff("Test U", "   ", "https://x") == []


def test_extract_staff_parses_and_drops_unknown_category(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    payload = (
        '[{"name": "Jane Doe", "title": "Assistant Coach", "category": "coach", '
        '"sport": "track_field", "email": "jdoe@example.edu", "phone": "", "bio_url": ""},'
        '{"name": "Someone Else", "title": "Groundskeeper", "category": "facilities", '
        '"sport": "", "email": "", "phone": "", "bio_url": ""}]'
    )
    monkeypatch.setattr(llm_provider, "OpenAI", _make_fake_openai(payload))
    rows = llm_provider.extract_staff("Test U", "some page text", "https://x")
    assert len(rows) == 1
    assert rows[0]["name"] == "Jane Doe"
    assert rows[0]["category"] == "coach"
    assert rows[0]["email"] == "jdoe@example.edu"


def test_extract_staff_unparseable_response_returns_empty_list(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(llm_provider, "OpenAI", _make_fake_openai("not json"))
    assert llm_provider.extract_staff("Test U", "some page text", "https://x") == []


def test_extract_staff_wraps_single_object_response_in_list(monkeypatch):
    # Observed in the wild: when only one staff member is found, the model
    # sometimes returns a bare JSON object instead of a one-item array,
    # despite the system prompt asking for an array.
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    payload = (
        '{"name": "Justin LeBlanc", "title": "Director of Athletics", '
        '"category": "admin", "sport": "", "email": "", "phone": "601-974-1197", '
        '"bio_url": "https://gomajors.com/staff-directory/justin-leblanc/41"}'
    )
    monkeypatch.setattr(llm_provider, "OpenAI", _make_fake_openai(payload))
    rows = llm_provider.extract_staff("Test U", "some page text", "https://x")
    assert len(rows) == 1
    assert rows[0]["name"] == "Justin LeBlanc"
    assert rows[0]["category"] == "admin"
    assert rows[0]["phone"] == "601-974-1197"


def test_extract_staff_repairs_truncated_json_missing_closing_brace(monkeypatch):
    # Observed in the wild: Ollama occasionally degenerates into emitting a
    # long run of trailing whitespace instead of the closing brace, leaving
    # otherwise-complete JSON truncated.
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    payload = (
        '{\n\t"name": "Josh Daume",\n\t"title": "Director of Athletics",\n\t'
        '"category": "admin",\n\t"sport": "",\n\t"email": "",\n\t"phone": "",\n\t'
        '"bio_url": "/staff-directory/josh-daume/336"\n' + ("\t" * 50)
    )
    monkeypatch.setattr(llm_provider, "OpenAI", _make_fake_openai(payload))
    rows = llm_provider.extract_staff("Test U", "some page text", "https://x")
    assert len(rows) == 1
    assert rows[0]["name"] == "Josh Daume"
    assert rows[0]["bio_url"] == "/staff-directory/josh-daume/336"
