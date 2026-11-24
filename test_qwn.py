"""Manual smoke test against the configured local Ollama server."""

from argparse import ArgumentParser
from time import monotonic

from backend.config import OLLAMA_MODEL
from backend.llm import generate_response


def main() -> None:
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("message", nargs="?", default="Hello. Reply in one short sentence.")
    args = parser.parse_args()
    started = monotonic()
    answer = generate_response([{"role": "user", "content": args.message}])
    print(f"{OLLAMA_MODEL} responded in {monotonic() - started:.1f}s")
    print(answer)


if __name__ == "__main__":
    main()
