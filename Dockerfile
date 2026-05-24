FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN useradd --create-home --shell /bin/bash appuser

COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY . .
RUN mkdir -p /app/data /app/reports \
    && chown -R appuser:appuser /app

USER appuser

HEALTHCHECK --interval=60s --timeout=10s --start-period=30s --retries=3 CMD ["python", "healthcheck.py"]

CMD ["python", "main.py"]

