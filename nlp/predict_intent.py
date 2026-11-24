
import joblib
from pathlib import Path

# ==========================================
# PROJECT PATHS
# ==========================================

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MODEL_DIR = PROJECT_ROOT / "models" / "intent_classifier"

# ==========================================
# LOAD TRAINED MODEL
# ==========================================

model = joblib.load(MODEL_DIR / "intent_model.pkl")
vectorizer = joblib.load(MODEL_DIR / "tfidf_vectorizer.pkl")


# ==========================================
# INTENT PREDICTION FUNCTION
# ==========================================

def predict_intent(message):

    # Convert customer message into TF-IDF features
    message_vector = vectorizer.transform([message])

    # Get probability for every intent
    probabilities = model.predict_proba(message_vector)[0]

    # Get indices of top 3 predictions
    top_indices = probabilities.argsort()[-3:][::-1]

    print("\n========== INTENT PREDICTIONS ==========")

    for rank, index in enumerate(top_indices, start=1):

        intent = model.classes_[index]
        confidence = probabilities[index] * 100

        print(
            f"{rank}. {intent:<30} "
            f"Confidence: {confidence:.2f}%"
        )

    # Return the highest probability prediction
    best_index = top_indices[0]

    return (
        model.classes_[best_index],
        probabilities[best_index] * 100
    )


# ==========================================
# MAIN PROGRAM
# ==========================================

if __name__ == "__main__":

    print("=" * 50)
    print("CUSTOMER SUPPORT INTENT CLASSIFIER")
    print("Type 'exit' to stop")
    print("=" * 50)

    while True:

        message = input("\nCustomer: ").strip()

        if message.lower() == "exit":
            print("\nClassifier stopped.")
            break

        if not message:
            print("Please enter a customer message.")
            continue

        predicted_intent, confidence = predict_intent(message)

        print("\n========== FINAL PREDICTION ==========")
        print(f"Predicted Intent : {predicted_intent}")
        print(f"Confidence       : {confidence:.2f}%")
        print("=" * 50)
