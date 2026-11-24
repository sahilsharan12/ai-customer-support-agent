from backend.llm import generate_response
from backend.database_tools import get_order_details


if __name__ == "__main__":
    order_id = "e481f51cbdc54678b7cc49136f2d6af7"

    conversation = [
        {
            "role": "user",
            "content": (
                f"My order ID is {order_id}. "
                "According to my order details, it was delivered "
                "on October 10, 2017. "
                "Suppose I reported a damaged product on "
                "October 15, 2017. "
                "Can I request a return and refund under your policy? "
                "Please verify my order and explain the eligibility."
            )
        }
    ]

    print("=" * 60)
    print("TESTING SQL + RAG INTEGRATION")
    print("=" * 60)

    order = get_order_details(order_id)
    if order is None:
        raise RuntimeError("The sample Olist order is unavailable.")
    response = generate_response(conversation, authenticated_customer_id=order["order"]["customer_unique_id"])

    print("\nCUSTOMER QUESTION:")
    print(conversation[-1]["content"])

    print("\nAI RESPONSE:")
    print("=" * 60)
    print(response)
