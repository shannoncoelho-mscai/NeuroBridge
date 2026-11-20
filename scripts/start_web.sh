#!/bin/sh
# Start script for a hosted demo (Render, Docker). Free hosts wipe local files on restart,
# so the clearly-labelled demo data is rebuilt each time the server starts.
set -e
mkdir -p "$(dirname "${NEUROBRIDGE_APP_DB:-/tmp/neurobridge/app.sqlite3}")"
if [ -n "$NEUROBRIDGE_DEMO_PASSWORD" ]; then
  python scripts/seed_demo_app.py --password "$NEUROBRIDGE_DEMO_PASSWORD" || echo "Demo data not loaded"
fi
exec python -m uvicorn agent.api.app:app --host 0.0.0.0 --port "${PORT:-10000}" --proxy-headers --forwarded-allow-ips="*"
