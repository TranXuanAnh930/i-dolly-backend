FROM python:3.12-slim

# /app is bind-mounted from the host in docker-compose.yaml (dev setup),
# so .pyc files this container writes land on the host disk too. On some
# Docker Desktop bind-mount backends, mtime resolution is coarse enough
# that Python's "has the source changed?" check can be fooled into
# reusing stale bytecode after a source file is edited on the host — this
# caused a real crash-loop (alembic kept running an old, already-fixed
# migration). Never write .pyc files instead of trying to keep them fresh.
ENV PYTHONDONTWRITEBYTECODE=1

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

CMD ["/start.sh"]