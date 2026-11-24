
from pathlib import Path
import sqlite3


# ==========================================
# DATABASE CONNECTION
# ==========================================

PROJECT_ROOT = Path(__file__).resolve().parent.parent

DB_PATH = PROJECT_ROOT / "database" / "olist.db"

connection = sqlite3.connect(DB_PATH)
cursor = connection.cursor()


# ==========================================
# HELPER FUNCTIONS
# ==========================================

def get_count(query):
    cursor.execute(query)
    return cursor.fetchone()[0]


def check_duplicates(table, column):

    query = f"""
        SELECT COUNT(*)
        FROM (
            SELECT {column}
            FROM {table}
            GROUP BY {column}
            HAVING COUNT(*) > 1
        )
    """

    return get_count(query)


def check_nulls(table, column):

    query = f"""
        SELECT COUNT(*)
        FROM {table}
        WHERE {column} IS NULL
    """

    return get_count(query)


# ==========================================
# 1. PRIMARY KEY VALIDATION
# ==========================================

primary_keys = {
    "customers": "customer_id",
    "orders": "order_id",
    "products": "product_id",
    "sellers": "seller_id"
}

print("\nPRIMARY KEY VALIDATION")
print("=" * 55)

for table, column in primary_keys.items():

    duplicates = check_duplicates(table, column)

    nulls = check_nulls(table, column)

    print(f"\nTable: {table}")
    print(f"Column: {column}")
    print(f"Duplicate groups: {duplicates}")
    print(f"Null values: {nulls}")


# ==========================================
# 2. FOREIGN KEY VALIDATION
# ==========================================

checks = {

    "Orders without customers": """
        SELECT COUNT(*)
        FROM orders o
        LEFT JOIN customers c
        ON o.customer_id = c.customer_id
        WHERE c.customer_id IS NULL
    """,

    "Order items without orders": """
        SELECT COUNT(*)
        FROM order_items i
        LEFT JOIN orders o
        ON i.order_id = o.order_id
        WHERE o.order_id IS NULL
    """,

    "Order items without products": """
        SELECT COUNT(*)
        FROM order_items i
        LEFT JOIN products p
        ON i.product_id = p.product_id
        WHERE p.product_id IS NULL
    """,

    "Order items without sellers": """
        SELECT COUNT(*)
        FROM order_items i
        LEFT JOIN sellers s
        ON i.seller_id = s.seller_id
        WHERE s.seller_id IS NULL
    """,

    "Payments without orders": """
        SELECT COUNT(*)
        FROM order_payments p
        LEFT JOIN orders o
        ON p.order_id = o.order_id
        WHERE o.order_id IS NULL
    """,

    "Reviews without orders": """
        SELECT COUNT(*)
        FROM order_reviews r
        LEFT JOIN orders o
        ON r.order_id = o.order_id
        WHERE o.order_id IS NULL
    """
}

print("\n\nFOREIGN KEY VALIDATION")
print("=" * 55)

for label, query in checks.items():

    result = get_count(query)

    print(f"{label}: {result}")


# ==========================================
# 3. ORDER STATUS DISTRIBUTION
# ==========================================

print("\n\nORDER STATUS DISTRIBUTION")
print("=" * 55)

cursor.execute("""
    SELECT order_status, COUNT(*)
    FROM orders
    GROUP BY order_status
    ORDER BY COUNT(*) DESC
""")

for status, count in cursor.fetchall():

    print(f"{status}: {count:,}")


# ==========================================
# 4. DATABASE INTEGRITY
# ==========================================

print("\n\nDATABASE INTEGRITY")

cursor.execute("PRAGMA integrity_check")

print(cursor.fetchone()[0])


# ==========================================
# CLOSE CONNECTION
# ==========================================

connection.close()

print("\nValidation completed.")
