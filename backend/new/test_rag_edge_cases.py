from backend.llm import generate_response


if __name__ == "__main__":
    conversation = [
        {
            "role": "user",
            "content": (
                "I purchased a product 30 days ago. "
                "Can I still return it? "
                "Does your policy allow returns after 30 days?"
            )
        }
    ]

    print("=" * 60)
    print("TESTING RAG POLICY EDGE CASE")
    print("=" * 60)

    response = generate_response(conversation)

    print("\nCUSTOMER QUESTION:")
    print(conversation[-1]["content"])

    print("\nAI RESPONSE:")
    print("=" * 60)
    print(response)
