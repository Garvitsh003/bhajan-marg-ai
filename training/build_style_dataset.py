"""
Builds a conservative style-learning dataset from already indexed transcript
chunks. It does NOT invent "Premanand Ji quotes".

This script asks the local model to turn transcript passages into:
- a plausible user question that the passage directly addresses
- a faithful explanation in simple devotional Hindi
- the source chunk ids for traceability

Review the JSONL manually before fine-tuning. Synthetic examples should never
be treated as canonical evidence; canonical evidence remains the raw transcript.
"""
import argparse
import json
from pathlib import Path

from app import db
from app.llm import ollama_chat, parse_json


def rows(limit: int):
    with db.tx() as conn:
        return conn.execute(
            """
            SELECT c.*,v.title FROM chunks c
            JOIN videos v ON v.video_id=c.video_id
            ORDER BY c.video_id,c.chunk_index
            LIMIT ?
            """,
            (limit,),
        ).fetchall()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=500)
    ap.add_argument("--out", default="training/data/style_examples.jsonl")
    args = ap.parse_args()

    db.init_db()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    with out.open("w", encoding="utf-8") as f:
        for n, row in enumerate(rows(args.limit), 1):
            text = row["text"]
            prompt = f"""
Transcript passage:
{text}

Create one training example for an AI explanation assistant.
Only create a question if this passage genuinely contains enough material to
answer it. The explanation must preserve the meaning and must NOT pretend to be
an exact quote.

Return JSON only:
{{
  "usable": true,
  "question": "...",
  "answer": "...",
  "reason": "..."
}}
If unsuitable, return {{"usable":false,"reason":"..."}}.
"""
            raw = ollama_chat(
                [{"role":"user","content":prompt}],
                temperature=0.2,
                json_mode=True,
            )
            obj = parse_json(raw, {"usable": False})
            if not obj.get("usable"):
                continue
            record = {
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "Explain spiritual ideas simply and devotionally. "
                            "Do not impersonate Premanand Ji and do not invent quotations."
                        ),
                    },
                    {"role": "user", "content": obj["question"]},
                    {"role": "assistant", "content": obj["answer"]},
                ],
                "provenance": {
                    "video_id": row["video_id"],
                    "chunk_index": row["chunk_index"],
                    "title": row["title"],
                },
            }
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
            print(n, row["video_id"], row["chunk_index"])


if __name__ == "__main__":
    main()
