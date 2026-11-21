# ---- 1. Build the React (TypeScript) frontend ----
FROM node:20-alpine AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---- 2. Python backend that also serves the built UI ----
FROM python:3.11-slim
WORKDIR /app/backend
ENV PYTHONUNBUFFERED=1 STATIC_DIR=/app/frontend/dist
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ ./
COPY --from=web /web/dist /app/frontend/dist
# Render sets $PORT; default to 8000 locally.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
