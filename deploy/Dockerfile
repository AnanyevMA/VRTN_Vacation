FROM python:3.12.8-slim-bookworm

# Create non-root system user with UID 1000
RUN useradd -u 1000 -m -s /bin/sh appuser

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Ensure data directory exists for SQLite WAL mode and set permissions for appuser
RUN mkdir -p /app/data && chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--limit-concurrency", "50", "--timeout-keep-alive", "5", "--no-access-log"]


