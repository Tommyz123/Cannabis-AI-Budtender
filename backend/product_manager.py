"""Product data management module for AI Budtender.

Loads the product SQLite database, builds category indexes, generates compact JSON,
and applies beginner safety filtering with fallback logic.
"""

import json
import sqlite3

import pandas as pd

from backend.config import DB_PATH, BEGINNER_THC_LIMITS

# THC unit is determined by category (not stored in DB)
THC_UNIT_BY_CATEGORY: dict[str, str] = {
    "Flower": "%",
    "Pre-rolls": "%",
    "Vaporizers": "%",
    "Concentrates": "%",
    "Edibles": "mg",
    "Beverages": "mg",
    "Tincture": "mg",
    "Topicals": "mg",
}

_BEGINNER_EXPERIENCE = {"Beginner", "All Levels"}
_INTERMEDIATE_EXPERIENCE = {"Beginner", "Intermediate", "All Levels"}


def _build_thc_string(row: pd.Series) -> str:
    """Return THC level + unit as a compact string, e.g. '22%' or '5mg'."""
    level = row["thc_level"]
    unit = row.get("thc_unit", "")
    if pd.isna(level):
        return ""
    return f"{level}{unit}" if unit else str(level)


def _row_to_compact(row: pd.Series) -> dict:
    """Convert a DataFrame row to compact JSON dict format."""
    record = {
        "id": int(row["id"]),
        "s": str(row["product"]) if not pd.isna(row["product"]) else "",
        "c": str(row["brand"]) if not pd.isna(row["brand"]) else "",
        "cat": str(row["category"]) if not pd.isna(row["category"]) else "",
        "sub": str(row["sub_category"]) if not pd.isna(row["sub_category"]) else "",
        "t": str(row["strain_type"]) if not pd.isna(row["strain_type"]) else "",
        "thc": _build_thc_string(row),
        "p": float(row["price"]) if not pd.isna(row["price"]) else 0.0,
        "pr": str(row["price_range"]) if not pd.isna(row["price_range"]) else "",
        "f": str(row["effects"]) if not pd.isna(row["effects"]) else "",
        "sc": str(row["activity_scenario"]) if not pd.isna(row["activity_scenario"]) else "",
        "tod": str(row["time_of_day"]) if not pd.isna(row["time_of_day"]) else "",
        "xl": str(row["experience_level"]) if not pd.isna(row["experience_level"]) else "",
        "cm": str(row["consumption_method"]) if not pd.isna(row["consumption_method"]) else "",
        "on": str(row["onset_time"]) if not pd.isna(row["onset_time"]) else "",
        "dur": str(row["duration"]) if not pd.isna(row["duration"]) else "",
    }
    # Optional fields: include only when non-empty
    flv = row.get("flavor_profile")
    if flv is not None and not pd.isna(flv) and str(flv).strip():
        record["flv"] = str(flv)
    hw = row.get("hardware_type")
    if hw is not None and not pd.isna(hw) and str(hw).strip():
        record["hw"] = str(hw)
    wt = row.get("unit_weight")
    if wt is not None and not pd.isna(wt) and str(wt).strip():
        record["wt"] = str(wt)
    pk = row.get("pack_size")
    if pk is not None and not pd.isna(pk):
        record["pk"] = str(int(pk))
    return record


def _extract_hardware_type(attrs_str) -> str | None:
    """Extract hardware_type from attributes JSON string."""
    if not attrs_str:
        return None
    try:
        return json.loads(attrs_str).get("hardware_type")
    except (json.JSONDecodeError, AttributeError):
        return None


class ProductManager:
    """Manages product catalog loading, indexing, and filtering."""

    def __init__(self):
        self._df: pd.DataFrame = pd.DataFrame()
        self._category_index: dict[str, pd.DataFrame] = {}
        self._all_compact_json: str = "[]"

    def load(self, db_path: str = DB_PATH) -> None:
        """Load products from SQLite and build all indexes."""
        con = sqlite3.connect(db_path)
        df = pd.read_sql_query("SELECT * FROM products", con)
        con.close()

        # Derive thc_unit from category (replaces THCUnit column)
        df["thc_unit"] = df["category"].map(THC_UNIT_BY_CATEGORY).fillna("")

        # Extract hardware_type from attributes JSON for query search
        df["hardware_type"] = df["attributes"].apply(_extract_hardware_type)

        self._df = df
        self._build_category_index()
        self._all_compact_json = self._generate_compact_json(df)

    def _build_category_index(self) -> None:
        """Build a dict mapping category name → filtered DataFrame."""
        self._category_index = {
            cat: group.copy()
            for cat, group in self._df.groupby("category")
        }

    def _generate_compact_json(self, df: pd.DataFrame) -> str:
        """Serialize a DataFrame to compact JSON string."""
        records = [_row_to_compact(row) for _, row in df.iterrows()]
        return json.dumps(records, separators=(",", ":"))

    @property
    def total_count(self) -> int:
        """Return number of loaded products."""
        return len(self._df)

    @property
    def category_index(self) -> dict[str, pd.DataFrame]:
        """Return category index mapping."""
        return self._category_index

    def get_category_summary_json(self) -> str:
        """Return category counts for first-turn context (minimal tokens)."""
        summary = {
            "total": len(self._df),
            "cats": {cat: len(df) for cat, df in self._category_index.items()},
        }
        return json.dumps(summary, separators=(",", ":"))

    def get_all_compact_json(self) -> str:
        """Return pre-generated compact JSON for all products."""
        return self._all_compact_json

    def get_beginner_compact_json(self) -> str:
        """
        Return compact JSON of products safe for beginners.

        Applies hard safety rules, with two fallback levels
        if filtered count drops below 3.
        """
        df = self._apply_beginner_filter(self._df, _BEGINNER_EXPERIENCE)
        if len(df) >= 3:
            return self._generate_compact_json(df)

        # Fallback level 1: extend experience level to Intermediate
        df = self._apply_beginner_filter(self._df, _INTERMEDIATE_EXPERIENCE)
        if len(df) >= 3:
            return self._generate_compact_json(df)

        # Fallback level 2: fully open experience level, keep THC limits + no concentrates
        df = self._apply_beginner_filter(self._df, experience_levels=None)
        return self._generate_compact_json(df)

    def search_products(
        self,
        query: str = "",
        category: str | None = None,
        strain_type: str | None = None,
        effects: list[str] | None = None,
        exclude_effects: list[str] | None = None,
        exclude_categories: list[str] | None = None,
        min_thc: float | None = None,
        max_thc: float | None = None,
        max_price: float | None = None,
        budget_target: float | None = None,
        time_of_day: str | None = None,
        activity_scenario: str | None = None,
        unit_weight: str | None = None,
        list_sub_types: bool = False,
        limit: int = 8,
        is_beginner: bool = False,
        **_kwargs,
    ) -> dict:
        """
        Search products with optional filters. Called by the Agent Loop tool dispatcher.

        Returns:
            Dict with 'products' (list of compact dicts) and 'total' count.
            If list_sub_types=True, returns category/subcategory overview instead.
        """
        df = self._df.copy()

        # list_sub_types: return category overview (early return, skip filter pipeline)
        if list_sub_types:
            overview = {}
            for cat, cdf in self._category_index.items():
                subs = cdf["sub_category"].dropna().unique().tolist()
                overview[cat] = {"count": len(cdf), "subcategories": subs}
            return {"overview": overview}

        df_base = df.copy()
        df = self._apply_filters(
            df, category, strain_type, effects, exclude_effects, exclude_categories,
            min_thc, max_thc, max_price, budget_target, time_of_day,
            activity_scenario, unit_weight, query, is_beginner,
        )
        df = self._sort_results(df, budget_target)
        result = self._build_result(df, limit)

        if result["total"] == 0:
            fallback = self._try_fallback(
                df_base, category, strain_type, effects, exclude_effects, exclude_categories,
                min_thc, max_thc, max_price, budget_target, time_of_day,
                activity_scenario, unit_weight, query, is_beginner, limit,
            )
            if fallback:
                return fallback

        return result

    def _apply_filters(
        self,
        df: pd.DataFrame,
        category: str | None,
        strain_type: str | None,
        effects: list[str] | None,
        exclude_effects: list[str] | None,
        exclude_categories: list[str] | None,
        min_thc: float | None,
        max_thc: float | None,
        max_price: float | None,
        budget_target: float | None,
        time_of_day: str | None,
        activity_scenario: str | None,
        unit_weight: str | None,
        query: str,
        is_beginner: bool,
    ) -> pd.DataFrame:
        """Apply all search filters to the DataFrame and return filtered result."""
        # 1. Category filter
        if category:
            cat_lower = category.lower()
            matched_cat = next(
                (c for c in self._category_index if c.lower() == cat_lower), None
            )
            if matched_cat:
                df = self._category_index[matched_cat].copy()
            else:
                df = df[df["category"].str.lower() == cat_lower]

        # 2. Strain type filter (Indica / Sativa / Hybrid)
        if strain_type:
            df = df[df["strain_type"].str.lower() == strain_type.lower()]

        # 3. Exclude categories
        if exclude_categories:
            excl_lower = [c.lower() for c in exclude_categories]
            df = df[~df["category"].str.lower().isin(excl_lower)]

        # 4. Effects filter (effects column contains keyword)
        if effects:
            for effect in effects:
                df = df[df["effects"].str.contains(effect, case=False, na=False)]

        # 5. Exclude effects
        if exclude_effects:
            for eff in exclude_effects:
                df = df[~df["effects"].str.contains(eff, case=False, na=False)]

        # 6. min_thc (percentage products only)
        if min_thc is not None:
            pct_mask = df["thc_unit"] == "%"
            df = df[~pct_mask | (df["thc_level"] >= min_thc)]

        # 6b. max_thc (percentage products only)
        if max_thc is not None:
            pct_mask = df["thc_unit"] == "%"
            df = df[~pct_mask | (df["thc_level"] <= max_thc)]

        # 7. max_price filter
        if max_price is not None:
            df = df[df["price"].fillna(0) <= max_price]

        # 8. budget_target: keep products within 120% of target
        if budget_target is not None and max_price is None:
            df = df[df["price"].fillna(0) <= budget_target * 1.2]

        # 9. time_of_day filter
        if time_of_day:
            tod_lower = time_of_day.lower()
            df = df[
                df["time_of_day"].str.lower().str.contains(tod_lower, na=False)
                | (df["time_of_day"].str.lower() == "anytime")
            ]

        # 10. activity_scenario filter
        if activity_scenario:
            df = df[
                df["activity_scenario"].str.contains(
                    activity_scenario, case=False, na=False
                )
            ]

        # 11. unit_weight filter
        if unit_weight:
            df = df[df["unit_weight"].str.lower() == unit_weight.lower()]

        # 12. free-text query (product + strain_type + effects + unit_weight + description + flavor_profile + hardware_type)
        # regex=False: treat query as literal string, not regex
        if query:
            mask = df["product"].str.contains(query, case=False, na=False, regex=False)
            mask |= df["strain_type"].str.contains(query, case=False, na=False, regex=False)
            mask |= df["effects"].str.contains(query, case=False, na=False, regex=False)
            mask |= df["unit_weight"].str.contains(query, case=False, na=False, regex=False)
            mask |= df["description"].str.contains(query, case=False, na=False, regex=False)
            mask |= df["flavor_profile"].str.contains(query, case=False, na=False, regex=False)
            mask |= df["hardware_type"].str.contains(query, case=False, na=False, regex=False)
            df = df[mask]

        # Beginner safety filter
        if is_beginner:
            df = self._apply_beginner_filter(df, _BEGINNER_EXPERIENCE)

        return df

    def _sort_results(self, df: pd.DataFrame, budget_target: float | None) -> pd.DataFrame:
        """Sort filtered results: by price proximity to budget, or by weight + price."""
        def _parse_weight(wt):
            """Extract numeric value from weight string like '1g', '0.5g', '2g'."""
            try:
                return float(str(wt).replace("g", "").strip())
            except (ValueError, TypeError):
                return 0.0

        if not df.empty and "unit_weight" in df.columns:
            df = df.copy()
            df["_weight_num"] = df["unit_weight"].apply(_parse_weight)
            if budget_target is not None:
                df["_price_dist"] = (df["price"].fillna(0) - budget_target).abs()
                df = df.sort_values(["_price_dist"], ascending=[True])
                df = df.drop(columns=["_price_dist"])
            else:
                df = df.sort_values(["_weight_num", "price"], ascending=[False, False])
            df = df.drop(columns=["_weight_num"])

        return df

    def _build_result(self, df: pd.DataFrame, limit: int) -> dict:
        """Assemble the final result dict from filtered and sorted DataFrame."""
        matched_count = len(df)
        df = df.head(limit)
        products = [_row_to_compact(row) for _, row in df.iterrows()]
        return {"products": products, "total": matched_count}

    def _try_fallback(
        self,
        df_base: pd.DataFrame,
        category: str | None,
        strain_type: str | None,
        effects: list[str] | None,
        exclude_effects: list[str] | None,
        exclude_categories: list[str] | None,
        min_thc: float | None,
        max_thc: float | None,
        max_price: float | None,
        budget_target: float | None,
        time_of_day: str | None,
        activity_scenario: str | None,
        unit_weight: str | None,
        query: str,
        is_beginner: bool,
        limit: int,
    ) -> dict | None:
        """
        Try fallback searches when the original returns 0 results.

        Priority:
          1. Relax price (keep category + strain_type — find same product above budget)
          2. Relax strain_type to partial match (Indica → Indica-Hybrid), keep category + price
          3. Cross-category substitution (Flower → Pre-rolls), only when flavor query present

        Returns result dict with 'fallback_note' field, or None if all fallbacks fail.
        """
        def _run(new_category, new_strain_type, new_max_price, new_budget, note):
            df = self._apply_filters(
                df_base.copy(), new_category, new_strain_type, effects, exclude_effects,
                exclude_categories, min_thc, max_thc, new_max_price, new_budget,
                time_of_day, activity_scenario, unit_weight, query, is_beginner,
            )
            df = self._sort_results(df, new_budget)
            result = self._build_result(df, limit)
            if result["total"] > 0:
                result["fallback_note"] = note
                return result
            return None

        def _run_partial_strain(new_max_price, new_budget, note):
            """Apply partial strain_type match (contains) instead of exact match."""
            df = self._apply_filters(
                df_base.copy(), category, None, effects, exclude_effects,
                exclude_categories, min_thc, max_thc, new_max_price, new_budget,
                time_of_day, activity_scenario, unit_weight, query, is_beginner,
            )
            if strain_type:
                df = df[df["strain_type"].str.lower().str.contains(
                    strain_type.lower(), na=False
                )]
            df = self._sort_results(df, new_budget)
            result = self._build_result(df, limit)
            if result["total"] > 0:
                result["fallback_note"] = note
                return result
            return None

        cat_label = category or ""
        strain_label = strain_type.capitalize() if strain_type else ""
        budget_label = f"${int(max_price or budget_target)}" if (max_price or budget_target) else ""
        product_label = f"{strain_label} {cat_label}".strip() or "products"

        # ── Fallback 1: Relax price (keep category + strain_type) ─────────────
        if max_price is not None or budget_target is not None:
            note = (
                f"No {product_label} found within {budget_label}. "
                "Showing options above that budget:"
            )
            result = _run(category, strain_type, None, None, note)
            if result:
                return result

        # ── Fallback 2: Relax strain_type to partial match (keep category + price) ─
        if strain_type:
            note = (
                f"No pure {product_label} matched your criteria. "
                f"{strain_label}-dominant Hybrid is very similar in effect — showing those:"
            )
            result = _run_partial_strain(max_price, budget_target, note)
            if result:
                return result

        # ── Fallback 3: Cross-category Flower → Pre-rolls (only if flavor query present) ─
        if category and category.lower() == "flower" and query:
            flower_label = f"{strain_label} Flower" if strain_label else "Flower"
            note = (
                f"No {flower_label} with that flavor profile available. "
                "Pre-rolls share the same strain and flavor — showing those as a close alternative:"
            )
            result = _run("Pre-rolls", strain_type, max_price, budget_target, note)
            if result:
                return result

        return None

    def get_product_by_id(self, product_id: str) -> dict | None:
        """Return full compact product info for a given product ID, or None if not found."""
        try:
            pid = int(product_id)
        except (ValueError, TypeError):
            return None
        matches = self._df[self._df["id"] == pid]
        if matches.empty:
            return None
        return _row_to_compact(matches.iloc[0])

    def _apply_beginner_filter(
        self,
        df: pd.DataFrame,
        experience_levels: set | None,
    ) -> pd.DataFrame:
        """
        Apply beginner safety filters to a DataFrame.

        Args:
            df: Source product DataFrame.
            experience_levels: Set of allowed experience level strings,
                or None to skip experience level filtering.

        Returns:
            Filtered DataFrame.
        """
        limits = BEGINNER_THC_LIMITS

        # Rule 1: exclude concentrates (always)
        mask = df["category"] != "Concentrates"

        # Rule 2: experience level (optional)
        if experience_levels is not None:
            mask &= df["experience_level"].isin(experience_levels)

        # Rule 3: Edibles/Beverages THC <= 5mg (mg-unit, per-serving dose)
        edibles_mask = (df["thc_unit"] == "mg") & (
            df["thc_level"] > limits["edibles_mg"]
        )
        mask &= ~edibles_mask

        # Rule 4: Flower/Pre-rolls THC <= 20%
        flower_cats = {"Flower", "Pre-rolls"}
        flower_mask = (
            df["thc_unit"] == "%"
        ) & df["category"].isin(flower_cats) & (
            df["thc_level"] > limits["flower_percent"]
        )
        mask &= ~flower_mask

        # Rule 5: Vaporizers THC <= 70%
        vape_mask = (df["thc_unit"] == "%") & (
            df["category"] == "Vaporizers"
        ) & (df["thc_level"] > limits["vaporizers_percent"])
        mask &= ~vape_mask

        return df[mask].copy()
