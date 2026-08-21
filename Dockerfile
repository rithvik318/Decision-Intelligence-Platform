# --- build the frontend -----------------------------------------------------
FROM node:22-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json* ./
RUN npm install
COPY web/ ./
# Same-origin in the image, so the client needs no absolute API base URL.
ENV VITE_API_BASE_URL=""
RUN npm run build

# --- runtime ----------------------------------------------------------------
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY pyproject.toml README.md ./
COPY app ./app
# `local-embeddings` pulls FastEmbed, which the documented default configuration
# requires. Without it Cognee silently falls back to OpenAI embeddings.
RUN pip install --no-cache-dir -e ".[cognee,local-embeddings]"

COPY --from=web /web/dist ./web/dist
COPY examples ./examples

# All durable state lives here: decisions.json, workspaces.json and Cognee's
# SQLite/LanceDB/Kuzu stores. Mount it or the data dies with the container.
ENV EDI_DATA_DIR=/data
VOLUME ["/data"]

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/health').read()"

# Cognee's embedded stores are single-process; keep one worker.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
