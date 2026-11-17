#!/bin/sh
set -eu
for count in 1 2 3 4 5 6 7 8 9; do
    printf 'progress %s\n' "$count" >> ../progress.txt
    sleep 20
done
commit=$(git rev-parse HEAD)
printf 'FAIL\nCommit: %s\nPlanted timing verdict after three minutes of file progress.\n' "$commit" > ../verdict.md
