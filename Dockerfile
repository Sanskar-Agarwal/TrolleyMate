# Single-container build: React app compiled, then served by FastAPI on port 8000.
#   docker compose up --build        → http://localhost:8000

FROM node:22-alpine AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim AS app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app/backend
COPY backend/requirements.lock ./
# Pinned, complete set — no resolver surprises on demo day (KAN-29).
RUN pip install --no-cache-dir --no-deps -r requirements.lock && pip check
COPY backend/ ./
COPY --from=web /web/dist /app/frontend/dist
ENV FRONTEND_DIST=../frontend/dist \
    DATABASE_URL=sqlite:////data/trolleymate.db
VOLUME /data
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health')"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
