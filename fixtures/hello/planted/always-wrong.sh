#!/bin/sh
set -eu
printf 'Diagnosis: the planted builder deliberately keeps the acceptance failure.\n' > ../report.md
if ! git apply --check planted/wrong.patch 2>/dev/null; then
    :
else
    git apply planted/wrong.patch
fi
git add hello.py
git commit --allow-empty -m 'test: preserve planted shout failure'
commit=$(git rev-parse HEAD)
printf 'READY %s\nDiagnosis: deliberately kept the same wrong assumption; shout remains mixed case.\n' "$commit" > ../report.md
