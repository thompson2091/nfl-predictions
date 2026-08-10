#!/usr/bin/env python3
"""Container health probe — hits Streamlit's own health endpoint."""
import os
import sys
import urllib.request

port = os.environ.get("PORT") or os.environ.get("STREAMLIT_SERVER_PORT", "8501")
url = f"http://127.0.0.1:{port}/_stcore/health"

try:
    with urllib.request.urlopen(url, timeout=4) as resp:
        sys.exit(0 if resp.status == 200 else 1)
except Exception as exc:  # noqa: BLE001 - any failure means unhealthy
    print(f"healthcheck failed: {exc}", file=sys.stderr)
    sys.exit(1)
