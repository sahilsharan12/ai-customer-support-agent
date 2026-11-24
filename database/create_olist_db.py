
from pathlib import Path
import sqlite3
import pandas as pd
from database.order_indexes import add_order_indexes
from backend.config import ORDER_DB_PATH


# ==========================================
# 1. PROJECT PATHS
# ==========================================

PROJECT_ROOT = Path(__file__).resolve().parent.parent

OLIST_DIR = (
    PROJECT_ROOT
    / "data"
    / "raw"
    / "olist"
    / "archive"
)

DB_PATH = ORDER_DB_PATH
DB_PATH.parent.mkdir(parents=True, exist_ok=True)


# ==========================================
# 2. CSV FILE MAPPING
# ==========================================

TABLES = {
    "olist_customers_dataset.csv": "customers",
    "olist_orders_dataset.csv": "orders",
    "olist_order_items_dataset.csv": "order_items",
    "olist_order_payments_dataset.csv": "order_payments",
    "olist_order_reviews_dataset.csv": "order_reviews",
    "olist_products_dataset.csv": "products",
    "olist_sellers_dataset.csv": "sellers",
    "olist_geolocation_dataset.csv": "geolocation",
    "product_category_name_translation.csv":
        "product_category_translation"
}


# ==========================================
# 3. VALIDATE SOURCE FILES
# ==========================================

if not OLIST_DIR.exists():
    raise FileNotFoundError(
        f"Olist directory not found: {OLIST_DIR}"
    )

for filename in TABLES:

    file_path = OLIST_DIR / filename

    if not file_path.exists():
        raise FileNotFoundError(
            f"Missing CSV file: {file_path}"
        )


# ==========================================
# 4. CREATE SQLITE DATABASE
# ==========================================

with sqlite3.connect(DB_PATH) as connection:

    for filename, table_name in TABLES.items():

        csv_path = OLIST_DIR / filename

        print(f"\nImporting: {filename}")

        df = pd.read_csv(csv_path)

        # Import CSV into SQLite
        df.to_sql(
            table_name,
            connection,
            if_exists="replace",
            index=False
        )

        print(f"Table: {table_name}")
        print(f"Rows: {len(df):,}")
        print(f"Columns: {len(df.columns)}")

    # Enable foreign key enforcement for future operations
    connection.execute("PRAGMA foreign_keys = ON")

    add_order_indexes(connection)
    print("\nDatabase creation completed.")


# ==========================================
# 5. VERIFY DATABASE
# ==========================================

with sqlite3.connect(DB_PATH) as connection:

    cursor = connection.cursor()

    cursor.execute("""
        SELECT name
        FROM sqlite_master
        WHERE type = 'table'
        ORDER BY name
    """)

    tables = cursor.fetchall()

    print("\nDATABASE TABLES")

    for table in tables:

        table_name = table[0]

        cursor.execute(
            f'SELECT COUNT(*) FROM "{table_name}"'
        )

        count = cursor.fetchone()[0]

        print(f"{table_name}: {count:,} rows")


print(f"\nDatabase saved at: {DB_PATH}")
