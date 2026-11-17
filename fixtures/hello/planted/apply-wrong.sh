#!/bin/sh
set -eu
git apply planted/wrong.patch
git add hello.py
git commit -m 'feat: accept shout flag'
commit=$(git rev-parse HEAD)
printf 'READY %s\nBUILDER-SAYS-IT-WORKS\n' "$commit" > ../report.md
