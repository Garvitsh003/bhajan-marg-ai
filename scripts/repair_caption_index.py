"""Dry-run caption repair; --apply writes a NEW cloud collection for review.

python scripts/repair_caption_index.py --transcripts data/transcripts
python scripts/repair_caption_index.py --transcripts data/transcripts \
    --collection bhajan_marg_chunks_cloud_v2 --apply
"""
import argparse
import copy
import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.chunking import chunk_transcript
from app.text import merge_rolling_caption, normalize_text


def repair_document(document: dict) -> tuple[dict, int]:
    repaired = copy.deepcopy(document)
    previous = ''
    changed = 0
    rolling = str(document.get('transcript_source','')).startswith('youtube_caption:')
    for segment in repaired['segments']:
        if rolling and segment.get('raw_text'):
            raw = normalize_text(segment['raw_text'])
            text = merge_rolling_caption(previous, raw)
            previous = raw
        else:
            # Whisper already supplies independent segments, not rolling cues.
            text = normalize_text(segment['text'])
        changed += text != segment['text']
        segment['text'] = text
    repaired['segments'] = [s for s in repaired['segments'] if s['text']]
    return repaired, changed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--transcripts', type=Path, default=Path('data/transcripts'))
    parser.add_argument('--collection', help='A new, empty collection; existing collections are never overwritten')
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--output', type=Path, default=Path('data/repaired_transcripts'))
    args = parser.parse_args()
    files = sorted(args.transcripts.glob('*.json'))
    if not files:
        parser.error('No transcript JSON files found')
    docs = []
    changed = 0
    for path in files:
        doc, count = repair_document(json.loads(path.read_text(encoding='utf-8')))
        changed += count
        docs.append((path.name, doc))
    print(json.dumps({'videos':len(docs),'changed_caption_segments':changed,
        'chunks':sum(len(chunk_transcript(doc['segments'])) for _,doc in docs),
        'mode':'apply' if args.apply else 'dry-run'}, indent=2))
    if not args.apply:
        return
    if args.output.resolve() == args.transcripts.resolve():
        parser.error('Output must differ from the original transcript directory')
    if not args.collection:
        parser.error('--apply requires --collection naming a NEW collection')
    from qdrant_client import QdrantClient, models
    from app.config import settings
    if not settings.qdrant_api_key or not settings.qdrant_url.startswith('https://'):
        parser.error('Configure QDRANT_URL and QDRANT_API_KEY in your .env or environment')
    c = QdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key,
                     cloud_inference=True, timeout=90)
    if c.collection_exists(args.collection):
        parser.error('Collection already exists. Choose a new name; no existing data was modified.')
    c.create_collection(collection_name=args.collection,
        vectors_config={'dense_vector':models.VectorParams(size=384,distance=models.Distance.COSINE)},
        sparse_vectors_config={'bm25_sparse_vector':models.SparseVectorParams(modifier=models.Modifier.IDF)})
    args.output.mkdir(parents=True,exist_ok=True)
    expected = 0
    for filename, doc in docs:
        (args.output/filename).write_text(json.dumps(doc,ensure_ascii=False,indent=2),encoding='utf-8')
        points = []
        for chunk in chunk_transcript(doc['segments']):
            payload = {k:doc.get(k) for k in ('video_id','title','url','published_at')}
            payload.update(chunk)
            points.append(models.PointStruct(
                id=str(uuid.uuid5(uuid.NAMESPACE_URL,f'bhajan-marg:{doc["video_id"]}:{chunk["chunk_index"]}')),
                payload=payload, vector={
                    'dense_vector':models.Document(text=chunk['text'],model=settings.qdrant_dense_model),
                    'bm25_sparse_vector':models.Document(text=chunk['text'],model=settings.qdrant_bm25_model)}))
        c.upload_points(collection_name=args.collection,points=points,batch_size=8,wait=True)
        expected += len(points)
        print('Uploaded', doc['video_id'], len(points), 'chunks')
    actual = c.count(collection_name=args.collection,exact=True).count
    if actual != expected:
        raise RuntimeError(f'Count mismatch: expected {expected}, received {actual}. Do not switch collections.')
    print('Verified', actual, 'chunks. Set QDRANT_COLLECTION='+args.collection+' only after staging tests.')


if __name__ == '__main__':
    main()
