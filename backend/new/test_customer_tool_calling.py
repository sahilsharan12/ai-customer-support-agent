from backend.llm import generate_response


if __name__ == "__main__":
    customer_unique_id = "7c396fd4830fd04220f754e42b4e5bff"

    conversation_history = [
        {
            "role": "user",
            "content": (
                "Please show me all my previous orders, "
                "including their order IDs, status, and purchase dates."
            )
        }
    ]

    print("\nTesting Customer Order History Tool")
    print("=" * 60)

    response = generate_response(conversation_history, authenticated_customer_id=customer_unique_id)

    print("\nQWEN RESPONSE:")
    print("=" * 60)
    print(response)
