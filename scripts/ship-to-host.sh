#!/bin/bash
# Install a pushed branch, tag or commit of Herdworks on a host registered with hc.
set -euo pipefail
if [ "$#" -lt 1 ] || [ "$#" -gt 2 ]; then
    echo 'usage: scripts/ship-to-host.sh HOST [REF]' >&2
    exit 2
fi
host=$1
ref=${2:-main}
root=$(git rev-parse --show-toplevel)
local_commit=$(git -C "$root" rev-parse --verify "$ref^{commit}")
remote_commit=$(git -C "$root" ls-remote origin "refs/heads/$ref" | cut -f1)
if git -C "$root" show-ref --verify --quiet "refs/heads/$ref" && [ "$remote_commit" != "$local_commit" ]; then
    echo "refusing: $ref is not pushed (local $local_commit, origin ${remote_commit:-none}); push it first" >&2
    exit 1
fi
hc exec -i --on "$host" -- bash -lc '
set -euo pipefail
if [ -n "$2" ]; then export XDG_CONFIG_HOME=$2; fi
bash -s -- "$1"
' hw-ship "$ref" "${HW_HOST_CONFIG_HOME:-}" < "$root/install.sh"
