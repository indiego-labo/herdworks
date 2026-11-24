#!/usr/bin/env bash
# Run from any location in the findings checkout. The evidence directory must be new.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd -P)
repo=$(git -C "$here" rev-parse --show-toplevel)
candidate=610fa3acebe97e050beeba00de11e7f8f43d1903
mkdir "$1"
evidence=$(cd "$1" && pwd -P)
transfer=$(mktemp -d "$evidence/.transfer.XXXXXX")
trap 'rm -rf -- "$transfer"' EXIT
(
    set -x
    git init --bare "$transfer/pack.git"
    git -C "$transfer/pack.git" fetch --no-tags "$repo" "$candidate:refs/heads/candidate"
    git -C "$transfer/pack.git" bundle create "$transfer/candidate.bundle" refs/heads/candidate
    git -C "$transfer/pack.git" bundle list-heads "$transfer/candidate.bundle"
    shasum -a 256 "$transfer/candidate.bundle"
    cp "$here"/{check.py,fixture-publisher.py,remote.sh} "$transfer/"
    tar -C "$transfer" -cf "$transfer/input.tar" candidate.bundle check.py fixture-publisher.py remote.sh
) > "$evidence/transfer.txt" 2>&1
set +e
ssh -o BatchMode=yes -o ConnectTimeout=8 -o StrictHostKeyChecking=yes agent-dev '
set -eu
umask 077
root=$(mktemp -d /tmp/hw11.XXXXXXXX)
trap '\''rm -rf -- "$root"'\'' EXIT
(
    cd "$root"
    mkdir evidence
    tar -xf -
    sha256sum candidate.bundle > evidence/received-bundle.txt
    set +e
    bash remote.sh > evidence/remote.txt 2>&1
    result=$?
    set -e
    printf "root=%s\nexit=%s\n" "$root" "$result" > evidence/remote-exit.txt
    if test "$result" -ne 0; then exit "$result"; fi
) || result=$?
tar -C "$root/evidence" -cf /dev/stdout .
rm -rf -- "$root"
test ! -e "$root"
printf "Scratch root removed: %s\n" "$root" >&2
exit "${result:-0}"
' < "$transfer/input.tar" > "$transfer/output.tar" 2> "$evidence/ssh-stderr.txt"
result=$?
set -e
printf 'exit=%s\n' "$result" > "$evidence/ssh-exit.txt"
if test -s "$transfer/output.tar"; then
    tar -xf "$transfer/output.tar" -C "$evidence"
fi
exit "$result"
