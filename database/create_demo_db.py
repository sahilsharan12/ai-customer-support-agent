import argparse
import sqlite3
from contextlib import closing
from datetime import date, timedelta
from pathlib import Path

from database.order_indexes import add_order_indexes


DEMO_PROFILE = "demo-customer-001"
DEMO_ORDERS = ("demo-order-1001", "demo-order-1002", "demo-order-1003")


def create_demo_db(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb"):
        pass
    with closing(sqlite3.connect(path)) as db, db:
        db.executescript("""
            CREATE TABLE customers (
                customer_id TEXT PRIMARY KEY, customer_unique_id TEXT,
                customer_city TEXT, customer_state TEXT
            );
            CREATE TABLE orders (
                order_id TEXT PRIMARY KEY, customer_id TEXT, order_status TEXT,
                order_purchase_timestamp TEXT, order_approved_at TEXT,
                order_delivered_carrier_date TEXT, order_delivered_customer_date TEXT,
                order_estimated_delivery_date TEXT
            );
            CREATE TABLE order_payments (
                order_id TEXT, payment_sequential INTEGER, payment_type TEXT,
                payment_installments INTEGER, payment_value REAL
            );
            CREATE TABLE order_items (
                order_id TEXT, order_item_id INTEGER, product_id TEXT,
                seller_id TEXT, price REAL, freight_value REAL
            );
            CREATE TABLE products (product_id TEXT, product_category_name TEXT);
            CREATE TABLE product_category_translation (
                product_category_name TEXT, product_category_name_english TEXT
            );
        """)
        add_order_indexes(db)
        today = date.today()
        paid = (today - timedelta(days=3)).isoformat()
        shipped = (today - timedelta(days=2)).isoformat()
        delivered = (today - timedelta(days=1)).isoformat()
        db.execute("INSERT INTO customers VALUES (?, ?, ?, ?)", ("demo-cart", DEMO_PROFILE, "Demo City", "SP"))
        db.execute("INSERT INTO products VALUES (?, ?)", ("demo-product", "accessories"))
        db.execute("INSERT INTO product_category_translation VALUES (?, ?)", ("accessories", "Accessories"))
        for order_id in DEMO_ORDERS:
            db.execute(
                "INSERT INTO orders VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (order_id, "demo-cart", "delivered", paid, paid, shipped, delivered, today.isoformat()),
            )
            db.execute("INSERT INTO order_payments VALUES (?, 1, 'credit_card', 1, 100)", (order_id,))
            db.execute("INSERT INTO order_items VALUES (?, 1, 'demo-product', 'demo-seller', 90, 10)", (order_id,))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Create a separate SQLite database with recent synthetic orders.")
    parser.add_argument("--output", type=Path, default=Path("database/demo_orders.db"))
    args = parser.parse_args()
    try:
        create_demo_db(args.output)
    except FileExistsError:
        parser.exit(1, f"{args.output} already exists. Choose a new output path.\n")
    print(f"Created {args.output} for profile {DEMO_PROFILE}.")
    print("Demo order IDs:", ", ".join(DEMO_ORDERS))
