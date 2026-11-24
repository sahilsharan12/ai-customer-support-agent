import os
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")


def project_path(name: str, default: str) -> Path:
    return PROJECT_ROOT / os.getenv(name, default)


DATA_DIR = project_path("SUPPORT_DATA_DIR", "data")
ORDER_DB_PATH = project_path("ORDER_DB_PATH", "database/olist.db")
VECTOR_STORE_DIR = project_path("CHROMA_PERSIST_DIRECTORY", "rag/vector_store")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3:1.7b")
OLLAMA_EMBEDDING_MODEL = os.getenv("OLLAMA_EMBEDDING_MODEL", "nomic-embed-text")
POLICY_RETRIEVAL = os.getenv("POLICY_RETRIEVAL", "local").strip().lower()
DEMO_REFUNDS_ENABLED = os.getenv("DEMO_REFUNDS_ENABLED", "false").strip().lower() == "true"
