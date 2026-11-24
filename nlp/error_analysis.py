
import pandas as pd
from pathlib import Path

# Project paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent

RESULT_PATH = (
    PROJECT_ROOT / "data" / "processed" /
    "clean_benchmark_results.csv"
)

# Load results if saved
if not RESULT_PATH.exists():
    raise FileNotFoundError(
        "Please save results_df from your notebook first."
    )

df = pd.read_csv(RESULT_PATH)

# ==========================================
# 1. BASELINE ERRORS
# ==========================================

baseline_errors = df[
    df["Baseline Correct"] == False
]

print("=" * 75)
print("BASELINE MODEL ERRORS")
print("=" * 75)

print(
    baseline_errors[
        [
            "Customer Message",
            "Expected Intent",
            "Baseline Prediction",
            "Baseline Confidence"
        ]
    ]
)

# ==========================================
# 2. AUGMENTED MODEL ERRORS
# ==========================================

augmented_errors = df[
    df["Augmented Correct"] == False
]

print("\n" + "=" * 75)
print("AUGMENTED MODEL ERRORS")
print("=" * 75)

print(
    augmented_errors[
        [
            "Customer Message",
            "Expected Intent",
            "Augmented Prediction",
            "Augmented Confidence"
        ]
    ]
)

# ==========================================
# 3. CONFUSION PATTERNS
# ==========================================

print("\n" + "=" * 75)
print("AUGMENTED MODEL CONFUSION PATTERNS")
print("=" * 75)

confusion_summary = (
    augmented_errors.groupby(
        ["Expected Intent", "Augmented Prediction"]
    )
    .size()
    .reset_index(name="Error Count")
    .sort_values("Error Count", ascending=False)
)

print(confusion_summary)

# ==========================================
# 4. SAVE RESULTS
# ==========================================

OUTPUT_PATH = (
    PROJECT_ROOT / "data" / "processed" /
    "augmented_model_errors.csv"
)

augmented_errors.to_csv(
    OUTPUT_PATH,
    index=False
)

print("\nError analysis saved to:", OUTPUT_PATH)
