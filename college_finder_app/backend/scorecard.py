"""College Scorecard API client."""
import requests

SCORECARD_URL = "https://api.data.gov/ed/collegescorecard/v1/schools.json"

# (abbr, display name) — the canonical list this module is built around.
_STATES = [
    ("AL", "Alabama"), ("AK", "Alaska"), ("AZ", "Arizona"), ("AR", "Arkansas"),
    ("CA", "California"), ("CO", "Colorado"), ("CT", "Connecticut"), ("DE", "Delaware"),
    ("FL", "Florida"), ("GA", "Georgia"), ("HI", "Hawaii"), ("ID", "Idaho"),
    ("IL", "Illinois"), ("IN", "Indiana"), ("IA", "Iowa"), ("KS", "Kansas"),
    ("KY", "Kentucky"), ("LA", "Louisiana"), ("ME", "Maine"), ("MD", "Maryland"),
    ("MA", "Massachusetts"), ("MI", "Michigan"), ("MN", "Minnesota"), ("MS", "Mississippi"),
    ("MO", "Missouri"), ("MT", "Montana"), ("NE", "Nebraska"), ("NV", "Nevada"),
    ("NH", "New Hampshire"), ("NJ", "New Jersey"), ("NM", "New Mexico"), ("NY", "New York"),
    ("NC", "North Carolina"), ("ND", "North Dakota"), ("OH", "Ohio"), ("OK", "Oklahoma"),
    ("OR", "Oregon"), ("PA", "Pennsylvania"), ("RI", "Rhode Island"), ("SC", "South Carolina"),
    ("SD", "South Dakota"), ("TN", "Tennessee"), ("TX", "Texas"), ("UT", "Utah"),
    ("VT", "Vermont"), ("VA", "Virginia"), ("WA", "Washington"), ("WV", "West Virginia"),
    ("WI", "Wisconsin"), ("WY", "Wyoming"), ("DC", "District of Columbia"),
]
_NAME_TO_ABBR = {name.lower(): abbr for abbr, name in _STATES}
_VALID_ABBRS = {abbr for abbr, _ in _STATES}


def list_states():
    """Return every state (+ DC) as {'abbr', 'name'}, sorted by name."""
    return [{"abbr": abbr, "name": name} for abbr, name in sorted(_STATES, key=lambda t: t[1])]


def normalize_state(state):
    """Accept either 'Texas' or 'TX' and return the two-letter abbreviation.
    Raises ValueError if the state isn't recognized."""
    s = state.strip()
    if len(s) == 2 and s.upper() in _VALID_ABBRS:
        return s.upper()
    abbr = _NAME_TO_ABBR.get(s.lower())
    if not abbr:
        raise ValueError(f"Unrecognized state: {state!r}")
    return abbr


def fetch_schools(state_abbr, fields, api_key, per_page=100):
    """
    Fetch every school in a state from College Scorecard, requesting the
    given API field names (e.g. 'school.name', 'latest.student.size')
    plus 'id' (always included). Returns a list of dicts, one per school,
    keyed by 'id' plus every entry in `fields`. Any field ending in
    '_url' gets 'https://' prefixed if it's missing a scheme.
    Raises requests.HTTPError (via raise_for_status) on an HTTP error, or
    other requests.RequestException on a network failure.
    """
    all_fields = ["id"] + [f for f in fields if f != "id"]
    fields_param = ",".join(all_fields)
    results = []
    page = 0

    while True:
        params = {
            "api_key": api_key,
            "school.state": state_abbr,
            "fields": fields_param,
            "per_page": per_page,
            "page": page,
        }
        resp = requests.get(SCORECARD_URL, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        batch = data.get("results", [])
        if not batch:
            break

        for row in batch:
            clean = {}
            for f in all_fields:
                v = row.get(f)
                if f.endswith("_url") and isinstance(v, str) and v and not v.startswith("http"):
                    v = "https://" + v
                clean[f] = v
            results.append(clean)

        total = data.get("metadata", {}).get("total", 0)
        page += 1
        if page * per_page >= total:
            break

    return results
