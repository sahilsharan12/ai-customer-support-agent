
import pandas as pd
from pathlib import Path

from sklearn.model_selection import train_test_split

# ==========================================
# 1. PATH CONFIGURATION
# ==========================================

PROJECT_ROOT = Path(__file__).resolve().parent.parent

INPUT_PATH = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "bitext_preprocessed.csv"
)

OUTPUT_DIR = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "splits"
)

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


# ==========================================
# 2. LOAD PROCESSED DATASET
# ==========================================

print("\nLoading preprocessed dataset...")

df = pd.read_csv(INPUT_PATH)

print("Dataset shape:", df.shape)

# Input and target columns
X = df["processed_instruction"]
y = df["intent"]


# ==========================================
# 3. FIRST SPLIT: 70% TRAIN, 30% TEMP
# ==========================================

X_train, X_temp, y_train, y_temp = train_test_split(
    X,
    y,
    test_size=0.30,
    random_state=42,
    stratify=y
)


# ==========================================
# 4. SECOND SPLIT: 15% VALIDATION, 15% TEST
# ==========================================

X_val, X_test, y_val, y_test = train_test_split(
    X_temp,
    y_temp,
    test_size=0.50,
    random_state=42,
    stratify=y_temp
)


# ==========================================
# 5. CREATE DATAFRAMES
# ==========================================

train_df = pd.DataFrame({
    "instruction": X_train,
    "intent": y_train
})

val_df = pd.DataFrame({
    "instruction": X_val,
    "intent": y_val
})

test_df = pd.DataFrame({
    "instruction": X_test,
    "intent": y_test
})


# ==========================================
# 6. SAVE DATASETS
# ==========================================

train_df.to_csv(OUTPUT_DIR / "train.csv", index=False)
val_df.to_csv(OUTPUT_DIR / "validation.csv", index=False)
test_df.to_csv(OUTPUT_DIR / "test.csv", index=False)


# ==========================================
# 7. DATASET SUMMARY
# ==========================================

print("\n========== DATASET SPLIT SUMMARY ==========")

print(f"Total records      : {len(df)}")
print(f"Training records   : {len(train_df)}")
print(f"Validation records : {len(val_df)}")
print(f"Testing records    : {len(test_df)}")

print("\n========== INTENT DISTRIBUTION ==========")

for name, dataset in [
    ("TRAIN", train_df),
    ("VALIDATION", val_df),
    ("TEST", test_df)
]:
    print(f"\n{name}")
    print(dataset["intent"].value_counts().sort_index().to_string())


# ==========================================
# 8. CHECK DATA LEAKAGE: EXACT TEXT OVERLAP
# ==========================================

train_texts = set(train_df["instruction"])
val_texts = set(val_df["instruction"])
test_texts = set(test_df["instruction"])

print("\n========== EXACT TEXT OVERLAP CHECK ==========")

print("Train-Validation overlap:", len(train_texts & val_texts))
print("Train-Test overlap      :", len(train_texts & test_texts))
print("Validation-Test overlap :", len(val_texts & test_texts))


# ==========================================
# 9. FINAL VALIDATION
# ==========================================

assert len(train_df) + len(val_df) + len(test_df) == len(df)

assert len(train_texts & val_texts) == 0
assert len(train_texts & test_texts) == 0
assert len(val_texts & test_texts) == 0

print("\nAll split checks passed!")
print("Datasets saved successfully:", OUTPUT_DIR)
