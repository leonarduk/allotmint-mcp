# Research agent sidecar. Bigger than it looks: sentence-transformers pulls in
# PyTorch, so the image is measured in GB. That is the cost of embedding
# locally instead of paying a hosted embeddings API per token (issue #11).
FROM python:3.12-slim

WORKDIR /app

# Baked in at build time so the first request doesn't pay a model download.
ENV HF_HOME=/app/.cache/huggingface \
    ALLOTMINT_RESEARCH_EMBEDDING_MODEL=all-MiniLM-L6-v2

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY ingest.py ./

RUN python -c "from sentence_transformers import SentenceTransformer; \
    SentenceTransformer('all-MiniLM-L6-v2')"

EXPOSE 8100
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8100"]
