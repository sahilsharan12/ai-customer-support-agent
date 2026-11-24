FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    SUPPORT_DATA_DIR=/var/lib/support ORDER_DB_PATH=/orders/olist.db

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && useradd --uid 10001 --create-home support \
    && install -d -o support -g support /var/lib/support /orders

COPY backend backend
COPY database/*.py database/
COPY frontend frontend
COPY models/intent_classifier models/intent_classifier
COPY rag/*.py rag/
COPY rag/documents rag/documents

USER support
EXPOSE 8000
HEALTHCHECK CMD ["python", "-c", "from urllib.request import urlopen; urlopen('http://127.0.0.1:8000/health', timeout=3).close()"]
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-proxy-headers", "--no-access-log"]
