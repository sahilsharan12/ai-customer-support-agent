from backend.database_tools import get_customer_orders


if __name__ == "__main__":
    # Customer ID from the previously tested Olist order
    customer_unique_id = "7c396fd4830fd04220f754e42b4e5bff"

    result = get_customer_orders(customer_unique_id)

    if result:

        print("\nCUSTOMER ORDER HISTORY")
        print("=" * 60)

        print("Customer ID:", result["customer_unique_id"])

        print("Total Orders:", result["total_orders"])

        print("\nOrder Status Summary:")
        print(result["status_summary"])

        print("\nOrders:")

        for order in result["orders"]:

            print("\nOrder ID:", order["order_id"])
            print("Status:", order["order_status"])
            print("Purchase Date:", order["order_purchase_timestamp"])
            print("Estimated Delivery:", order["order_estimated_delivery_date"])

    else:

        print("No orders found for this customer.")
