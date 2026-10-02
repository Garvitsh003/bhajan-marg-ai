"""Run the saved 20-question suite against a deployed backend; no automatic retries."""
import argparse
import json
import time
from pathlib import Path
import requests


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', required=True, help='Backend URL, not the static frontend')
    parser.add_argument('--sequential', action='store_true', help='Reuse one conversation as in the original benchmark')
    parser.add_argument('--output', type=Path, default=Path('benchmark-results.json'))
    args = parser.parse_args()
    cases = json.loads((Path(__file__).resolve().parents[1]/'tests/benchmark_cases.json').read_text())
    rows, conversation = [], None
    for case in cases:
        started = time.monotonic()
        row = dict(case)
        try:
            response = requests.post(args.base_url.rstrip('/')+'/api/chat', json={
                'question':case['question'], 'conversation_id':conversation if args.sequential else None}, timeout=240)
            row['http_status'] = response.status_code
            row['request_id'] = response.headers.get('X-Request-ID')
            try:
                row['response'] = response.json()
            except ValueError:
                row['response'] = {'error':'Non-JSON response'}
            if response.ok and isinstance(row['response'], dict):
                conversation = row['response'].get('conversation_id', conversation)
        except requests.RequestException as exc:
            row['error'] = type(exc).__name__
        row['elapsed_seconds'] = round(time.monotonic()-started, 2)
        rows.append(row)
        args.output.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding='utf-8')
        print(case['id'], row.get('http_status', row.get('error')), row['elapsed_seconds'], flush=True)
    print('Saved', args.output, '— manually review relevance, quote completeness, and all four adversarial answers.')

if __name__ == '__main__':
    main()
