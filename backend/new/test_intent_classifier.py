from backend.intent_classifier import predict_intent


if __name__ == "__main__":
    test_messages = [
        "Where is my order?",
        "I want to cancel my order.",
        "I need a refund.",
        "How long will delivery take?"
    ]

    for message in test_messages:
        result = predict_intent(message)

        print("\nCustomer:", message)
        print("Prediction:", result["intent"])
        print("Confidence:", result["confidence"])
        print("Top 3:", result["top_predictions"])
