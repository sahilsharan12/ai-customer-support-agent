import json
from pathlib import Path

from backend.agent import retrieve
from rag.retriever import DOCUMENTS_DIR


DATASET = Path(__file__).with_name("policy_cases.json")


def evaluate():
    examples = json.loads(DATASET.read_text(encoding="utf-8"))
    scores = []
    for example in examples:
        result = retrieve({"history": [{"role": "user", "content": example["question"]}]})
        source = example["source"]
        if source is None:
            correct = result.get("fallback") == "POLICY_UNAVAILABLE"
            scores.append({"question": example["question"], "abstained": correct, "passed": correct})
            continue
        answer = result.get("answer", "")
        cited = result.get("sources") == [source]
        fact = example["fact"].lower() in answer.lower()
        # Exclude the document title added by retrieval and the citation rendered by the API.
        article = "\n\n".join(answer.rsplit("\n\nSource [", 1)[0].split("\n\n")[1:])
        original = (DOCUMENTS_DIR / source).read_text(encoding="utf-8")
        faithful = bool(article) and article in original
        scores.append({
            "question": example["question"], "citation": cited, "fact_found": fact,
            "extractive_faithfulness": faithful, "passed": cited and fact and faithful,
        })
    return {"cases": len(scores), "passed": sum(row["passed"] for row in scores), "details": scores}


if __name__ == "__main__":
    report = evaluate()
    print(json.dumps(report, indent=2))
    raise SystemExit(int(report["passed"] != report["cases"]))
