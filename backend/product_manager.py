"""Product data management module for AI Budtender.

Loads the product CSV, builds category indexes, generates compact JSON,
and applies beginner safety filtering with fallback logic.
"""

import json
import pandas as pd
from backend.config import CSV_PATH, BEGINNER_THC_LIMITS

_BEGINNER_EXPERIENCE = {"Beginner", "All Levels"}
_INTERMEDIATE_EXPERIENCE = {"Beginner", "Intermediate", "All Levels"}
_STRAIN_TYPE_KEYWORDS = {"indica", "sativa", "hybrid"}

_COMPACT_KEY_MAP = {
    "id": "id",
    "Strain": "s",
    "Company": "c",
    "Categories": "cat",
    "SubCategory": "sub",
    "Types": "t",
    "thc": "thc",
    "Price": "p",
    "PriceRange": "pr",
    "Feelings": "f",
    "ActivityScenario": "sc",
    "TimeOfDay": "tod",
    "ExperienceLevel": "xl",
    "ConsumptionMethod": "cm",
    "OnsetTime": "on",
    "Duration": "dur",
    "FlavorProfile": "flv",
    "HardwareType": "hw",
}


def _build_thc_string(row: pd.Series) -> str:
    """Return THC level + unit as a compact string, e.g. '22%' or '5mg'."""
    level = row["THCLevel"]
    unit = row["THCUnit"]
    if pd.isna(level):
        return ""
    if pd.isna(unit):
        return str(level)
    return f"{level}{unit}"


def _row_to_compact(row: pd.Series) -> dict:
    """Convert a DataFrame row to compact JSON dict format (PRD section 11)."""
    record = {
        "id": int(row["id"]),
        "s": str(row["Strain"]) if not pd.isna(row["Strain"]) else "",
        "c": str(row["Company"]) if not pd.isna(row["Company"]) else "",
        "cat": str(row["Categories"]) if not pd.isna(row["Categories"]) else "",
        "sub": str(row["SubCategory"]) if not pd.isna(row["SubCategory"]) else "",
        "t": str(row["Types"]) if not pd.isna(row["Types"]) else "",
        "thc": _build_thc_string(row),
        "p": float(row["Price"]) if not pd.isna(row["Price"]) else 0.0,
        "pr": str(row["PriceRange"]) if not pd.isna(row["PriceRange"]) else "",
        "f": str(row["Feelings"]) if not pd.isna(row["Feelings"]) else "",
        "sc": str(row["ActivityScenario"]) if not pd.isna(row["ActivityScenario"]) else "",
        "tod": str(row["TimeOfDay"]) if not pd.isna(row["TimeOfDay"]) else "",
        "xl": str(row["ExperienceLevel"]) if not pd.isna(row["ExperienceLevel"]) else "",
        "cm": str(row["ConsumptionMethod"]) if not pd.isna(row["ConsumptionMethod"]) else "",
        "on": str(row["OnsetTime"]) if not pd.isna(row["OnsetTime"]) else "",
        "dur": str(row["Duration"]) if not pd.isna(row["Duration"]) else "",
    }
    # Optional fields: include only when non-empty
    flv = row["FlavorProfile"]
    if not pd.isna(flv) and str(flv).strip():
        record["flv"] = str(flv)
    hw = row["HardwareType"]
    if not pd.isna(hw) and str(hw).strip():
        record["hw"] = str(hw)
    wt = row["UnitWeight"]
    if not pd.isna(wt) and str(wt).strip():
        record["wt"] = str(wt)
    pk = row["PackSize"]
    if not pd.isna(pk) and str(pk).strip():
        record["pk"] = str(int(pk))
    return record


class ProductManager:
    """Manages product catalog loading, indexing, and filtering."""

    def __init__(self):
        self._df: pd.DataFrame = pd.DataFrame()
        self._category_index: dict[str, pd.DataFrame] = {}
        self._all_compact_json: str = "[]"

    def load(self, csv_path: str = CSV_PATH) -> None:
        """Load the product CSV and build all indexes."""
        df = pd.read_csv(csv_path)
        df.insert(0, "id", range(1, len(df) + 1))
        self._df = df
        self._build_category_index()
        self._all_compact_json = self._generate_compact_json(df)

    def _build_category_index(self) -> None:
        """Build a dict mapping category name → filtered DataFrame."""
        self._category_index = {
            cat: group.copy()
            for cat, group in self._df.groupby("Categories")
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

        Applies hard safety rules (PRD section 6), with two fallback levels
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
                subs = cdf["SubCategory"].dropna().unique().tolist()
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
                df = df[df["Categories"].str.lower() == cat_lower]

        # 2. Strain type filter (Indica / Sativa / Hybrid)
        if strain_type:
            df = df[df["Types"].str.lower() == strain_type.lower()]

        # 3. Exclude categories
        if exclude_categories:
            excl_lower = [c.lower() for c in exclude_categories]
            df = df[~df["Categories"].str.lower().isin(excl_lower)]

        # 4. Effects filter (Feelings column contains keyword)
        if effects:
            for effect in effects:
                df = df[df["Feelings"].str.contains(effect, case=False, na=False)]

        # 5. Exclude effects
        if exclude_effects:
            for eff in exclude_effects:
                df = df[~df["Feelings"].str.contains(eff, case=False, na=False)]

        # 6. min_thc (percentage products only)
        if min_thc is not None:
            pct_mask = df["THCUnit"] == "%"
            df = df[~pct_mask | (df["THCLevel"] >= min_thc)]

        # 6b. max_thc (percentage products only)
        if max_thc is not None:
            pct_mask = df["THCUnit"] == "%"
            df = df[~pct_mask | (df["THCLevel"] <= max_thc)]

        # 6. max_price filter
        if max_price is not None:
            df = df[df["Price"].fillna(0) <= max_price]

        # 7. budget_target: keep products within 120% of target
        if budget_target is not None and max_price is None:
            df = df[df["Price"].fillna(0) <= budget_target * 1.2]

        # 8. time_of_day filter
        if time_of_day:
            tod_lower = time_of_day.lower()
            df = df[
                df["TimeOfDay"].str.lower().str.contains(tod_lower, na=False)
                | (df["TimeOfDay"].str.lower() == "anytime")
            ]

        # 9. activity_scenario filter
        if activity_scenario:
            df = df[
                df["ActivityScenario"].str.contains(
                    activity_scenario, case=False, na=False
                )
            ]

        # 10. unit_weight filter
        if unit_weight:
            df = df[df["UnitWeight"].str.lower() == unit_weight.lower()]

        # 11. free-text query (Strain + Types + Feelings + UnitWeight + Description + FlavorProfile + HardwareType)
        # regex=False: treat query as literal string, not regex — prevents | and other special chars from being misinterpreted
        if query:
            desc_col = "Description" if "Description" in df.columns else None
            mask = df["Strain"].str.contains(query, case=False, na=False, regex=False)
            mask |= df["Types"].str.contains(query, case=False, na=False, regex=False)
            mask |= df["Feelings"].str.contains(query, case=False, na=False, regex=False)
            mask |= df["UnitWeight"].str.contains(query, case=False, na=False, regex=False)
            if desc_col:
                mask |= df[desc_col].str.contains(query, case=False, na=False, regex=False)
            mask |= df["FlavorProfile"].str.contains(query, case=False, na=False, regex=False)
            mask |= df["HardwareType"].str.contains(query, case=False, na=False, regex=False)
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
                return float(str(wt).replace('g', '').strip())
            except (ValueError, TypeError):
                return 0.0

        if not df.empty and "UnitWeight" in df.columns:
            df = df.copy()
            df["_weight_num"] = df["UnitWeight"].apply(_parse_weight)
            if budget_target is not None:
                # Budget intent: show products closest to budget target first
                df["_price_dist"] = (df["Price"].fillna(0) - budget_target).abs()
                df = df.sort_values(["_price_dist"], ascending=[True])
                df = df.drop(columns=["_price_dist"])
            else:
                df = df.sort_values(["_weight_num", "Price"], ascending=[False, False])
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
        Try one fallback search when the original returns 0 results.

        Priority:
          1. Remove strain_type AND category (when query is present) to find flavor matches
             across all forms; results are sorted by FlavorProfile match first.
          2. Widen THC range by ±5%
          3. Relax price limit by +$15

        Returns result dict with 'fallback_note' field, or None if all fallbacks also fail.
        """
        def _run(new_category, new_strain_type, new_query, new_min_thc, new_max_thc,
                 new_max_price, new_budget, note, flavor_priority=False):
            df = self._apply_filters(
                df_base.copy(), new_category, new_strain_type, effects, exclude_effects, exclude_categories,
                new_min_thc, new_max_thc, new_max_price, new_budget, time_of_day,
                activity_scenario, unit_weight, new_query, is_beginner,
            )
            if flavor_priority and new_query and not df.empty and "FlavorProfile" in df.columns:
                # Sort: FlavorProfile matches first, then by price proximity
                df = df.copy()
                df["_flv_match"] = df["FlavorProfile"].str.contains(new_query, case=False, na=False).astype(int)
                if new_budget is not None:
                    df["_price_dist"] = (df["Price"].fillna(0) - new_budget).abs()
                    df = df.sort_values(["_flv_match", "_price_dist"], ascending=[False, True])
                    df = df.drop(columns=["_price_dist"])
                else:
                    df = df.sort_values("_flv_match", ascending=False)
                df = df.drop(columns=["_flv_match"])
            else:
                df = self._sort_results(df, new_budget)
            result = self._build_result(df, limit)
            if result["total"] > 0:
                result["fallback_note"] = note
                return result
            return None

        # Fallback 1: remove strain_type AND category to find flavor matches across all forms
        if strain_type:
            label = f"{strain_type.capitalize()} {category}" if category else strain_type.capitalize()
            note = (
                f"No {label} products matched your criteria. "
                "Showing closest flavor matches across all strain types and forms."
            )
            result = _run(None, None, query, min_thc, max_thc, max_price, budget_target, note,
                          flavor_priority=bool(query))
            if result:
                return result

        # Fallback 2: widen THC range by ±5%
        if min_thc is not None or max_thc is not None:
            new_min = (min_thc - 5) if min_thc is not None else None
            new_max = (max_thc + 5) if max_thc is not None else None
            note = (
                "No products matched the requested THC range. "
                "Showing nearby options (±5% THC)."
            )
            result = _run(category, strain_type, query, new_min, new_max, max_price, budget_target, note)
            if result:
                return result

        # Fallback 3: relax price by +$15
        if max_price is not None or budget_target is not None:
            new_max_price = (max_price + 15) if max_price is not None else None
            new_budget = (budget_target + 15) if budget_target is not None else None
            note = (
                f"No products found within the original budget. "
                f"Showing options up to ${int((max_price or budget_target) + 15)}."
            )
            result = _run(category, strain_type, query, min_thc, max_thc, new_max_price, new_budget, note)
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
        mask = df["Categories"] != "Concentrates"

        # Rule 2: experience level (optional)
        if experience_levels is not None:
            mask &= df["ExperienceLevel"].isin(experience_levels)

        # Rule 3: Edibles THC <= 5mg
        edibles_mask = (df["THCUnit"] == "mg") & (
            df["THCLevel"] > limits["edibles_mg"]
        )
        mask &= ~edibles_mask

        # Rule 4: Flower/Pre-rolls THC <= 20%
        flower_cats = {"Flower", "Pre-rolls"}
        flower_mask = (
            df["THCUnit"] == "%"
        ) & df["Categories"].isin(flower_cats) & (
            df["THCLevel"] > limits["flower_percent"]
        )
        mask &= ~flower_mask

        # Rule 5: Vaporizers THC <= 70%
        vape_mask = (df["THCUnit"] == "%") & (
            df["Categories"] == "Vaporizers"
        ) & (df["THCLevel"] > limits["vaporizers_percent"])
        mask &= ~vape_mask

        return df[mask].copy()
