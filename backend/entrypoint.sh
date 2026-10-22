#!/bin/sh
# Apply database migrations, then start the API server.
set -e
python - <<'PY'
import sys, time
from sqlalchemy import create_engine, text
from almlight.core.config import get_settings
url = get_settings().database_url
for attempt in range(60):
    try:
        with create_engine(url).connect() as c:
            c.execute(text("SELECT 1"))
        break
    except Exception as exc:  # database not ready yet
        if attempt == 59:
            print(f"Database not reachable: {exc}", file=sys.stderr)
            sys.exit(1)
        time.sleep(1)
PY
alembic upgrade head
exec uvicorn almlight.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips='*' "$@"
