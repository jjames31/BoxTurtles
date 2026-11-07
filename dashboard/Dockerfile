FROM node:22-bookworm-slim AS frontend
WORKDIR /build
COPY frontend/package*.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim-bookworm
ARG TORCH_INDEX_URL=https://download.pytorch.org/whl/cpu
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 TURTLE_DATA_DIR=/data \
    TURTLE_MODEL_PATH=/app/best.pt YOLO_CONFIG_DIR=/tmp/ultralytics \
    YOLO_AUTOINSTALL=false OMP_NUM_THREADS=2
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg libglib2.0-0 libgl1 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements-public.txt ./
RUN pip install --no-cache-dir torch torchvision --index-url ${TORCH_INDEX_URL} \
    && pip install --no-cache-dir -r requirements-public.txt
COPY backend/ ./backend/
COPY --from=frontend /build/dist ./frontend/dist
RUN useradd --uid 10001 --create-home turtle && mkdir /data && chown turtle:turtle /data
USER turtle
EXPOSE 8000
HEALTHCHECK --start-period=90s --interval=30s --timeout=10s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=5)"
CMD ["uvicorn", "backend.app.public:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--proxy-headers", "--forwarded-allow-ips", "*", "--limit-concurrency", "64", "--timeout-keep-alive", "5"]
