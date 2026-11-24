
from pathlib import Path
import joblib


# ==========================================
# 1. PROJECT PATHS
# ==========================================

PROJECT_ROOT = Path(__file__).resolve().parent.parent

MODEL_DIR = PROJECT_ROOT / "models" / "intent_classifier"

MODEL_PATH = MODEL_DIR / "intent_model.pkl"
VECTORIZER_PATH = MODEL_DIR / "tfidf_vectorizer.pkl"
LABELS_PATH = MODEL_DIR / "intent_labels.pkl"


# ==========================================
# 2. CHECK MODEL FILES
# ==========================================

required_files = [
    MODEL_PATH,
    VECTORIZER_PATH,
    LABELS_PATH
]

for file_path in required_files:
    if not file_path.exists():
        raise FileNotFoundError(
            f"Required model file not found: {file_path}"
        )


# ==========================================
# 3. LOAD TRAINED MODEL
# ==========================================

intent_model = joblib.load(MODEL_PATH)

tfidf_vectorizer = joblib.load(VECTORIZER_PATH)

intent_labels = joblib.load(LABELS_PATH)


# ==========================================
# 4. PREDICT CUSTOMER INTENT
# ==========================================

def predict_intent(message: str) -> dict:

    if not isinstance(message, str) or not message.strip():
        raise ValueError("Customer message cannot be empty.")

    # Convert customer message into TF-IDF features
    message_vector = tfidf_vectorizer.transform([message])

    # Predict intent
    predicted_class = intent_model.predict(message_vector)[0]

    # Get prediction probabilities
    probabilities = intent_model.predict_proba(message_vector)[0]

    # Highest confidence
    confidence = float(max(probabilities))

    # Get top 3 predictions
    top_indices = probabilities.argsort()[-3:][::-1]

    top_predictions = []

    for index in top_indices:

        top_predictions.append({
            "intent": str(intent_model.classes_[index]),
            "confidence": round(
                float(probabilities[index]), 4
            )
        })

    # Final response
    return {
        "intent": str(predicted_class),
        "confidence": round(confidence, 4),
        "top_predictions": top_predictions
    }


# ==========================================
# 5. MODULE TEST
# ==========================================

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
        print("Predicted Intent:", result["intent"])
        print("Confidence:", result["confidence"])
        print("Top Predictions:", result["top_predictions"])
