import sqlite3
from contextlib import closing

from backend.config import ORDER_DB_PATH


def add_order_indexes(connection: sqlite3.Connection) -> None:
    connection.executescript("""
        CREATE INDEX IF NOT EXISTS idx_olist_customer_id ON customers(customer_id);
        CREATE INDEX IF NOT EXISTS idx_olist_customer_profile ON customers(customer_unique_id);
        CREATE INDEX IF NOT EXISTS idx_olist_order_id ON orders(order_id);
        CREATE INDEX IF NOT EXISTS idx_olist_order_customer ON orders(customer_id);
        CREATE INDEX IF NOT EXISTS idx_olist_order_items ON order_items(order_id);
        CREATE INDEX IF NOT EXISTS idx_olist_order_payments ON order_payments(order_id);
        CREATE INDEX IF NOT EXISTS idx_olist_product_id ON products(product_id);
        CREATE INDEX IF NOT EXISTS idx_olist_category
            ON product_category_translation(product_category_name);
    """)


if __name__ == "__main__":
    with closing(sqlite3.connect(ORDER_DB_PATH.resolve().as_uri() + "?mode=rw", uri=True)) as db:
        add_order_indexes(db)
        print(f"Order indexes added to {ORDER_DB_PATH}")
