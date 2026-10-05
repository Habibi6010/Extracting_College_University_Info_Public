from backend import staff_cache


def test_load_missing_file_returns_none(tmp_path):
    assert staff_cache.load("TX", "Example University", cache_dir=tmp_path) is None


def test_save_then_load_round_trip(tmp_path):
    saved = staff_cache.save("TX", "Example University", [{"name": "Sam"}], cache_dir=tmp_path)
    loaded = staff_cache.load("TX", "Example University", cache_dir=tmp_path)
    assert loaded["school_name"] == "Example University"
    assert loaded["state"] == "TX"
    assert loaded["cache_version"] == staff_cache.CACHE_VERSION
    assert loaded["staff"] == [{"name": "Sam"}]
    assert loaded["fetched_at"] == saved["fetched_at"]


def test_save_slugifies_school_name_for_filename(tmp_path):
    staff_cache.save("TX", "St. Mary's University!", [], cache_dir=tmp_path)
    assert (tmp_path / "TX" / "st-mary-s-university.json").exists()


def test_different_schools_do_not_collide(tmp_path):
    staff_cache.save("TX", "Alpha College", [{"name": "A"}], cache_dir=tmp_path)
    staff_cache.save("TX", "Beta College", [{"name": "B"}], cache_dir=tmp_path)
    assert staff_cache.load("TX", "Alpha College", cache_dir=tmp_path)["staff"] == [{"name": "A"}]
    assert staff_cache.load("TX", "Beta College", cache_dir=tmp_path)["staff"] == [{"name": "B"}]
