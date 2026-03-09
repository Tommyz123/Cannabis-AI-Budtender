"""Product data management module for AI Budtender.

Loads the product CSV, builds category indexes, generates compact JSON,
and applies beginner safety filtering with fallback logic.
"""

import json
import pandas as pd
from backend.config import CSV_PATH, BEGINNER_THC_LIMITS

_BEGINNER_EXPERIENCE = {"Beginner", "All Levels"}
_INTERMEDIATE_EXPERIENCE = {"Beginner", "Intermediate", "All Levels"}

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
        effects: list[str] | None = None,
        exclude_effects: list[str] | None = None,
        exclude_categories: list[str] | None = None,
        min_thc: float | None = None,
        max_price: float | None = None,
        budget_target: float | None = None,
        time_of_day: str | None = None,
        activity_scenario: str | None = None,
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

        # list_sub_types: return category overview
        if list_sub_types:
            overview = {}
            for cat, cdf in self._category_index.items():
                subs = cdf["SubCategory"].dropna().unique().tolist()
                overview[cat] = {"count": len(cdf), "subcategories": subs}
            return {"overview": overview}

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

        # 2. Exclude categories
        if exclude_categories:
            excl_lower = [c.lower() for c in exclude_categories]
            df = df[~df["Categories"].str.lower().isin(excl_lower)]

        # 3. Effects filter (Feelings column contains keyword)
        if effects:
            for effect in effects:
                df = df[df["Feelings"].str.contains(effect, case=False, na=False)]

        # 4. Exclude effects
        if exclude_effects:
            for eff in exclude_effects:
                df = df[~df["Feelings"].str.contains(eff, case=False, na=False)]

        # 5. min_thc (percentage products only)
        if min_thc is not None:
            pct_mask = df["THCUnit"] == "%"
            df = df[~pct_mask | (df["THCLevel"] >= min_thc)]

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

        # 10. free-text query (Strain + Types + Feelings + Description)
        if query:
            desc_col = "Description" if "Description" in df.columns else None
            mask = df["Strain"].str.contains(query, case=False, na=False)
            mask |= df["Types"].str.contains(query, case=False, na=False)
            mask |= df["Feelings"].str.contains(query, case=False, na=False)
            if desc_col:
                mask |= df[desc_col].str.contains(query, case=False, na=False)
            df = df[mask]

        # 11. Beginner safety filter
        if is_beginner:
            df = self._apply_beginner_filter(df, _BEGINNER_EXPERIENCE)

        # Limit results
        df = df.head(limit)

        products = [_row_to_compact(row) for _, row in df.iterrows()]
        return {"products": products, "total": len(products)}

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
