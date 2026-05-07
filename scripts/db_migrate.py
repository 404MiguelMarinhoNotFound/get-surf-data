"""Run forecast cache SQL migrations."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import db


def main():
    migration_dir = ROOT / "migrations"
    files = sorted(migration_dir.glob("*.sql"))
    if not files:
        print("No migrations found.")
        return 0

    with db.connect() as conn:
        with conn.cursor() as cur:
            for path in files:
                cur.execute(path.read_text(encoding="utf-8"))
                print(path.name)
        conn.commit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
