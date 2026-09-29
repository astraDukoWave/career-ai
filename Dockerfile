# =============================================================================
# Deploy image for Heroku (container stack). Multi-stage: build the frontend,
# then assemble it alongside the backend under a layout that satisfies P8
# (backend/app/main.py resolves the frontend as parents[2]/frontend/dist).
#
# DRIFT GUARD: the native libs list below (WeasyPrint deps) is duplicated
# from backend/Dockerfile for local dev. Any change to that list must be
# replicated in both files.
#
# No CMD here on purpose — the boot command lives in heroku.yml (run.web).
# =============================================================================

# --- Stage 1: frontend build -------------------------------------------------
FROM node:20-alpine AS frontend-build
WORKDIR /build
COPY frontend/package*.json ./
RUN npm install
COPY frontend/ ./
ARG VITE_API_URL
ENV VITE_API_URL=$VITE_API_URL
RUN npm run build

# --- Stage 2: backend + assembled image --------------------------------------
FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpango-1.0-0 \
    libpangoft2-1.0-0 \
    libcairo2 \
    libgdk-pixbuf-2.0-0 \
    libffi-dev \
    shared-mime-info \
    fonts-dejavu \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv/backend

COPY backend/requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY backend/ .
COPY --from=frontend-build /build/dist /srv/frontend/dist
