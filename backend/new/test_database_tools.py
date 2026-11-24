from backend.database_tools import get_order_details


if __name__ == "__main__":
    # Sample order ID from the Olist dataset
    order_id = "e481f51cbdc54678b7cc49136f2d6af7"

    result = get_order_details(order_id)

    if result:

        print("\nORDER DETAILS")
        print("=" * 50)

        print(result)

    else:

        print("Order not found.")
