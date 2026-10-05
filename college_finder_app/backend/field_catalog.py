"""Loads and exposes the generated field catalog."""
import json
from pathlib import Path

CATALOG_PATH = Path(__file__).parent / "field_catalog.json"


def load_catalog(path=None):
    """
    Load the field catalog JSON and return its parsed dict:
    {"categories": [{"key", "label", "fields": [{"api_field", "label", "is_url"}]}],
     "value_labels": {api_field: {code_str: label_str}}}
    Defaults to the generated field_catalog.json next to this module.
    """
    if path is None:
        path = CATALOG_PATH
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def all_fields(catalog):
    """Flatten catalog['categories'] into a single list of api_field names."""
    return [f["api_field"] for cat in catalog["categories"] for f in cat["fields"]]


def decode_row(row, catalog):
    """
    Given a school row dict {api_field: raw_value}, return a new dict with
    any field present in catalog['value_labels'] decoded from its numeric
    code to its label string. Fields with no matching value_labels entry,
    or whose value has no matching code, pass through unchanged.
    """
    value_labels = catalog.get("value_labels", {})
    decoded = {}
    for k, v in row.items():
        labels = value_labels.get(k)
        if labels is not None and v is not None:
            decoded[k] = labels.get(str(v), v)
        else:
            decoded[k] = v
    return decoded
