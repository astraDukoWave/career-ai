# =============================================================================
# Backend image — FastAPI + WeasyPrint
# WeasyPrint needs native libs (cairo, pango, gdk-pixbuf) that are NOT in the
# slim base image. Without them the container builds fine but PDF generation
# crashes at runtime.
# =============================================================================
FROM python:3.11-slim

# --- System dependencies for WeasyPrint -------------------------------------
# Pin nothing here: apt resolves the right versions for the slim base.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpango-1.0-0 \
    libpangoft2-1.0-0 \
    libcairo2 \
    libgdk-pixbuf-2.0-0 \
    libffi-dev \
    shared-mime-info \
    fonts-dejavu \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first (cached layer, only re-runs if requirements change).
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Source is mounted as a volume in docker-compose for hot-reload, so this COPY
# only matters for production-style builds without the volume mount.
COPY . .

EXPOSE 8000

# Default command (overridden by docker-compose for dev hot-reload).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
