# Slim, official Python base — no extra OS packages needed since
# qrcode/Pillow ship manylinux wheels for this image.
FROM python:3.12-slim

WORKDIR /app

# Install dependencies first so this layer is cached unless requirements.txt
# changes — code edits won't trigger a slow reinstall.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App code.
COPY app ./app

# Where the SQLite file lives inside the container. Mount a volume here
# (see docker-compose.yml) so data survives `docker compose down`/restarts.
ENV LOOPLINK_DATA_DIR=/app/data
RUN mkdir -p /app/data

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
