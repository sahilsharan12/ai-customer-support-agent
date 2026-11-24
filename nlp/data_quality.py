
import pandas as pd
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

DATASET_PATH = (
    PROJECT_ROOT / "data" / "raw" / "bitext" / "data"
    / "Bitext_Sample_Customer_Support_Training_Dataset_27K_responses-v11.csv"
)

df = pd.read_csv(DATASET_PATH)

print("\n========== TEXT QUALITY ANALYSIS ==========")

# 1. Check duplicate customer instructions
print("\n1. Duplicate Instructions:")
print(df["instruction"].duplicated().sum())

# 2. Check unique customer instructions
print("\n2. Unique Instructions:")
print(df["instruction"].nunique())

# 3. Check flags distribution
print("\n3. Flags Distribution:")
print(df["flags"].value_counts().head(20).to_string())

# 4. Check template placeholders
placeholder_count = df["instruction"].str.contains(
    r"\{\{.*?\}\}", regex=True
).sum()

print("\n4. Messages containing placeholders:")
print(placeholder_count)

# 5. Check instruction length
df["instruction_length"] = df["instruction"].str.len()

print("\n5. Instruction Length Statistics:")
print(df["instruction_length"].describe())

# 6. Display examples for selected intents
selected_intents = [
    "cancel_order",
    "track_order",
    "get_refund",
    "payment_issue"
]

print("\n6. Sample Messages by Intent:")

for intent in selected_intents:

    samples = df.loc[
        df["intent"] == intent, "instruction"
    ].head(3)

    print(f"\nIntent: {intent}")

    for sample in samples:
        print("-", sample)

print("\n========== QUALITY ANALYSIS COMPLETED ==========")
