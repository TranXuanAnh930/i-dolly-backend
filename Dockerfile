FROM python:3.12-slim

# /app is bind-mounted from the host in docker-compose.yaml (dev setup),
# so .pyc files this container writes land on the host disk too. On some
# Docker Desktop bind-mount backends, mtime resolution is coarse enough
# that Python's "has the source changed?" check can be fooled into
# reusing stale bytecode after a source file is edited on the host — this
# caused a real crash-loop (alembic kept running an old, already-fixed
# migration). Never write .pyc files instead of trying to keep them fresh.
ENV PYTHONDONTWRITEBYTECODE=1

# Python fully buffers stdout when it isn't attached to a real terminal —
# which is exactly what a container's stdout is to `docker logs`/`docker
# compose logs`. Without this, print() output (e.g. email_sender.py's
# DEBUG-mode token dump) can sit in the buffer indefinitely instead of
# reaching the log stream, since nothing forces a flush between requests.
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

RUN printf '#!/bin/sh\n\
set -e\n\
echo "Running Alembic migrations..."\n\
python -m alembic upgrade head\n\
echo "Starting FastAPI..."\n\
exec python -m uvicorn main:app --host 0.0.0.0 --port $PORT\n' > /start.sh \
 && chmod +x /start.sh

# Same image, no migrations (the web service's /start.sh already runs them
# on boot) — just starts a Celery worker against app/celery_app.py. Used as
# the start command for a separate process (docker-compose's `worker`
# service locally, a Render Background Worker in prod), never as this
# image's default CMD.
RUN printf '#!/bin/sh\n\
set -e\n\
echo "Starting Celery worker..."\n\
exec python -m celery -A app.celery_app worker --loglevel=info\n' > /start-worker.sh \
 && chmod +x /start-worker.sh

CMD ["/start.sh"]