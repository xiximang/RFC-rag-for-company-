FROM python:3.11-slim

WORKDIR /app

# Install system dependencies for API layer and optional parsers.
# These packages are required when OCR / PDF-to-image / audio parsing is enabled.
# They are kept in the API image so health-check endpoints and local uploads can
# validate files without crashing if the optional features are turned off.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        curl \
        gcc \
        tesseract-ocr \
        tesseract-ocr-chi-sim \
        tesseract-ocr-eng \
        poppler-utils \
        ffmpeg \
        libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies as root
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code and create a non-root user
COPY . .
RUN groupadd -r appuser && useradd -r -g appuser appuser \
    && chown -R appuser:appuser /app

USER appuser

EXPOSE 8080

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "2"]
