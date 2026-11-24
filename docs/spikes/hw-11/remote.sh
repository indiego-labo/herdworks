#!/usr/bin/env bash
set -eu
umask 077
unset HC_TERMINAL_ID HC_TERMINAL_SOCKET HC_SCOPE HW_HC_HOP HW_CALLER_TERMINAL
unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE GIT_OBJECT_DIRECTORY GIT_ALTERNATE_OBJECT_DIRECTORIES
export PATH="$HOME/.local/bin:$HOME/.opencode/bin:$PATH"
export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1 GIT_TERMINAL_PROMPT=0
export GIT_ALLOW_PROTOCOL=file
export HC_SESSION="hw11-${PWD##*.}"
export HW_HOME="$PWD/home" XDG_CONFIG_HOME="$PWD/config" XDG_STATE_HOME="$PWD/state" XDG_RUNTIME_DIR="$PWD/runtime"
mkdir "$XDG_CONFIG_HOME" "$XDG_STATE_HOME" "$XDG_RUNTIME_DIR"

cleanup_core() {
    hc ls --all --json > evidence/terminals-after.json
    hc server stop
    sockets=$(find "$XDG_RUNTIME_DIR" -type s -print)
    test -z "$sockets"
    printf 'No scratch runtime sockets remain.\n'
}

trap 'cleanup_core > evidence/core-cleanup.txt 2>&1' EXIT
hc server start > evidence/core-start.txt 2>&1
hc ls --all --json > evidence/terminals-before.json
git clone --branch candidate --single-branch candidate.bundle candidate
git -C candidate checkout --detach
python3 check.py
