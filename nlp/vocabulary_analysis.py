
import joblib
from pathlib import Path

# Project paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent
MODEL_DIR = PROJECT_ROOT / "models" / "intent_classifier"

# Load trained vectorizer
vectorizer = joblib.load(MODEL_DIR / "tfidf_vectorizer.pkl")

# Get vocabulary
vocabulary = vectorizer.vocabulary_

# Test customer messages
test_messages = [
    "where is my package",
    "track my order",
    "i want to cancel my order",
    "i want to return my product",
    "has my refund been processed",
    "how long will delivery take"
]

print("=" * 70)
print("TF-IDF VOCABULARY COVERAGE ANALYSIS")
print("=" * 70)

for message in test_messages:

    # Convert message into tokens using vectorizer
    analyzer = vectorizer.build_analyzer()
    tokens = analyzer(message)

    known_tokens = [
        token for token in tokens
        if token in vocabulary
    ]

    unknown_tokens = [
        token for token in tokens
        if token not in vocabulary
    ]

    coverage = (
        len(known_tokens) / len(tokens) * 100
        if tokens else 0
    )

    print(f"\nCustomer Message: {message}")
    print(f"Tokens           : {tokens}")
    print(f"Known Tokens     : {known_tokens}")
    print(f"Unknown Tokens   : {unknown_tokens}")
    print(f"Vocabulary Cover : {coverage:.2f}%")

print("\nAnalysis completed!")
