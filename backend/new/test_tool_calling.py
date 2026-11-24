from backend.llm import generate_response
from backend.database_tools import get_order_details


if __name__ == "__main__":
    order_id = "e481f51cbdc54678b7cc49136f2d6af7"

    conversation = [
        {
            "role": "user",
            "content": (
                f"Please check my order with ID {order_id}. "
                "Tell me its order status, purchase date, "
                "actual delivery date, estimated delivery date, "
                "payment details and purchased products. "
                "Use the database information only."
            )
        }
    ]

    print("\nTESTING SPECIFIC ORDER DETAILS TOOL")
    print("=" * 60)

    order = get_order_details(order_id)
    if order is None:
        raise RuntimeError("The sample Olist order is unavailable.")
    response = generate_response(conversation, authenticated_customer_id=order["order"]["customer_unique_id"])

    print("\nCUSTOMER QUESTION")
    print("=" * 60)
    print(conversation[-1]["content"])

    print("\nAI RESPONSE")
    print("=" * 60)
    print(response)
