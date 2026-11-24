
import pandas as pd
import re
from pathlib import Path

# ==========================================
# 1. PATH CONFIGURATION
# ==========================================

PROJECT_ROOT = Path(__file__).resolve().parent.parent

DATASET_PATH = (
    PROJECT_ROOT / "data" / "raw" / "bitext" / "data"
    / "Bitext_Sample_Customer_Support_Training_Dataset_27K_responses-v11.csv"
)

OUTPUT_PATH = (
    PROJECT_ROOT / "data" / "processed"
    / "bitext_preprocessed.csv"
)


# ==========================================
# 2. TEXT PREPROCESSING FUNCTION
# ==========================================

def preprocess_text(text):

    if not isinstance(text, str):
        return ""

    # Convert text to lowercase
    text = text.lower()

    # Preserve placeholder meaning in standardized form
    text = re.sub(
        r"\{\{\s*(.*?)\s*\}\}",
        lambda match: match.group(1).strip().replace(" ", "_"),
        text
    )

    # Remove extra whitespace
    text = re.sub(r"\s+", " ", text)

    # Remove leading and trailing spaces
    text = text.strip()

    return text


# ==========================================
# 3. LOAD ORIGINAL DATASET
# ==========================================

print("\nLoading Bitext dataset...")

df = pd.read_csv(DATASET_PATH)

print("Original dataset shape:", df.shape)


# ==========================================
# 4. PREPROCESS CUSTOMER INSTRUCTIONS
# ==========================================

print("\nPreprocessing customer instructions...")

df["processed_instruction"] = (
    df["instruction"].apply(preprocess_text)
)


# ==========================================
# 5. CHECK PREPROCESSING RESULTS
# ==========================================

print("\n========== PREPROCESSING EXAMPLES ==========")

for index in range(min(10, len(df))):

    print("\nOriginal:")
    print(df.loc[index, "instruction"])

    print("Processed:")
    print(df.loc[index, "processed_instruction"])


# ==========================================
# 6. CHECK DUPLICATES AFTER NORMALIZATION
# ==========================================

print("\n========== DUPLICATE ANALYSIS ==========")

print(
    "Duplicate processed instructions:",
    df["processed_instruction"].duplicated().sum()
)

print(
    "Unique processed instructions:",
    df["processed_instruction"].nunique()
)


# ==========================================
# 7. CHECK LABEL CONSISTENCY
# ==========================================

label_counts = (
    df.groupby("processed_instruction")["intent"].nunique()
)

conflicts = label_counts[label_counts > 1]

print(
    "Conflicting intent groups:",
    len(conflicts)
)


# ==========================================
# 8. REMOVE EXACT NORMALIZED DUPLICATES
# ==========================================

df = df.drop_duplicates(
    subset=["processed_instruction"],
    keep="first"
).reset_index(drop=True)


# ==========================================
# 9. SAVE PROCESSED DATASET
# ==========================================

OUTPUT_PATH.parent.mkdir(
    parents=True,
    exist_ok=True
)

df.to_csv(OUTPUT_PATH, index=False)

print("\n========== FINAL SUMMARY ==========")

print("Original records       : 26872")
print("Processed records      :", len(df))
print("Unique intents         :", df["intent"].nunique())
print("Remaining duplicates   :", df["processed_instruction"].duplicated().sum())
print("Conflicting labels     :", len(conflicts))

print("\nSaved processed dataset:")
print(OUTPUT_PATH)

print("\nPreprocessing completed successfully!")
