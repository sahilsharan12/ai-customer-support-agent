from backend.llm import generate_response


if __name__ == "__main__":
    conversation = [
        {
            "role": "user",
            "content": (
                "I received a damaged product. "
                "Can I return it and get a refund? "
                "What is the return policy?"
            )
        }
    ]

    print("=" * 60)
    print("TESTING RAG + QWEN INTEGRATION")
    print("=" * 60)

    response = generate_response(conversation)

    print("\nCUSTOMER QUESTION:")
    print(conversation[-1]["content"])

    print("\nQWEN RESPONSE:")
    print("=" * 60)
    print(response)
