
import os
import csv
import json
import zipfile
import gzip
from pathlib import Path
from collections import Counter

# =====================================================
# PROJECT CONFIGURATION
# =====================================================

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data" / "raw"

DATASETS = {
    "Bitext Customer Support": "bitext",
    "ABCD Conversations": "abcd",
    "Banking77": "banking77",
    "CLINC150": "clinc150",
    "Olist E-Commerce": "olist",
    "Voice Datasets": "voice",
}

SKIP_DIRS = {".git", "__pycache__"}

# =====================================================
# HELPER FUNCTIONS
# =====================================================

def format_size(size):
    units = ["B", "KB", "MB", "GB", "TB"]

    for unit in units:
        if size < 1024:
            return f"{size:.2f} {unit}"
        size /= 1024

    return f"{size:.2f} PB"


def get_files(folder):
    files = []

    if not folder.exists():
        return files

    for root, dirs, filenames in os.walk(folder):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]

        for filename in filenames:
            path = Path(root) / filename

            if path.is_file():
                files.append(path)

    return files


def inspect_csv(file_path):
    print("\n      CSV INFORMATION")

    try:
        with open(
            file_path,
            "r",
            encoding="utf-8-sig",
            newline=""
        ) as f:

            reader = csv.reader(f)

            header = next(reader, None)

            if header is None:
                print("      Empty CSV file")
                return

            row_count = sum(1 for _ in reader)

            print(f"      Columns     : {len(header)}")
            print(f"      Data rows   : {row_count:,}")
            print(f"      Column names: {header}")

    except Exception as e:
        print(f"      CSV Error: {e}")


def inspect_parquet(file_path):
    print("\n      PARQUET INFORMATION")

    try:
        import pandas as pd

        df = pd.read_parquet(file_path)

        print(f"      Rows        : {len(df):,}")
        print(f"      Columns     : {len(df.columns)}")
        print(f"      Column names: {df.columns.tolist()}")

    except ImportError:
        print("      pandas is not installed.")

    except Exception as e:
        print(f"      Parquet inspection unavailable: {e}")


def inspect_json(file_path):
    print("\n      JSON INFORMATION")

    try:
        # Read only the opening portion to identify JSON structure.
        with open(file_path, "r", encoding="utf-8") as f:
            start = f.read(100000).lstrip()

        if not start:
            print("      Empty JSON file")
            return

        if start.startswith("{"):
            print("      JSON structure: Object / Dictionary")

        elif start.startswith("["):
            print("      JSON structure: Array / List")

        else:
            print("      JSON structure: Other")

        print("      JSON file detected successfully.")

    except Exception as e:
        print(f"      JSON Error: {e}")


def inspect_zip(file_path):
    print("\n      ZIP INFORMATION")

    try:
        with zipfile.ZipFile(file_path, "r") as z:
            members = z.infolist()

            print(f"      Archived files: {len(members)}")

            bad_file = z.testzip()

            if bad_file:
                print(f"      Corrupted file: {bad_file}")
            else:
                print("      ZIP integrity: OK")

    except Exception as e:
        print(f"      ZIP Error: {e}")


# =====================================================
# MAIN DATASET CHECK
# =====================================================

def main():

    print("\n" + "=" * 75)
    print("       AI CUSTOMER SUPPORT AGENT - DATASET REPORT")
    print("=" * 75)

    if not DATA_DIR.exists():
        print(f"\nData directory not found: {DATA_DIR}")
        return

    overall_files = 0
    overall_size = 0

    extension_summary = Counter()

    for dataset_name, folder_name in DATASETS.items():

        folder = DATA_DIR / folder_name

        print("\n" + "-" * 75)
        print(f"DATASET: {dataset_name}")
        print(f"PATH   : {folder}")
        print("-" * 75)

        if not folder.exists():
            print("STATUS : NOT DOWNLOADED")
            continue

        files = get_files(folder)

        if not files:
            print("STATUS : EMPTY / NO FILES FOUND")
            continue

        total_size = sum(f.stat().st_size for f in files)

        overall_files += len(files)
        overall_size += total_size

        extensions = Counter(
            f.suffix.lower() or "[no extension]"
            for f in files
        )

        for ext, count in extensions.items():
            extension_summary[ext] += count

        print("STATUS       : DOWNLOADED")
        print(f"TOTAL FILES  : {len(files)}")
        print(f"TOTAL SIZE   : {format_size(total_size)}")

        print("\nFILE FORMAT SUMMARY:")

        for ext, count in sorted(extensions.items()):
            print(f"  {ext:<15}: {count} file(s)")

        print("\nFILES:")

        for file_path in sorted(files):
            relative_path = file_path.relative_to(folder)
            size = format_size(file_path.stat().st_size)

            print(f"  {relative_path}  |  {size}")

        # Inspect tabular and structured files
        for file_path in sorted(files):

            suffix = file_path.suffix.lower()

            print("\n" + "." * 65)
            print(f"INSPECTING: {file_path.name}")

            if suffix == ".csv":
                inspect_csv(file_path)

            elif suffix == ".parquet":
                inspect_parquet(file_path)

            elif suffix == ".json":
                inspect_json(file_path)

            elif suffix == ".zip":
                inspect_zip(file_path)

            elif suffix == ".gz":
                try:
                    with gzip.open(file_path, "rb") as f:
                        f.read(1)
                    print("      GZIP integrity: OK")
                except Exception as e:
                    print(f"      GZIP Error: {e}")

    # =================================================
    # FINAL SUMMARY
    # =================================================

    print("\n" + "=" * 75)
    print("                    FINAL SUMMARY")
    print("=" * 75)

    print(f"Total datasets checked : {len(DATASETS)}")
    print(f"Total files found      : {overall_files}")
    print(f"Total downloaded size  : {format_size(overall_size)}")

    print("\nFILE FORMAT DISTRIBUTION:")

    for ext, count in sorted(extension_summary.items()):
        print(f"  {ext:<15}: {count}")

    print("\nDATASET STATUS:")

    for dataset_name, folder_name in DATASETS.items():
        folder = DATA_DIR / folder_name
        files = get_files(folder)

        if not folder.exists() or not files:
            status = "NOT DOWNLOADED / EMPTY"
        else:
            status = "DOWNLOADED"

        print(f"  {dataset_name:<30} : {status}")

    print("\n" + "=" * 75)
    print("                  DATASET CHECK COMPLETED")
    print("=" * 75)


if __name__ == "__main__":
    main()
