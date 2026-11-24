
import pandas as pd
from pathlib import Path

# ==========================================
# 1. LOAD DATASET
# ==========================================

PROJECT_ROOT = Path(__file__).resolve().parent.parent

DATASET_PATH = (
    PROJECT_ROOT / "data" / "raw" / "bitext" / "data"
    / "Bitext_Sample_Customer_Support_Training_Dataset_27K_responses-v11.csv"
)

df = pd.read_csv(DATASET_PATH)

# Normalize text for comparison only
df["normalized_instruction"] = (
    df["instruction"]
    .str.lower()
    .str.strip()
    .str.replace(r"\s+", " ", regex=True)
)


# ==========================================
# 2. EXACT DUPLICATE ANALYSIS
# ==========================================

print("\n========== EXACT DUPLICATE ANALYSIS ==========")

print(
    "Exact duplicate instructions:",
    df["instruction"].duplicated().sum()
)

print(
    "Unique exact instructions:",
    df["instruction"].nunique()
)


# ==========================================
# 3. REPEATED INSTRUCTION GROUPS
# ==========================================

print("\n========== REPEATED INSTRUCTION GROUPS ==========")

repeated = df[
    df.duplicated(
        subset=["normalized_instruction"],
        keep=False
    )
]

repeated_groups = repeated.groupby(
    "normalized_instruction"
)

print("Repeated message groups:", len(repeated_groups))
print("Records belonging to repeated groups:", len(repeated))


# ==========================================
# 4. CHECK CONFLICTING INTENT LABELS
# ==========================================

print("\n========== INTENT CONSISTENCY ==========")

intent_counts = (
    repeated.groupby("normalized_instruction")["intent"]
    .nunique()
)

conflicting_messages = intent_counts[
    intent_counts > 1
]

print(
    "Repeated messages with conflicting intents:",
    len(conflicting_messages)
)

if not conflicting_messages.empty:

    print("\nExamples of conflicting labels:")

    for message in conflicting_messages.index[:10]:

        print("\nMessage:", message)

        examples = repeated[
            repeated["normalized_instruction"] == message
        ][["instruction", "category", "intent"]]

        print(examples.to_string(index=False))

else:
    print("No conflicting intent labels found.")


# ==========================================
# 5. TOP REPEATED MESSAGES
# ==========================================

print("\n========== TOP 10 REPEATED MESSAGES ==========")

top_repeated = (
    df["normalized_instruction"]
    .value_counts()
    .head(10)
)

print(top_repeated.to_string())


# ==========================================
# 6. PLACEHOLDER ANALYSIS BY INTENT
# ==========================================

print("\n========== PLACEHOLDER ANALYSIS ==========")

df["has_placeholder"] = df["instruction"].str.contains(
    r"\{\{.*?\}\}",
    regex=True,
    na=False
)

placeholder_by_intent = (
    df.groupby("intent")["has_placeholder"]
    .agg(["sum", "count"])
)

placeholder_by_intent["percentage"] = (
    placeholder_by_intent["sum"]
    / placeholder_by_intent["count"] * 100
)

print(placeholder_by_intent.to_string())


# ==========================================
# 7. FINAL SUMMARY
# ==========================================

print("\n========== FINAL SUMMARY ==========")

print("Total records:", len(df))
print("Unique normalized messages:", df["normalized_instruction"].nunique())
print("Repeated message groups:", len(repeated_groups))
print("Conflicting intent groups:", len(conflicting_messages))
print("Messages with placeholders:", df["has_placeholder"].sum())

print("\nDuplicate analysis completed!")
