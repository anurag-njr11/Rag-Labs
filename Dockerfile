# RAGLabs in one container: docker build -t raglabs . && docker compose up
FROM node:22-slim AS web
WORKDIR /src/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build   # writes ../backend/app/web

FROM python:3.12-slim
WORKDIR /src
COPY backend/ backend/
COPY --from=web /src/backend/app/web backend/app/web
RUN pip install --no-cache-dir ./backend
# Data, downloaded embedding models and the secret key (kept apart from the data) live on volumes.
ENV DATA_DIR=/data FASTEMBED_CACHE_PATH=/data/models RAGLABS_SECRET_KEY_FILE=/config/secret.key \
    ALLOWED_HOSTS=localhost,127.0.0.1
VOLUME ["/data", "/config"]
EXPOSE 8000
CMD ["raglabs", "serve", "--host", "0.0.0.0"]
