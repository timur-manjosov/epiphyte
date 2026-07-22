# Runtime image only — no compiled assets, so a single stage is enough.
FROM python:3.11-slim

WORKDIR /app

# Dependency layer first, so it stays cached across rebuilds that only touch
# source.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Non-root user, even though the container is isolated per project.
RUN useradd --system --create-home --uid 1000 appuser \
    && mkdir -p /app/data \
    && chown -R appuser:appuser /app
USER appuser

# storage.py's DEFAULT_DB_PATH ("epiphyte.db") is resolved relative to the
# working directory, so running from /app/data puts the SQLite file (and its
# WAL/SHM sidecars) on the bind-mounted volume without touching bot logic.
WORKDIR /app/data

CMD ["python", "/app/bot.py"]
