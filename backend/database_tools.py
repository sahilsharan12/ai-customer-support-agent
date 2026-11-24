
import sqlite3
from contextlib import closing

from backend.config import ORDER_DB_PATH


# ==========================================
# DATABASE CONFIGURATION
# ==========================================

DB_PATH = ORDER_DB_PATH


# ==========================================
# DATABASE CONNECTION
# ==========================================

def get_db_connection():

    connection = sqlite3.connect(DB_PATH.resolve().as_uri() + "?mode=ro", uri=True)

    connection.row_factory = sqlite3.Row

    return connection


def customer_identity_exists(customer_unique_id: str) -> bool:
    with closing(get_db_connection()) as connection:
        return connection.execute(
            "SELECT 1 FROM customers WHERE customer_unique_id = ? LIMIT 1",
            (customer_unique_id,),
        ).fetchone() is not None


# ==========================================
# GET ORDER DETAILS
# ==========================================


def get_order_details(order_id: str):

    if not isinstance(order_id, str) or not order_id.strip():
        raise ValueError("Valid order ID is required.")

    order_id = order_id.strip()

    connection = get_db_connection()

    try:

        cursor = connection.cursor()

        # ----------------------------------
        # 1. ORDER AND CUSTOMER DETAILS
        # ----------------------------------

        cursor.execute("""
            SELECT
                o.order_id,
                o.order_status,
                o.order_purchase_timestamp,
                o.order_approved_at,
                o.order_delivered_carrier_date,
                o.order_delivered_customer_date,
                o.order_estimated_delivery_date,

                c.customer_id,
                c.customer_unique_id,
                c.customer_city,
                c.customer_state

            FROM orders o

            JOIN customers c
                ON o.customer_id = c.customer_id

            WHERE o.order_id = ?

        """, (order_id,))

        order = cursor.fetchone()

        if order is None:
            return None

        # ----------------------------------
        # 2. PAYMENT DETAILS
        # ----------------------------------

        cursor.execute("""
            SELECT
                payment_type,
                payment_installments,
                payment_value

            FROM order_payments

            WHERE order_id = ?

            ORDER BY payment_sequential

        """, (order_id,))

        payments = [
            dict(row) for row in cursor.fetchall()
        ]

        # ----------------------------------
        # 3. PURCHASED PRODUCTS
        # ----------------------------------

        cursor.execute("""
            SELECT
                oi.order_item_id,
                oi.product_id,
                oi.seller_id,
                oi.price,
                oi.freight_value,

                p.product_category_name,
                t.product_category_name_english

            FROM order_items oi

            LEFT JOIN products p
                ON oi.product_id = p.product_id

            LEFT JOIN product_category_translation t
                ON p.product_category_name =
                   t.product_category_name

            WHERE oi.order_id = ?

            ORDER BY oi.order_item_id

        """, (order_id,))

        products = [
            dict(row) for row in cursor.fetchall()
        ]

        # ----------------------------------
        # 4. ORDER SUMMARY
        # ----------------------------------

        total_items = len(products)

        total_product_value = sum(
            float(item["price"] or 0)
            for item in products
        )

        total_freight = sum(
            float(item["freight_value"] or 0)
            for item in products
        )

        total_paid = sum(
            float(payment["payment_value"] or 0)
            for payment in payments
        )

        # ----------------------------------
        # 5. FINAL RESPONSE
        # ----------------------------------

        return {

            "order": dict(order),

            "summary": {
                "total_items": total_items,
                "total_product_value": round(
                    total_product_value, 2
                ),
                "total_freight": round(
                    total_freight, 2
                ),
                "total_paid": round(
                    total_paid, 2
                ),
                "currency": "BRL"
            },

            "payments": payments,

            "products": products,

            "currency": "BRL",

            "data_source": (
                "Historical Olist Brazilian E-Commerce dataset "
                "(2016-2018)"
            )

        }

    finally:
        connection.close()


# ==========================================
# GET CUSTOMER ORDER HISTORY
# ==========================================

def get_customer_orders(
    customer_unique_id: str,
    limit: int = 20,
    offset: int = 0
):

    # ----------------------------------
    # 1. INPUT VALIDATION
    # ----------------------------------

    if (
        not isinstance(customer_unique_id, str)
        or not customer_unique_id.strip()
    ):
        raise ValueError("Valid customer ID is required.")

    if not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ValueError("Limit must be between 1 and 100.")

    if not isinstance(offset, int) or offset < 0:
        raise ValueError("Offset cannot be negative.")

    customer_unique_id = customer_unique_id.strip()

    connection = get_db_connection()

    try:

        cursor = connection.cursor()

        # ----------------------------------
        # 2. GET TOTAL ORDER COUNT
        # ----------------------------------

        cursor.execute("""
            SELECT COUNT(*) AS total_orders

            FROM customers c

            JOIN orders o
                ON c.customer_id = o.customer_id

            WHERE c.customer_unique_id = ?

        """, (customer_unique_id,))

        total_orders = cursor.fetchone()["total_orders"]

        # ----------------------------------
        # 3. GET PAGINATED ORDER HISTORY
        # ----------------------------------

        cursor.execute("""
            SELECT
                c.customer_unique_id,
                o.order_id,
                o.order_status,
                o.order_purchase_timestamp,
                o.order_delivered_customer_date,
                o.order_estimated_delivery_date

            FROM customers c

            JOIN orders o
                ON c.customer_id = o.customer_id

            WHERE c.customer_unique_id = ?

            ORDER BY
                o.order_purchase_timestamp DESC,
                o.order_id DESC

            LIMIT ? OFFSET ?

        """, (
            customer_unique_id,
            limit,
            offset
        ))

        orders = [
            dict(row) for row in cursor.fetchall()
        ]

        # ----------------------------------
        # 4. ORDER STATUS SUMMARY
        # ----------------------------------

        cursor.execute("""
            SELECT
                o.order_status,
                COUNT(*) AS total

            FROM customers c

            JOIN orders o
                ON c.customer_id = o.customer_id

            WHERE c.customer_unique_id = ?

            GROUP BY o.order_status

        """, (customer_unique_id,))

        status_summary = {
            row["order_status"]: row["total"]
            for row in cursor.fetchall()
        }

        # ----------------------------------
        # 5. FINAL RESPONSE
        # ----------------------------------

        return {

            "customer_unique_id": customer_unique_id,

            "total_orders": total_orders,

            "limit": limit,

            "offset": offset,

            "returned_orders": len(orders),

            "status_summary": status_summary,

            "orders": orders,

            "data_source": "Historical Olist dataset"

        }

    finally:

        connection.close()
