#!/usr/bin/env python3

import sys
from pathlib import Path

from dotenv import load_dotenv

# Project root: bhajan_marg_ai/
ROOT = Path(__file__).resolve().parents[1]

# Allow imports such as `from app...` when this file is run directly.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Explicit path avoids python-dotenv's stdin/Python 3.14 discovery issue.
load_dotenv(dotenv_path=ROOT / ".env")

from app.product_db import ensure_schema, database_url


url = database_url()

if not url:
    raise SystemExit(
        "❌ DATABASE_URL is not set. "
        "Add DATABASE_URL to the project .env file."
    )

print("Project root:", ROOT)
print("DATABASE_URL: ✅ found")
print("Connecting to PostgreSQL / Neon...")

ensure_schema()

print()
print("✅ Bhajan Marg AI V1 PostgreSQL schema is ready")
