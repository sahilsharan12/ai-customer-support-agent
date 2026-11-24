
import pandas as pd
from pathlib import Path

# Project paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent

DATASET_PATH = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "bitext_preprocessed.csv"
)

df = pd.read_csv(DATASET_PATH)

# Intents we want to investigate
target_intents = [
    "track_order",
    "track_refund",
    "delivery_period",
    "cancel_order",
    "get_refund",
    "place_order"
]

print("=" * 70)
print("INTENT EXAMPLES ANALYSIS")
print("=" * 70)

for intent in target_intents:

    examples = df[df["intent"] == intent]

    print(f"\n{'=' * 70}")
    print(f"INTENT: {intent}")
    print(f"Total records: {len(examples)}")
    print("-" * 70)

    # Display 10 random examples
    sample = examples["processed_instruction"].sample(
        n=min(10, len(examples)),
        random_state=42
    )

    for i, message in enumerate(sample, start=1):
        print(f"{i}. {message}")

print("\nAnalysis completed!")
