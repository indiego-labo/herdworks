#!/bin/bash
# Run only as a plain owner shell. Stdout is the evidence tar stream.
set -euo pipefail
exec 3>&1
exec >&2
scratch=$(mktemp -d /tmp/hw8.XXXXXXXX)
scratch=$(cd "$scratch" && pwd -P)
export PATH="$HOME/.local/bin:$HOME/bin:$PATH"
export HC_SESSION="hw8-${scratch##*.}"
export XDG_CONFIG_HOME="$scratch/config" XDG_STATE_HOME="$scratch/state" XDG_RUNTIME_DIR="$scratch/run"
export HW_HOME="$scratch/home" CODEX_HOME="$scratch/codex"
unset HC_TERMINAL_ID HC_TERMINAL_SOCKET HC_SCOPE HW_CALLER_TERMINAL HW_HC_HOP
mkdir -m 700 "$XDG_CONFIG_HOME" "$XDG_STATE_HOME" "$XDG_RUNTIME_DIR" "$HW_HOME" "$CODEX_HOME" "$scratch/evidence" "$scratch/shim"
mkdir -m 700 "$scratch/tmp"
export TMPDIR="$scratch/tmp"
export PYTHONDONTWRITEBYTECODE=1
stop_core() {
    if [ "${core_started:-0}" = 1 ]; then
        hc server stop --json
    fi
}
cleanup() {
    stop_core >&2
    cd /
    rm -rf -- "$scratch" && test ! -e "$scratch" && echo "Removed scratch root $scratch"
}
trap cleanup EXIT
tar -xf - -C "$scratch"
git clone --quiet --no-checkout "$scratch/candidate.bundle" "$scratch/candidate"
git -C "$scratch/candidate" checkout --quiet --detach d230e7aafe4f688cd85f6e7811f790e248c9632e
ln -s "$scratch/terminal-fixture.py" "$scratch/shim/codex"
cd "$scratch/candidate"
export PATH="$scratch/shim:$PATH"
hc server start --json > "$scratch/evidence/core-start.json" 2>&1 || { cat "$scratch/evidence/core-start.json"; exit 1; }
core_started=1
set +e
python3 "$scratch/journey.py" > "$scratch/evidence/journey.log" 2>&1
journey_status=$?
python3 -m unittest discover -s tests -v > "$scratch/evidence/unit.txt" 2>&1
unit_status=$?
{
    echo "Scratch root $scratch"
    echo "python3 journey.py exit $journey_status"
    echo "python3 -m unittest discover -s tests -v exit $unit_status"
    hc ls --all --json
    stop_core
    stop_status=$?
    if [ "$stop_status" = 0 ]; then core_started=0; fi
    echo "hc server stop exit $stop_status"
    # A status query would start another core on this herdr version.
    if [ -S "$XDG_RUNTIME_DIR/herdr-core/$HC_SESSION.sock" ]; then
        echo "Scratch core socket still present after stop"
    else
        echo "Scratch core socket absent after stop"
    fi
} > "$scratch/evidence/lifecycle.txt" 2>&1
tar -cf - -C "$scratch" evidence >&3
exit "$((journey_status != 0 || unit_status != 0 || stop_status != 0))"
