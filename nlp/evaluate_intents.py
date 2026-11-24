import argparse
import json
from pathlib import Path

import pandas as pd
from sklearn.metrics import accuracy_score, f1_score

from backend.intent_classifier import intent_model, tfidf_vectorizer


SPLITS_DIR = Path(__file__).resolve().parents[1] / "data" / "processed" / "splits"


def normalize(messages: pd.Series) -> pd.Series:
    return messages.str.casefold().str.replace(r"\s+", " ", regex=True).str.strip()


def evaluate(test_path: Path, train_path: Path) -> dict:
    test = pd.read_csv(test_path)
    train = pd.read_csv(train_path)
    test = test.dropna(subset=["instruction", "intent"])
    overlap = normalize(test["instruction"]).isin(normalize(train["instruction"].dropna()))
    held_out = test.loc[~overlap]
    if held_out.empty:
        raise ValueError("No held-out examples remain after excluding overlapping instructions.")

    predictions = []
    for start in range(0, len(held_out), 512):
        batch = held_out["instruction"].iloc[start:start + 512]
        predictions.extend(intent_model.predict(tfidf_vectorizer.transform(batch)))

    truth = held_out["intent"]
    return {
        "held_out_examples": len(held_out),
        "excluded_training_overlaps": int(overlap.sum()),
        "classes": int(truth.nunique()),
        "accuracy": round(float(accuracy_score(truth, predictions)), 4),
        "macro_f1": round(float(f1_score(truth, predictions, average="macro", zero_division=0)), 4),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Evaluate the shipped intent classifier against the held-out split.")
    parser.add_argument("--test", type=Path, default=SPLITS_DIR / "test.csv")
    parser.add_argument("--train", type=Path, default=SPLITS_DIR / "train_augmented.csv")
    args = parser.parse_args()
    print(json.dumps(evaluate(args.test, args.train), indent=2))
