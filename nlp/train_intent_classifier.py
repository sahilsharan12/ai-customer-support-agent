
import pandas as pd
import joblib

from pathlib import Path
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    confusion_matrix
)

# ==========================================
# 1. PATH CONFIGURATION
# ==========================================

PROJECT_ROOT = Path(__file__).resolve().parent.parent

SPLIT_DIR = PROJECT_ROOT / "data" / "processed" / "splits"

MODEL_DIR = PROJECT_ROOT / "models" / "intent_classifier"

MODEL_DIR.mkdir(parents=True, exist_ok=True)


# ==========================================
# 2. LOAD DATASETS
# ==========================================

print("\nLoading datasets...")

# Use augmented training dataset
train_df = pd.read_csv(
    SPLIT_DIR / "train_augmented.csv"
)

# Keep original validation and test datasets
val_df = pd.read_csv(
    SPLIT_DIR / "validation.csv"
)

test_df = pd.read_csv(
    SPLIT_DIR / "test.csv"
)

print("Training records  :", len(train_df))
print("Validation records:", len(val_df))
print("Testing records   :", len(test_df))


# ==========================================
# 3. DATA VALIDATION
# ==========================================

print("\nChecking datasets...")

required_columns = {"instruction", "intent"}

for name, df in [
    ("Training", train_df),
    ("Validation", val_df),
    ("Testing", test_df)
]:
    missing_columns = required_columns - set(df.columns)

    if missing_columns:
        raise ValueError(
            f"{name} dataset is missing columns: {missing_columns}"
        )

    if df["instruction"].isnull().any():
        raise ValueError(f"{name} dataset contains missing instructions.")

    if df["intent"].isnull().any():
        raise ValueError(f"{name} dataset contains missing intent labels.")


# Check that all validation and test labels exist in training
train_labels = set(train_df["intent"])
val_labels = set(val_df["intent"])
test_labels = set(test_df["intent"])

if not val_labels.issubset(train_labels):
    raise ValueError("Validation contains unseen intent labels.")

if not test_labels.issubset(train_labels):
    raise ValueError("Test contains unseen intent labels.")

print("Dataset validation passed!")


# ==========================================
# 4. SEPARATE INPUT AND TARGET
# ==========================================

X_train = train_df["instruction"].astype(str)
y_train = train_df["intent"].astype(str)

X_val = val_df["instruction"].astype(str)
y_val = val_df["intent"].astype(str)

X_test = test_df["instruction"].astype(str)
y_test = test_df["intent"].astype(str)


# ==========================================
# 5. TF-IDF VECTORIZATION
# ==========================================

print("\nApplying TF-IDF vectorization...")

vectorizer = TfidfVectorizer(
    ngram_range=(1, 2),
    max_features=20000,
    sublinear_tf=True
)

# Fit only on augmented training data
X_train_tfidf = vectorizer.fit_transform(X_train)

# Transform validation and test data
X_val_tfidf = vectorizer.transform(X_val)
X_test_tfidf = vectorizer.transform(X_test)

print("Training matrix shape  :", X_train_tfidf.shape)
print("Validation matrix shape:", X_val_tfidf.shape)
print("Testing matrix shape   :", X_test_tfidf.shape)


# ==========================================
# 6. TRAIN LOGISTIC REGRESSION
# ==========================================

print("\nTraining Logistic Regression model...")

model = LogisticRegression(
    max_iter=1000,
    C=1.0,
    class_weight=None,
    random_state=42
)

model.fit(X_train_tfidf, y_train)

print("Model training completed!")


# ==========================================
# 7. VALIDATION EVALUATION
# ==========================================

print("\n========== VALIDATION RESULTS ==========")

val_predictions = model.predict(X_val_tfidf)

val_accuracy = accuracy_score(
    y_val,
    val_predictions
)

print(
    "Validation Accuracy:",
    round(val_accuracy * 100, 2),
    "%"
)

print("\nValidation Classification Report:")

print(
    classification_report(
        y_val,
        val_predictions,
        zero_division=0
    )
)


# ==========================================
# 8. FINAL TEST EVALUATION
# ==========================================

print("\n========== TEST RESULTS ==========")

test_predictions = model.predict(X_test_tfidf)

test_accuracy = accuracy_score(
    y_test,
    test_predictions
)

print(
    "Test Accuracy:",
    round(test_accuracy * 100, 2),
    "%"
)

print("\nTest Classification Report:")

print(
    classification_report(
        y_test,
        test_predictions,
        zero_division=0
    )
)


# ==========================================
# 9. CONFUSION MATRIX
# ==========================================

cm = confusion_matrix(
    y_test,
    test_predictions,
    labels=model.classes_
)

print("\nConfusion Matrix Shape:", cm.shape)


# ==========================================
# 10. SAVE MODEL AND VECTORIZER
# ==========================================

joblib.dump(
    model,
    MODEL_DIR / "intent_model.pkl"
)

joblib.dump(
    vectorizer,
    MODEL_DIR / "tfidf_vectorizer.pkl"
)

joblib.dump(
    list(model.classes_),
    MODEL_DIR / "intent_labels.pkl"
)


# ==========================================
# 11. FINAL SUMMARY
# ==========================================

print("\n========== FINAL SUMMARY ==========")

print("Model              : Logistic Regression")
print("Vectorizer         : TF-IDF")
print("Training dataset   : train_augmented.csv")
print("Validation dataset : validation.csv")
print("Testing dataset    : test.csv")

print("Training records   :", len(train_df))
print("Validation records :", len(val_df))
print("Testing records    :", len(test_df))

print("Number of intents  :", len(model.classes_))

print(
    "Validation accuracy:",
    round(val_accuracy * 100, 2),
    "%"
)

print(
    "Test accuracy      :",
    round(test_accuracy * 100, 2),
    "%"
)

print("\nSaved model files:")
print(MODEL_DIR)

print("\nTraining completed successfully!")
