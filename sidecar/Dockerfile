# Sidecar image for Railway. The service's root directory is set to "sidecar",
# so the build context is this directory — COPY paths are context-relative.
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# server.py binds 0.0.0.0:$PORT when a platform port is present (Railway sets $PORT).
CMD ["python", "server.py"]
