
import pandas as pd
from pathlib import Path

# ==========================================
# 1. DATASET PATH
# ==========================================

PROJECT_ROOT = Path(__file__).resolve().parent.parent

DATASET_PATH = (
    PROJECT_ROOT
    / "data"
    / "raw"
    / "bitext"
    / "data"
    / "Bitext_Sample_Customer_Support_Training_Dataset_27K_responses-v11.csv"
)


# ==========================================
# 2. LOAD DATASET
# ==========================================

print("\n" + "=" * 60)
print("       BITEXT CUSTOMER SUPPORT DATASET ANALYSIS")
print("=" * 60)

if not DATASET_PATH.exists():
    raise FileNotFoundError(
        f"Dataset not found: {DATASET_PATH}"
    )

df = pd.read_csv(DATASET_PATH)

print("\nDataset loaded successfully!")

# ==========================================
# 3. BASIC INFORMATION
# ==========================================

print("\n" + "=" * 60)
print("1. BASIC DATASET INFORMATION")
print("=" * 60)

print(f"Total Records       : {df.shape[0]}")
print(f"Total Columns       : {df.shape[1]}")
print(f"Column Names        : {df.columns.tolist()}")

print("\nData Types:")
print(df.dtypes)


# ==========================================
# 4. MISSING VALUES
# ==========================================

print("\n" + "=" * 60)
print("2. MISSING VALUE ANALYSIS")
print("=" * 60)

print(df.isnull().sum())


# ==========================================
# 5. DUPLICATE RECORDS
# ==========================================

print("\n" + "=" * 60)
print("3. DUPLICATE ANALYSIS")
print("=" * 60)

print("Total Duplicate Rows:", df.duplicated().sum())


# ==========================================
# 6. CATEGORY ANALYSIS
# ==========================================

print("\n" + "=" * 60)
print("4. CATEGORY DISTRIBUTION")
print("=" * 60)

print("Unique Categories:", df["category"].nunique())

category_counts = df["category"].value_counts()

print(category_counts.to_string())


# ==========================================
# 7. INTENT ANALYSIS
# ==========================================

print("\n" + "=" * 60)
print("5. INTENT DISTRIBUTION")
print("=" * 60)

print("Unique Intents:", df["intent"].nunique())

intent_counts = df["intent"].value_counts()

print(intent_counts.to_string())


# ==========================================
# 8. INTENT STATISTICS
# ==========================================

print("\n" + "=" * 60)
print("6. INTENT DISTRIBUTION STATISTICS")
print("=" * 60)

print(intent_counts.describe())


# ==========================================
# 9. SAMPLE RECORDS
# ==========================================

print("\n" + "=" * 60)
print("7. SAMPLE CUSTOMER MESSAGES")
print("=" * 60)

for index, row in df.head(5).iterrows():

    print(f"\nRecord {index + 1}")
    print("Customer Message :", row["instruction"])
    print("Category         :", row["category"])
    print("Intent           :", row["intent"])
    print("Response         :", row["response"])


# ==========================================
# 10. FINAL SUMMARY
# ==========================================

print("\n" + "=" * 60)
print("ANALYSIS COMPLETED")
print("=" * 60)

print("Total Records     :", len(df))
print("Total Categories  :", df["category"].nunique())
print("Total Intents     :", df["intent"].nunique())
print("Missing Values    :", df.isnull().sum().sum())
print("Duplicate Rows    :", df.duplicated().sum())

print("\nDataset analysis completed successfully!")
