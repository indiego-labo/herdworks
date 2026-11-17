#!/usr/bin/env python3
import json
from pathlib import Path
import sys

repo = Path.cwd()
log = repo.parent / 'fake-gh.jsonl'
args = sys.argv[1:]
record = dict(args=args)
if args[:2] == ['pr', 'create'] and '--draft' in args:
    record['body'] = Path(args[args.index('--body-file') + 1]).read_text()
    output = 'https://github.invalid/fixture/hello/pull/1'
elif args[:2] == ['issue', 'list']:
    source = repo.parent / 'fake-gh-issues.json'
    output = source.read_text() if source.exists() else '[]'
elif args[:2] == ['issue', 'edit']:
    output = ''
elif args[:2] == ['issue', 'view']:
    entries = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
    output = json.dumps(dict(comments=[dict(body=e['args'][e['args'].index('--body') + 1]) for e in entries
                                      if e['args'][:3] == ['issue', 'comment', args[2]]]))
elif args[:2] == ['issue', 'comment']:
    output = ''
else:
    raise SystemExit('unsupported fake-gh command')
with log.open('a') as stream:
    stream.write(json.dumps(record) + '\n')
print(output)
