.PHONY: install qdrant model serve backfill100 backfill update stats

install:
	python3 -m venv .venv
	.venv/bin/pip install -r requirements.txt

qdrant:
	docker compose up -d

model:
	ollama pull qwen3:8b

serve:
	.venv/bin/uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

backfill100:
	.venv/bin/python -m app.cli backfill --limit 100

backfill:
	.venv/bin/python -m app.cli backfill --all

update:
	.venv/bin/python -m app.cli update

stats:
	.venv/bin/python -m app.cli stats
