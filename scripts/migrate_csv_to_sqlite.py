"""
Migration script: CSV (NYE4.0_v3.csv) → SQLite (products.db)
Run: venv/bin/python scripts/migrate_csv_to_sqlite.py
"""
import json
import re
import sqlite3

import pandas as pd

CSV_PATH = "data/NYE4.0_v3.csv"
DB_PATH = "data/products.db"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def parse_terpenes(raw: str) -> list[dict]:
    """'Myrcene,Limonene,Caryophyllene' → [{"name":..., "pct": null}, ...]"""
    if not isinstance(raw, str) or not raw.strip():
        return []
    return [{"name": t.strip(), "pct": None} for t in raw.split(",") if t.strip()]


def parse_other_cannabinoids(names_raw, levels_raw) -> list[dict]:
    """
    names_raw:  "CBG, CBD"  or  "CBN"  or NaN
    levels_raw: "1.5% CBG"  or  "100mg CBN"  or  "96.03% THCA"  or NaN
    Returns:    [{"name": "CBG", "amount": "1.5%"}, {"name": "CBD", "amount": null}]
    """
    if not isinstance(names_raw, str) or not names_raw.strip():
        return []

    names = [n.strip() for n in names_raw.split(",") if n.strip()]

    # Build a lookup {cannabinoid_name: amount_string} from OtherCannabinoidLevels
    level_map: dict[str, str] = {}
    if isinstance(levels_raw, str) and levels_raw.strip():
        # Format: "96.03% THCA" or "1.5% CBG" or "100mg CBN" or "1000mg CBD"
        for token in re.split(r",\s*", levels_raw):
            token = token.strip()
            # Match patterns like "96.03% THCA" or "100mg CBN"
            m = re.match(r"([\d.]+\s*%?mg?%?)\s+(\w+)", token)
            if m:
                amount_str = m.group(1).strip()
                canna_name = m.group(2).strip()
                level_map[canna_name.upper()] = amount_str

    result = []
    for name in names:
        amount = level_map.get(name.upper())
        result.append({"name": name, "amount": amount})
    return result


def parse_dietary(dietary_tags_raw, is_vegan, is_organic) -> list[str] | None:
    """Merge DietaryTags + IsVegan + IsOrganic into a deduplicated list."""
    tags: set[str] = set()
    if isinstance(dietary_tags_raw, str) and dietary_tags_raw.strip():
        for t in dietary_tags_raw.split(","):
            t = t.strip().lower()
            if t:
                tags.add(t)
    if is_vegan is True:
        tags.add("vegan")
    if is_organic is True:
        tags.add("organic")
    return sorted(tags) if tags else None


def parse_pack_size(raw) -> int | None:
    try:
        v = int(raw)
        return v if v > 0 else None
    except (TypeError, ValueError):
        return None


def nan_to_none(val):
    if pd.isna(val):
        return None
    return val


# ---------------------------------------------------------------------------
# Per-category attributes builders
# ---------------------------------------------------------------------------

def attrs_flower(row) -> dict:
    attrs: dict = {}
    terpenes = parse_terpenes(row["Terpenes"])
    if terpenes:
        attrs["terpenes"] = terpenes
        attrs["total_terpenes_pct"] = None

    # infused type
    sub = str(row["SubCategory"]).strip()
    if sub == "Moonrock":
        attrs["infused"] = {"type": "moonrock"}
    elif row["IsLiveResin"] is True:
        attrs["infused"] = {"type": "live_resin"}
    elif row["IsLiveRosin"] is True:
        attrs["infused"] = {"type": "live_rosin"}
    elif row["IsInfused"] is True:
        attrs["infused"] = {"type": "distillate"}

    oc = parse_other_cannabinoids(row["OtherCannabinoids"], row["OtherCannabinoidLevels"])
    if oc:
        attrs["other_cannabinoids"] = oc
    return attrs


def attrs_prerolls(row) -> dict:
    attrs: dict = {}
    terpenes = parse_terpenes(row["Terpenes"])
    if terpenes:
        attrs["terpenes"] = terpenes
        attrs["total_terpenes_pct"] = None

    if isinstance(row["PreRollConfig"], str) and row["PreRollConfig"].strip():
        attrs["pre_roll_config"] = row["PreRollConfig"].strip()

    # infused list
    sub = str(row["SubCategory"]).strip()
    infused = []
    if sub == "Live Resin" and row["IsLiveResin"] is True:
        infused.append({"type": "live_resin", "method": "infused"})
    elif sub == "Diamond Infused":
        infused.append({"type": "diamond", "method": "infused"})
    elif row["IsInfused"] is True:
        infused.append({"type": "other", "method": "infused"})
    if infused:
        attrs["infused"] = infused

    oc = parse_other_cannabinoids(row["OtherCannabinoids"], row["OtherCannabinoidLevels"])
    if oc:
        attrs["other_cannabinoids"] = oc
    return attrs


def attrs_edibles(row) -> dict:
    attrs: dict = {}
    terpenes = parse_terpenes(row["Terpenes"])
    if terpenes:
        attrs["terpenes"] = terpenes

    # thc_total_mg = thc_level(mg/piece) * pack_size
    pack = parse_pack_size(row["PackSize"])
    thc = nan_to_none(row["THCLevel"])
    if thc is not None and pack is not None:
        attrs["thc_total_mg"] = round(thc * pack, 2)

    dietary = parse_dietary(row["DietaryTags"], row["IsVegan"], row["IsOrganic"])
    if dietary:
        attrs["dietary"] = dietary

    oc = parse_other_cannabinoids(row["OtherCannabinoids"], row["OtherCannabinoidLevels"])
    if oc:
        attrs["other_cannabinoids"] = oc

    # Live Rosin edibles
    sub = str(row["SubCategory"]).strip()
    if sub == "Live Rosin" or row["IsLiveRosin"] is True:
        attrs["infused"] = [{"type": "live_rosin", "method": "infused"}]

    return attrs


def attrs_vaporizers(row) -> dict:
    attrs: dict = {}
    terpenes = parse_terpenes(row["Terpenes"])
    if terpenes:
        attrs["terpenes"] = terpenes
        attrs["total_terpenes_pct"] = None

    if isinstance(row["HardwareType"], str) and row["HardwareType"].strip():
        attrs["hardware_type"] = row["HardwareType"].strip()

    # oil_type from flags and SubCategory
    sub = str(row["SubCategory"]).strip()
    if row["IsLiveRosin"] is True or sub == "Live Rosin":
        attrs["oil_type"] = "live_rosin"
    elif row["IsLiveResin"] is True or sub == "Live Resin":
        attrs["oil_type"] = "live_resin"
    elif sub == "Distillate":
        attrs["oil_type"] = "distillate"
    else:
        attrs["oil_type"] = "distillate"

    oc = parse_other_cannabinoids(row["OtherCannabinoids"], row["OtherCannabinoidLevels"])
    if oc:
        attrs["other_cannabinoids"] = oc
    return attrs


def attrs_beverages(row) -> dict:
    attrs: dict = {}
    terpenes = parse_terpenes(row["Terpenes"])
    if terpenes:
        attrs["terpenes"] = terpenes
        attrs["total_terpenes_pct"] = None

    attrs["fast_acting"] = True

    dietary = parse_dietary(row["DietaryTags"], row["IsVegan"], row["IsOrganic"])
    if dietary:
        attrs["dietary"] = dietary

    oc = parse_other_cannabinoids(row["OtherCannabinoids"], row["OtherCannabinoidLevels"])

    # 1:1 ratio products: add CBD 10mg if no other_cannabinoids recorded
    strain = str(row["Strain"])
    if "1:1" in strain and not oc:
        oc = [{"name": "CBD", "amount": "10mg"}]

    if oc:
        attrs["other_cannabinoids"] = oc
    return attrs


def attrs_concentrates(row) -> dict:
    attrs: dict = {}
    terpenes = parse_terpenes(row["Terpenes"])
    if terpenes:
        attrs["terpenes"] = terpenes
        attrs["total_terpenes_pct"] = None

    oc = parse_other_cannabinoids(row["OtherCannabinoids"], row["OtherCannabinoidLevels"])
    if oc:
        attrs["other_cannabinoids"] = oc
    return attrs


def attrs_tincture(row) -> dict:
    attrs: dict = {}
    terpenes = parse_terpenes(row["Terpenes"])
    if terpenes:
        attrs["terpenes"] = terpenes
        attrs["total_terpenes_pct"] = None

    attrs["bottle_volume_ml"] = None

    dietary = parse_dietary(row["DietaryTags"], row["IsVegan"], row["IsOrganic"])
    if dietary:
        attrs["dietary"] = dietary

    oc = parse_other_cannabinoids(row["OtherCannabinoids"], row["OtherCannabinoidLevels"])
    if oc:
        attrs["other_cannabinoids"] = oc
    return attrs


def attrs_topicals(row) -> dict:
    attrs: dict = {}
    terpenes = parse_terpenes(row["Terpenes"])
    if terpenes:
        attrs["terpenes"] = terpenes
        attrs["total_terpenes_pct"] = None

    dietary = parse_dietary(row["DietaryTags"], row["IsVegan"], row["IsOrganic"])
    if dietary:
        attrs["dietary"] = dietary

    oc = parse_other_cannabinoids(row["OtherCannabinoids"], row["OtherCannabinoidLevels"])
    if oc:
        attrs["other_cannabinoids"] = oc
    return attrs


ATTRS_BUILDERS = {
    "Flower": attrs_flower,
    "Pre-rolls": attrs_prerolls,
    "Edibles": attrs_edibles,
    "Vaporizers": attrs_vaporizers,
    "Beverages": attrs_beverages,
    "Concentrates": attrs_concentrates,
    "Tincture": attrs_tincture,
    "Topicals": attrs_topicals,
}


# ---------------------------------------------------------------------------
# SubCategory normalization
# ---------------------------------------------------------------------------

def normalize_sub_category(category: str, sub: str) -> str:
    if category == "Beverages" and sub == "Drink":
        return "Beverage"
    if category == "Vaporizers":
        return "Vaporizer"
    return sub


# ---------------------------------------------------------------------------
# Main migration
# ---------------------------------------------------------------------------

def migrate():
    df = pd.read_csv(CSV_PATH)

    # Fix boolean columns (may be read as object)
    for col in ["IsLiveResin", "IsLiveRosin", "IsInfused", "IsVegan", "IsOrganic"]:
        df[col] = df[col].map({True: True, False: False, "True": True, "False": False})

    # Move Edibles SubCategory="Drink" → Beverages
    edible_drink_mask = (df["Categories"] == "Edibles") & (df["SubCategory"] == "Drink")
    df.loc[edible_drink_mask, "Categories"] = "Beverages"
    df.loc[edible_drink_mask, "SubCategory"] = "Beverage"

    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("DELETE FROM products")  # clear existing data on re-run

    inserted = 0
    skipped = 0

    for _, row in df.iterrows():
        category = str(row["Categories"]).strip()
        builder = ATTRS_BUILDERS.get(category)
        if builder is None:
            print(f"  SKIP unknown category '{category}': {row['Strain']}")
            skipped += 1
            continue

        sub_raw = str(nan_to_none(row["SubCategory"]) or "").strip()
        sub = normalize_sub_category(category, sub_raw)
        attrs = builder(row)

        cur.execute("""
            INSERT INTO products (
                product, brand, category, sub_category, strain_type,
                thc_level, price, price_range,
                effects, flavor_profile,
                time_of_day, activity_scenario, experience_level,
                consumption_method, onset_time, duration,
                unit_weight, pack_size, description, attributes
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            nan_to_none(row["Strain"]),
            nan_to_none(row["Company"]),
            category,
            sub or None,
            nan_to_none(row["Types"]),
            nan_to_none(row["THCLevel"]),
            nan_to_none(row["Price"]),
            nan_to_none(row["PriceRange"]),
            nan_to_none(row["Feelings"]),
            nan_to_none(row["FlavorProfile"]),
            nan_to_none(row["TimeOfDay"]),
            nan_to_none(row["ActivityScenario"]),
            nan_to_none(row["ExperienceLevel"]),
            nan_to_none(row["ConsumptionMethod"]),
            nan_to_none(row["OnsetTime"]),
            nan_to_none(row["Duration"]),
            nan_to_none(row["UnitWeight"]),
            parse_pack_size(row["PackSize"]),
            nan_to_none(row["Description"]),
            json.dumps(attrs) if attrs else None,
        ))
        inserted += 1

    con.commit()
    con.close()
    print(f"Migration complete: {inserted} inserted, {skipped} skipped")


if __name__ == "__main__":
    migrate()
