"""
Seed deterministic mock sale data on the products table.

Marks ~20% of products (43 of 217) as on-sale with a discount uniformly chosen
from {10, 15, 20, 25}%. Uses a fixed RNG seed (42) so re-runs select the same
ids and produce identical discounts -- this is what makes the script
idempotent.

Run after `setup_db.py` + `migrate_csv_to_sqlite.py`:
    venv/bin/python scripts/seed_sale_data.py
"""
import math
import os
import random
import sqlite3

DB_PATH = os.environ.get("DB_PATH", "data/products.db")

SALE_RATIO = 0.20
DISCOUNT_CHOICES = [10, 15, 20, 25]
RNG_SEED = 42


def seed_sale_data(db_path: str = DB_PATH) -> None:
    con = sqlite3.connect(db_path)
    cur = con.cursor()

    # Reset any prior sale state so the seed is the single source of truth.
    cur.execute("UPDATE products SET is_on_sale = 0, discount_pct = 0")

    cur.execute("SELECT id FROM products ORDER BY id")
    all_ids = [row[0] for row in cur.fetchall()]
    if not all_ids:
        con.close()
        print("Seeded 0 products on sale (products table empty)")
        return

    sale_count = math.floor(len(all_ids) * SALE_RATIO)

    rng = random.Random(RNG_SEED)
    sale_ids = rng.sample(all_ids, sale_count)

    applied_discounts: list[int] = []
    for pid in sale_ids:
        disc = rng.choice(DISCOUNT_CHOICES)
        applied_discounts.append(disc)
        cur.execute(
            "UPDATE products SET is_on_sale = 1, discount_pct = ? WHERE id = ?",
            (disc, pid),
        )

    con.commit()
    con.close()

    if applied_discounts:
        lo, hi = min(applied_discounts), max(applied_discounts)
        print(f"Seeded {sale_count} products on sale (discount range: {lo}-{hi}%)")
    else:
        print("Seeded 0 products on sale (discount range: 0-0%)")


if __name__ == "__main__":
    seed_sale_data()
