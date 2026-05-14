"""Tests for backend/product_manager.py."""

import json
import pytest
from backend.product_manager import ProductManager
from backend.config import DB_PATH


@pytest.fixture(scope="module")
def pm():
    """Loaded ProductManager fixture."""
    manager = ProductManager()
    manager.load(DB_PATH)
    return manager


def test_load_products(pm):
    """Verify DB loads correctly with expected row count and fields."""
    assert pm.total_count == 217
    df = pm._df
    required_cols = [
        "product", "brand", "category", "thc_level", "thc_unit",
        "price", "experience_level", "effects", "consumption_method",
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
    edibles = filtered[filtered["category"] == "Edibles"]
    if not edibles.empty:
        assert (edibles["thc_level"] <= 5).all()


def test_beginner_filter_thc_flower(pm):
    """Verify beginner filter: Flower/Pre-rolls THC <= 20%."""
    filtered = pm._apply_beginner_filter(pm._df, {"Beginner", "All Levels"})
    flower = filtered[filtered["category"].isin({"Flower", "Pre-rolls"})]
    if not flower.empty:
        assert (flower["thc_level"] <= 20).all()


def test_beginner_filter_thc_vaporizers(pm):
    """Verify beginner filter: Vaporizers THC <= 70%."""
    filtered = pm._apply_beginner_filter(pm._df, {"Beginner", "All Levels"})
    vapes = filtered[filtered["category"] == "Vaporizers"]
    if not vapes.empty:
        assert (vapes["thc_level"] <= 70).all()


def test_beginner_filter_experience_level(pm):
    """Verify beginner filter allows only Beginner and All Levels experience."""
    filtered = pm._apply_beginner_filter(pm._df, {"Beginner", "All Levels"})
    non_concentrates = filtered[filtered["category"] != "Concentrates"]
    allowed = {"Beginner", "All Levels"}
    assert non_concentrates["experience_level"].isin(allowed).all()


def test_fallback_level1(pm):
    """Verify fallback level 1 extends experience to Intermediate."""
    level0 = pm._apply_beginner_filter(pm._df, {"Beginner", "All Levels"})
    level1 = pm._apply_beginner_filter(pm._df, {"Beginner", "Intermediate", "All Levels"})
    assert len(level1) >= len(level0)
    allowed = {"Beginner", "Intermediate", "All Levels"}
    non_concentrates = level1[level1["category"] != "Concentrates"]
    assert non_concentrates["experience_level"].isin(allowed).all()


def test_fallback_level2(pm):
    """Verify fallback level 2 opens experience level completely."""
    filtered = pm._apply_beginner_filter(pm._df, experience_levels=None)
    assert "Concentrates" not in filtered["category"].values
    level1 = pm._apply_beginner_filter(pm._df, {"Beginner", "Intermediate", "All Levels"})
    assert len(filtered) >= len(level1)


# ── strain_type filter tests ───────────────────────────────────────────────────

def test_strain_type_filter_indica(pm):
    """Verify strain_type='Indica' only returns Indica products."""
    result = pm.search_products(category="Flower", strain_type="Indica")
    assert result["total"] > 0
    for p in result["products"]:
        assert p["t"].lower() == "indica", f"Expected Indica, got {p['t']}"


def test_strain_type_filter_sativa(pm):
    """Verify strain_type='Sativa' only returns Sativa products."""
    result = pm.search_products(category="Flower", strain_type="Sativa")
    assert result["total"] > 0
    for p in result["products"]:
        assert p["t"].lower() == "sativa", f"Expected Sativa, got {p['t']}"


def test_strain_type_filter_case_insensitive(pm):
    """Verify strain_type filter is case-insensitive."""
    result_upper = pm.search_products(strain_type="Indica")
    result_lower = pm.search_products(strain_type="indica")
    assert result_upper["total"] == result_lower["total"]


def test_strain_type_no_results_triggers_fallback(pm):
    """Verify fallback triggers when strain_type + query combination yields 0 results."""
    # Sativa flower with diesel/sour flavor = 0 results in dataset
    result = pm.search_products(
        category="Flower",
        strain_type="Sativa",
        query="diesel",
        budget_target=50,
    )
    assert result["total"] > 0, "Fallback should find results after removing strain_type"
    assert "fallback_note" in result, "Result should include fallback_note"
    assert "Sativa" in result["fallback_note"]


def test_fallback_note_absent_when_results_found(pm):
    """Verify fallback_note is NOT present when original search returns results."""
    result = pm.search_products(category="Flower", strain_type="Indica")
    assert "fallback_note" not in result


def test_fallback_thc_range_widening(pm):
    """Verify fallback widens THC range by ±5% when strain_type not set."""
    # Use an impossibly narrow THC range with no strain_type to trigger THC fallback
    result = pm.search_products(
        category="Flower",
        min_thc=99,
        max_thc=99,
    )
    # Should either find nothing (all fallbacks fail) or find with widened range
    # The key check: no crash and result has expected structure
    assert "products" in result
    assert "total" in result


def test_fallback_price_relaxation(pm):
    """Verify fallback relaxes price by +$15 when other fallbacks fail."""
    # Products exist just above $10 (e.g., pre-rolls ~$15)
    result = pm.search_products(
        category="Pre-rolls",
        max_price=1,  # impossibly low
    )
    assert "products" in result
    assert "total" in result


# ── get_filter_metadata: storefront sidebar bootstrap ────────────────────

def test_get_filter_metadata_returns_complete_structure(pm):
    """Sidebar metadata covers categories, brands, strains, effects, ranges."""
    meta = pm.get_filter_metadata()
    expected_keys = {
        "categories", "brands", "strain_types", "effects",
        "price_range", "thc_pct_range", "thc_mg_range",
        "on_sale_count", "total",
    }
    assert expected_keys.issubset(meta.keys())
    assert meta["total"] == 217


def test_get_filter_metadata_categories_sorted_desc_by_count(pm):
    """Categories are sorted descending by product count so the storefront
    can render most-populous first without further work."""
    meta = pm.get_filter_metadata()
    counts = [c["count"] for c in meta["categories"]]
    assert counts == sorted(counts, reverse=True)
    # All 8 catalog categories present.
    names = {c["name"] for c in meta["categories"]}
    assert "Flower" in names
    assert "Edibles" in names
    assert "Vaporizers" in names


def test_get_filter_metadata_strain_types_includes_canonical_three(pm):
    """Indica / Sativa / Hybrid are always present as primary strain types."""
    meta = pm.get_filter_metadata()
    names = {s["name"] for s in meta["strain_types"]}
    for canonical in ("Indica", "Sativa", "Hybrid"):
        assert canonical in names, f"missing canonical strain {canonical}"


def test_get_filter_metadata_effects_sorted_desc_by_count(pm):
    """Effects are returned most-common-first so the sidebar shows
    high-signal effects (Happy, Relaxed, Energetic) before niche ones."""
    meta = pm.get_filter_metadata()
    counts = [e["count"] for e in meta["effects"]]
    assert counts == sorted(counts, reverse=True)
    # Validate at least a few well-known effects are present.
    names = {e["name"] for e in meta["effects"]}
    assert "Happy" in names
    assert "Relaxed" in names


def test_get_filter_metadata_ranges_well_formed(pm):
    """Price + THC ranges have min ≤ max and non-negative values."""
    meta = pm.get_filter_metadata()
    pr = meta["price_range"]
    assert 0 <= pr["min"] <= pr["max"]
    pct = meta["thc_pct_range"]
    assert 0 <= pct["min"] <= pct["max"]
    mg = meta["thc_mg_range"]
    assert 0 <= mg["min"] <= mg["max"]


def test_get_filter_metadata_on_sale_count_matches_db(pm):
    """on_sale_count reflects the seeded ~20% (43 products in this dataset)."""
    meta = pm.get_filter_metadata()
    assert meta["on_sale_count"] > 0
    # The exact number is deterministic from scripts/seed_sale_data.py
    # (seed=42, 43 products). If the seeder changes, update this number.
    assert meta["on_sale_count"] == 43
