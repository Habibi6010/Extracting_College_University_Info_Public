"""
One-time build script: reads API_Documentations/CollegeScorecardDataDictionary.xlsx
and writes college_finder_app/backend/field_catalog.json.

Run manually whenever the Data Dictionary is updated:
    python API_Documentations/build_field_catalog.py
"""
import json
import re
from pathlib import Path

import openpyxl

REPO_ROOT = Path(__file__).parent.parent
DICTIONARY_PATH = REPO_ROOT / "API_Documentations" / "CollegeScorecardDataDictionary.xlsx"
OUTPUT_PATH = REPO_ROOT / "college_finder_app" / "backend" / "field_catalog.json"

# dev-category -> (category key, category label) for categories that pass
# straight through as "latest.<category>.<dev-friendly-name>".
LATEST_CATEGORIES = {
    "admissions": ("admissions", "Admissions"),
    "cost": ("cost", "Cost"),
    "student": ("student_body", "Student Body"),
    "aid": ("financial_aid", "Financial Aid"),
}

# Explicit allowlists for root/school fields, verified against the
# dictionary's actual field list (there is no single obvious rule to
# split these programmatically). Anything in root/school not listed here
# falls into Institution Type by default.
BASIC_INFO_FIELDS = {
    "id", "ope8_id", "ope6_id", "fed_sch_cd",
    "name", "accreditor", "school_url", "price_calculator_url", "alias",
    "accreditor_code", "title_iv.approval_date", "title_iv.eligibility_type",
    "under_investigation", "main_campus", "branches", "operating", "dolflag",
}
LOCATION_FIELDS = {
    "location.lat", "location.lon",
    "city", "state", "zip", "state_fips", "region_id", "locale",
    "degree_urbanization", "address",
}

CATEGORY_LABELS = {"basic_info": "Basic Info", "location": "Location", "institution_type": "Institution Type"}
CATEGORY_ORDER = [
    "basic_info", "location", "institution_type",
    "admissions", "cost", "student_body", "financial_aid",
]

VALUE_ENUM_RE = re.compile(r"^\s*(-?\d+)\s+(.+?)\s*$")


def parse_embedded_enum(name_cell):
    """
    Parse a multi-line 'NAME OF DATA ELEMENT' cell like:
        "Highest degree awarded\n 0 Non-degree-granting\n 1 Certificate degree"
    into {"0": "Non-degree-granting", "1": "Certificate degree", ...}.
    Returns {} if the cell has no embedded enumeration lines.
    """
    if not name_cell or "\n" not in str(name_cell):
        return {}
    lines = str(name_cell).split("\n")[1:]  # skip the description line
    labels = {}
    for line in lines:
        m = VALUE_ENUM_RE.match(line)
        if m:
            labels[m.group(1)] = m.group(2)
    return labels


def api_field_name(dev_category, dev_name):
    """
    Map a (dev-category, developer-friendly name) pair to the actual
    College Scorecard API field name, per the convention verified against
    the live API:
      - root fields: no prefix (e.g. 'id')
      - school fields: 'school.' prefix (e.g. 'school.name')
      - time-variant categories: 'latest.<category>.' prefix
        (e.g. 'latest.student.size')
    """
    if dev_category == "root":
        return dev_name
    if dev_category == "school":
        return f"school.{dev_name}"
    return f"latest.{dev_category}.{dev_name}"


def classify_root_school(dev_name):
    """Return the picker category key for a root/school field."""
    if dev_name in BASIC_INFO_FIELDS:
        return "basic_info"
    if dev_name in LOCATION_FIELDS:
        return "location"
    return "institution_type"


def build_catalog():
    wb = openpyxl.load_workbook(DICTIONARY_PATH, read_only=True, data_only=True)
    ws = wb["Institution_Data_Dictionary"]
    rows = list(ws.iter_rows(values_only=True))
    data_rows = rows[1:]  # skip header

    categories = {}  # key -> {"key", "label", "fields": [...]}
    value_labels = {}
    seen_api_fields = set()

    for row in data_rows:
        name_cell, dev_category, dev_name = row[0], row[1], row[2]
        value, label = row[6], row[7]

        if not dev_name or not dev_category:
            continue  # blank spacer row

        if dev_category in ("root", "school"):
            cat_key = classify_root_school(dev_name)
            cat_label = CATEGORY_LABELS[cat_key]
        elif dev_category in LATEST_CATEGORIES:
            cat_key, cat_label = LATEST_CATEGORIES[dev_category]
        else:
            continue  # completion/repayment/earnings/academics: out of scope

        api_field = api_field_name(dev_category, dev_name)
        if api_field in seen_api_fields:
            continue  # dictionary repeats a field across multiple value/label rows
        seen_api_fields.add(api_field)

        field_label = str(name_cell).split("\n")[0] if name_cell else dev_name
        is_url = dev_name.endswith("_url")

        categories.setdefault(cat_key, {"key": cat_key, "label": cat_label, "fields": []})
        categories[cat_key]["fields"].append({
            "api_field": api_field,
            "label": field_label,
            "is_url": is_url,
        })

        # Value decoding: a fully-enumerated field wins; otherwise fall
        # back to the generic boolean-flag rule.
        enum_labels = parse_embedded_enum(name_cell)
        if enum_labels:
            value_labels[api_field] = enum_labels
        elif value is not None and label in ("Yes", "No"):
            value_labels[api_field] = {"0": "No", "1": "Yes"}

    ordered = [categories[k] for k in CATEGORY_ORDER if k in categories]
    return {"categories": ordered, "value_labels": value_labels}


def main():
    catalog = build_catalog()
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(catalog, f, indent=2)
    total_fields = sum(len(c["fields"]) for c in catalog["categories"])
    print(
        f"Wrote {OUTPUT_PATH} with {len(catalog['categories'])} categories, "
        f"{total_fields} fields, {len(catalog['value_labels'])} decodable fields."
    )


if __name__ == "__main__":
    main()
