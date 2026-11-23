#!/usr/bin/env python3
import hashlib
import json
from pathlib import Path
import sys

repo = Path.cwd()
log = repo.parent / 'fake-gh.jsonl'
args = sys.argv[1:]
if args == ['pr', 'create', '--help']:
    if (repo.parent / 'fake-gh-attachments').is_file():
        print('  --attach file')
    raise SystemExit(0)

record = dict(args=args)
if args[:2] == ['pr', 'create']:
    record['isDraft'] = '--draft' in args
    body_path = Path(args[args.index('--body-file') + 1])
    body = body_path.read_text()
    assets = [Path(args[index + 1]) for index, arg in enumerate(args) if arg == '--attach']
    if assets:
        record['assets'] = {}
        for file in assets:
            assert body_path.parent / file.name == file
            destination = f'https://github.invalid/user-attachments/assets/{file.name}'
            if file.suffix in ('.mp4', '.mov', '.webm'):
                body = body.replace(f'![]({file.name})', destination)
            else:
                body = body.replace(f']({file.name})', f']({destination})')
            record['assets'][file.name] = hashlib.sha256(file.read_bytes()).hexdigest()
    record['body'] = body
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
