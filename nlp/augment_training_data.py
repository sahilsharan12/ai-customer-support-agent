
import pandas as pd
from pathlib import Path

# ==========================================
# PROJECT PATHS
# ==========================================

PROJECT_ROOT = Path(__file__).resolve().parent.parent

TRAIN_PATH = (
    PROJECT_ROOT / "data" / "processed" /
    "splits" / "train.csv"
)

OUTPUT_PATH = (
    PROJECT_ROOT / "data" / "processed" /
    "splits" / "train_augmented.csv"
)

# ==========================================
# LOAD ORIGINAL TRAINING DATA
# ==========================================

train_df = pd.read_csv(TRAIN_PATH)

print("Original training records:", len(train_df))

# ==========================================
# TARGETED AUGMENTATION EXAMPLES
# ==========================================

new_examples = {

    "track_order": [
        "where is my order",
        "where is my package",
        "can you track my order",
        "track my package",
        "i want to know my order status",
        "what is happening with my order",
        "show me my order tracking status",
        "has my order been shipped",
        "can i get an update on my order",
        "i need to locate my purchase",
        "please check my order status",
        "i want to know where my shipment is",
        "is my order on the way",
        "give me an update about my purchase",
        "help me find my order"
    ],

    "delivery_period": [
        "how long will delivery take",
        "when will my package arrive",
        "what is the estimated delivery time",
        "how many days will shipping take",
        "when can i expect my delivery",
        "how soon will my order arrive",
        "what is the expected arrival date",
        "how long does shipping usually take",
        "when should i receive my package",
        "how much time is needed for delivery",
        "when will the shipment reach me",
        "can you tell me the delivery date",
        "how soon can my item be delivered",
        "what is the expected shipping duration",
        "when can i expect my parcel"
    ],

    "get_refund": [
        "how can i request a refund",
        "i want to get my money back",
        "please help me request a refund",
        "i want to claim a refund",
        "how do i get my payment refunded",
        "i need to request my money back",
        "can i get a refund for my purchase",
        "i want to apply for a refund",
        "help me get a refund for my order",
        "i would like to receive my money back",
        "how can i claim my money back",
        "i want to ask for a reimbursement",
        "please initiate my refund request",
        "i need my purchase amount refunded",
        "how do i request reimbursement"
    ],

    "check_refund_policy": [
        "what is your refund policy",
        "what are the conditions for getting a refund",
        "am i eligible for a refund",
        "under what conditions can i get a refund",
        "what is your money back policy",
        "can you explain your refund rules",
        "how many days do i have to request a refund",
        "what are the refund eligibility requirements",
        "tell me about your return and refund policy",
        "when am i allowed to request a refund",
        "what is the refund period",
        "are there any restrictions on refunds",
        "what are the terms of your refund policy",
        "can i know your refund conditions",
        "explain the rules for getting my money back"
    ]
}

# ==========================================
# CONVERT TO DATAFRAME
# ==========================================

augmentation_records = []

for intent, messages in new_examples.items():

    for message in messages:

        augmentation_records.append({
            "instruction": message,
            "intent": intent
        })

augmentation_df = pd.DataFrame(augmentation_records)

# ==========================================
# REMOVE DUPLICATES
# ==========================================

combined_df = pd.concat(
    [train_df, augmentation_df],
    ignore_index=True
)

combined_df["instruction"] = (
    combined_df["instruction"].str.strip().str.lower()
)

combined_df = combined_df.drop_duplicates(
    subset=["instruction"],
    keep="first"
).reset_index(drop=True)

# ==========================================
# SAVE AUGMENTED DATASET
# ==========================================

OUTPUT_PATH.parent.mkdir(
    parents=True,
    exist_ok=True
)

combined_df.to_csv(OUTPUT_PATH, index=False)

# ==========================================
# SUMMARY
# ==========================================

print("\n========== AUGMENTATION SUMMARY ==========")

print("Original training records :", len(train_df))
print("New examples created      :", len(augmentation_df))
print("Final training records    :", len(combined_df))

print("\nAdded examples by intent:")

print(
    augmentation_df["intent"].value_counts()
)

print("\nFinal intent distribution:")

print(
    combined_df["intent"].value_counts()
)

print("\nSaved to:", OUTPUT_PATH)

print("\nAugmentation completed!")
