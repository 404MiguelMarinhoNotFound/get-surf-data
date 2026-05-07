"""Small Postgres helper for the Neon forecast cache."""

import os
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def _unquote(value):
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value


def load_local_env(filename=".env.local"):
    """Load local env vars for scripts without printing secret values."""
    path = ROOT / filename
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key and key not in os.environ:
            os.environ[key] = _unquote(value)


def connect():
    load_local_env()
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is required; no DB fallback is allowed")
    import psycopg
    from psycopg.rows import dict_row

    return psycopg.connect(url, row_factory=dict_row)


def jsonb(value):
    from psycopg.types.json import Jsonb

    return Jsonb(value)
