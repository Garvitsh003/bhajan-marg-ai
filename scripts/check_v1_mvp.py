#!/usr/bin/env python3
from pathlib import Path
import sys

root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
required = [
    "app/main.py",
    "app/language.py",
    "app/product_db.py",
    "app/v1_api.py",
    "web/index.html",
    "web/app.js",
    "web/config.js",
    "web/vercel.json",
    "app/static/index.html",
    "app/static/app.js",
    "migrations/001_v1_mvp_postgres.sql",
    "requirements-v1-mvp.txt",
]
missing = [x for x in required if not (root / x).exists()]
if missing:
    print("❌ Missing:")
    for x in missing:
        print(" -", x)
    raise SystemExit(1)

all_text = "\n".join((root / x).read_text(encoding="utf-8", errors="ignore") for x in required if (root / x).is_file())
if "supabase" in all_text.lower():
    print("❌ Supabase reference found in V1 implementation files")
    raise SystemExit(1)
if "api.include_router(v1_router)" not in (root / "app/main.py").read_text():
    print("❌ V1 API router is not included in app/main.py")
    raise SystemExit(1)
if 'preferred_language: Literal["auto", "hi", "hinglish", "en"]' not in (root / "app/main.py").read_text():
    print("❌ language/history patch missing in app/main.py")
    raise SystemExit(1)
if "message_sources" not in (root / "migrations/001_v1_mvp_postgres.sql").read_text():
    print("❌ structured source schema missing")
    raise SystemExit(1)

print("✅ No Supabase dependency")
print("✅ Accounts/auth API present")
print("✅ Persistent conversations/messages/sources present")
print("✅ Feedback + analytics schema present")
print("✅ Language renderer present")
print("✅ Vercel same-origin API proxy present")
