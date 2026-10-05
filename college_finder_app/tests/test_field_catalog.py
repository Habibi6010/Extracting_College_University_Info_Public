import json

from backend import field_catalog


def test_real_catalog_loads_and_has_expected_categories():
    catalog = field_catalog.load_catalog()
    keys = [c["key"] for c in catalog["categories"]]
    assert keys == [
        "basic_info", "location", "institution_type",
        "admissions", "cost", "student_body", "financial_aid",
    ]
    for cat in catalog["categories"]:
        assert len(cat["fields"]) > 0
        for f in cat["fields"]:
            assert f["api_field"]
            assert f["label"]


def test_real_catalog_value_labels_cover_expected_fields():
    catalog = field_catalog.load_catalog()
    assert catalog["value_labels"]["school.degrees_awarded.highest"]["3"] == "Bachelor's degree"
    assert catalog["value_labels"]["school.men_only"] == {"0": "No", "1": "Yes"}
    assert "school.ownership" not in catalog["value_labels"]


def test_real_catalog_every_decodable_field_exists_in_some_category():
    catalog = field_catalog.load_catalog()
    known_fields = set(field_catalog.all_fields(catalog))
    for api_field in catalog["value_labels"]:
        assert api_field in known_fields


def test_load_catalog_with_explicit_path(tmp_path):
    fixture = {
        "categories": [
            {"key": "basic_info", "label": "Basic Info", "fields": [
                {"api_field": "school.name", "label": "Institution name", "is_url": False},
            ]},
        ],
        "value_labels": {"school.ownership": {"1": "Public", "2": "Private nonprofit"}},
    }
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps(fixture), encoding="utf-8")
    catalog = field_catalog.load_catalog(path)
    assert catalog == fixture


def test_all_fields_flattens_categories():
    catalog = {
        "categories": [
            {"key": "a", "label": "A", "fields": [{"api_field": "x", "label": "X", "is_url": False}]},
            {"key": "b", "label": "B", "fields": [{"api_field": "y", "label": "Y", "is_url": False}]},
        ],
        "value_labels": {},
    }
    assert field_catalog.all_fields(catalog) == ["x", "y"]


def test_decode_row_decodes_known_code_and_passes_through_unknown():
    catalog = {
        "categories": [],
        "value_labels": {"school.ownership": {"1": "Public", "2": "Private nonprofit"}},
    }
    row = {"school.ownership": 1, "school.name": "Test U", "latest.student.size": None}
    decoded = field_catalog.decode_row(row, catalog)
    assert decoded == {"school.ownership": "Public", "school.name": "Test U", "latest.student.size": None}

    row2 = {"school.ownership": 99}
    assert field_catalog.decode_row(row2, catalog) == {"school.ownership": 99}
