"""Tests for backend/product_manager.py."""

import json
import pytest
from backend.product_manager import ProductManager


CSV_PATH = "data/NYE4.0_v3.csv"


@pytest.fixture(scope="module")
def pm():
    """Loaded ProductManager fixture."""
    manager = ProductManager()
    manager.load(CSV_PATH)
    return manager


def test_load_products(pm):
    """Verify CSV loads correctly with expected row count and fields."""
    assert pm.total_count == 217
    df = pm._df
    required_cols = [
        "Strain", "Company", "Categories", "THCLevel", "THCUnit",
        "Price", "ExperienceLevel", "Feelings", "ConsumptionMethod",
    ]
    for col in required_cols:
        assert col in df.columns, f"Missing column: {col}"


def test_category_index(pm):
    """Verify category index covers all categories in the CSV."""
    index = pm.category_index
    expected_categories = {
        "Concentrates", "Beverages", "Edibles", "Topicals",
        "Flower", "Pre-rolls", "Vaporizers", "Tincture",
    }
    assert set(index.keys()) == expected_categories


def test_compact_json_format(pm):
    """Verify compact JSON contains all 14 required core fields for each product."""
    required_keys = {"id", "s", "c", "cat", "sub", "t", "thc", "p", "pr",
                     "f", "sc", "tod", "xl", "cm", "on", "dur"}
    products = json.loads(pm.get_all_compact_json())
    assert len(products) == 217
    for product in products:
        missing = required_keys - set(product.keys())
        assert not missing, f"Product id={product.get('id')} missing keys: {missing}"


def test_compact_json_optional_fields(pm):
    """Verify optional field hw is included for vaporizers only when present."""
    products = json.loads(pm.get_all_compact_json())
    for product in products:
        if "hw" in product:
            assert product["hw"], "hw field should not be empty when included"


def test_beginner_filter_excludes_concentrates(pm):
    """Verify beginner filter removes all Concentrates products."""
    products = json.loads(pm.get_beginner_compact_json())
    categories = {p["cat"] for p in products}
    assert "Concentrates" not in categories


def test_beginner_filter_thc_edibles(pm):
    """Verify beginner filter: Edibles THC <= 5mg."""
    filtered = pm._apply_beginner_filter(pm._df, {"Beginner", "All Levels"})
    edibles = filtered[filtered["Categories"] == "Edibles"]
    if not edibles.empty:
        assert (edibles["THCLevel"] <= 5).all()


def test_beginner_filter_thc_flower(pm):
    """Verify beginner filter: Flower/Pre-rolls THC <= 20%."""
    filtered = pm._apply_beginner_filter(pm._df, {"Beginner", "All Levels"})
    flower = filtered[filtered["Categories"].isin({"Flower", "Pre-rolls"})]
    if not flower.empty:
        assert (flower["THCLevel"] <= 20).all()


def test_beginner_filter_thc_vaporizers(pm):
    """Verify beginner filter: Vaporizers THC <= 70%."""
    filtered = pm._apply_beginner_filter(pm._df, {"Beginner", "All Levels"})
    vapes = filtered[filtered["Categories"] == "Vaporizers"]
    if not vapes.empty:
        assert (vapes["THCLevel"] <= 70).all()


def test_beginner_filter_experience_level(pm):
    """Verify beginner filter allows only Beginner and All Levels experience."""
    filtered = pm._apply_beginner_filter(pm._df, {"Beginner", "All Levels"})
    non_concentrates = filtered[filtered["Categories"] != "Concentrates"]
    allowed = {"Beginner", "All Levels"}
    assert non_concentrates["ExperienceLevel"].isin(allowed).all()


def test_fallback_level1(pm):
    """Verify fallback level 1 extends experience to Intermediate."""
    level0 = pm._apply_beginner_filter(pm._df, {"Beginner", "All Levels"})
    level1 = pm._apply_beginner_filter(pm._df, {"Beginner", "Intermediate", "All Levels"})
    assert len(level1) >= len(level0)
    allowed = {"Beginner", "Intermediate", "All Levels"}
    non_concentrates = level1[level1["Categories"] != "Concentrates"]
    assert non_concentrates["ExperienceLevel"].isin(allowed).all()


def test_fallback_level2(pm):
    """Verify fallback level 2 opens experience level completely."""
    filtered = pm._apply_beginner_filter(pm._df, experience_levels=None)
    assert "Concentrates" not in filtered["Categories"].values
    level1 = pm._apply_beginner_filter(pm._df, {"Beginner", "Intermediate", "All Levels"})
    assert len(filtered) >= len(level1)
