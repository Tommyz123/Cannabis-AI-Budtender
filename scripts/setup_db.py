"""
Create SQLite database and tables for cannabis AI budtender.
Run once before migration: venv/bin/python scripts/setup_db.py
"""
import sqlite3
import os

DB_PATH = "data/products.db"


def setup_db():
    os.makedirs("data", exist_ok=True)

    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()

    cur.executescript("""
        CREATE TABLE IF NOT EXISTS products (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            product             TEXT NOT NULL,
            brand               TEXT,
            category            TEXT NOT NULL,
            sub_category        TEXT,
            strain_type         TEXT,
            thc_level           REAL,
            price               REAL,
            price_range         TEXT,
            effects             TEXT,
            flavor_profile      TEXT,
            time_of_day         TEXT,
            activity_scenario   TEXT,
            experience_level    TEXT,
            consumption_method  TEXT,
            onset_time          TEXT,
            duration            TEXT,
            unit_weight         TEXT,
            pack_size           INTEGER,
            description         TEXT,
            attributes          TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_category        ON products(category);
        CREATE INDEX IF NOT EXISTS idx_strain_type     ON products(strain_type);
        CREATE INDEX IF NOT EXISTS idx_experience      ON products(experience_level);
        CREATE INDEX IF NOT EXISTS idx_time_of_day     ON products(time_of_day);
        CREATE INDEX IF NOT EXISTS idx_price           ON products(price);
        CREATE INDEX IF NOT EXISTS idx_thc_level       ON products(thc_level);

        CREATE TABLE IF NOT EXISTS sessions (
            session_id  TEXT PRIMARY KEY,
            history     TEXT NOT NULL,
            created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at  DATETIME DEFAULT CURRENT_TIMESTAMP
        );
    """)

    con.commit()
    con.close()
    print(f"Database created: {DB_PATH}")


if __name__ == "__main__":
    setup_db()
