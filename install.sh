#!/usr/bin/env bash
# Herdworks installer for macOS and Linux. Installs everything into your home folder; no sudo.
#
#   curl -fsSL https://raw.githubusercontent.com/indiego-labo/herdworks/main/install.sh | bash
#
# Run it again to update. From a clone, `./install.sh [REF]` installs that branch, tag or commit.
#
# What it installs, each only if missing:
#   uv           Python for Herdworks                 ~/.local/bin/uv
#   herdr core   keeps agent terminals alive (hc)     ~/.local/bin/hc
#   opencode 2   the coding agent                     ~/.opencode/bin/opencode
#   gh           GitHub sign-in and pull requests     ~/.local/share/gh, ~/.local/bin/gh
#   Herdworks    this repository                      ~/.local/share/herdworks, ~/.local/bin/hw
#
# Settings, all optional:
#   HW_REF     branch, tag or commit to install (default main; the first argument wins)
#   HW_REPO    where to install from (default https://github.com/indiego-labo/herdworks.git)
#   HW_PREFIX  install folder (default ${XDG_DATA_HOME:-~/.local/share}/herdworks)
#   HW_BIN     folder for commands (default ~/.local/bin)
#   HW_NO_MODIFY_PATH=1  leave shell startup files alone
#   XDG_CONFIG_HOME selects where herdr core's templates are written, as hc does.

# Everything runs inside main, so a download cut short by the network runs nothing.
main() {
    set -euo pipefail

    local ref=${1:-${HW_REF:-main}}
    local repo=${HW_REPO:-https://github.com/indiego-labo/herdworks.git}
    local prefix=${HW_PREFIX:-${XDG_DATA_HOME:-$HOME/.local/share}/herdworks}
    local bindir=${HW_BIN:-$HOME/.local/bin}
    local opencode_dir=$HOME/.opencode/bin

    case "$prefix" in /*) ;; *) fail "HW_PREFIX must be an absolute path: $prefix" ;; esac
    case "$bindir" in /*) ;; *) fail "HW_BIN must be an absolute path: $bindir" ;; esac

    local os arch
    case "$(uname -s)" in
        Darwin) os=macos ;;
        Linux) os=linux ;;
        *) fail "Herdworks runs on macOS and Linux; this is $(uname -s)" ;;
    esac
    case "$(uname -m)" in
        x86_64 | amd64) arch=amd64 ;;
        arm64 | aarch64) arch=arm64 ;;
        *) fail "unsupported processor: $(uname -m)" ;;
    esac

    step "Checking this computer"
    need curl "install curl with your system's package manager, then run this again"
    need tar "install tar with your system's package manager, then run this again"
    if [ "$os" = macos ]; then
        need git "run: xcode-select --install   (it opens a window; click Install), then run this again"
        need unzip "unzip ships with macOS; something is wrong with this Mac's command-line tools"
    else
        need git "run: sudo apt-get install -y git   (or your distribution's equivalent), then run this again"
    fi
    ok "$os on $arch, with git, curl and tar"

    mkdir -p "$bindir"
    export PATH="$bindir:$opencode_dir:$PATH"

    step "uv (provides Python)"
    if command -v uv >/dev/null; then
        ok "already installed: $(command -v uv)"
    else
        run_installer uv https://astral.sh/uv/install.sh env UV_INSTALL_DIR="$bindir" UV_NO_MODIFY_PATH=1 sh
        ok "installed $(uv --version)"
    fi
    local python
    python=$(uv python find '>=3.11' 2>/dev/null || true)
    if [ -z "$python" ]; then
        quietly "Python" uv python install 3.12
        python=$(uv python find 3.12)
    fi
    ok "Python $("$python" -c 'import platform; print(platform.python_version())') at $python"

    step "herdr core (hc)"
    if command -v hc >/dev/null; then
        ok "already installed: $(hc --version 2>/dev/null || command -v hc)"
    else
        run_installer "herdr core" https://releases.herdr.dev/core/install.sh env HC_INSTALL_DIR="$bindir" sh
        command -v hc >/dev/null || fail "herdr core did not install; see https://github.com/herdrdev/herdr-core"
        ok "installed $(hc --version)"
    fi

    step "opencode (the coding agent)"
    # Herdworks needs opencode 2; opencode's first installer only installs opencode 1.
    local opencode_major
    opencode_major=$(opencode --version 2>/dev/null | sed -n 's/^[^0-9]*\([0-9][0-9]*\)\..*/\1/p' | head -1 || true)
    if [ -n "$opencode_major" ] && [ "$opencode_major" -ge 2 ]; then
        ok "already installed: $(command -v opencode) ($(opencode --version 2>/dev/null))"
    else
        if [ -n "$opencode_major" ]; then ok "opencode $opencode_major is too old; installing opencode 2"; fi
        run_installer opencode https://opencode.ai/v2/install bash -s -- --no-modify-path
        command -v opencode >/dev/null || fail "opencode did not install; see https://opencode.ai"
        ok "installed $(opencode --version 2>/dev/null)"
    fi

    step "GitHub CLI (gh)"
    if command -v gh >/dev/null; then
        ok "already installed: $(command -v gh)"
    else
        install_gh "$os" "$arch" "$bindir"
        ok "installed $(gh --version | head -1)"
    fi

    step "Herdworks"
    if [ -e "$prefix" ]; then
        [ -d "$prefix/.git" ] || fail "$prefix exists and is not a Herdworks install; move it aside and run this again"
        [ -z "$(git -C "$prefix" status --porcelain)" ] ||
            fail "$prefix has local changes. It is an install, not a place to edit; work in a clone instead"
        git -C "$prefix" remote set-url origin "$repo"
    else
        mkdir -p "$(dirname "$prefix")"
        git clone --quiet --no-checkout "$repo" "$prefix"
    fi
    git -C "$prefix" fetch --quiet --tags --prune origin '+refs/heads/*:refs/remotes/origin/*'
    local commit
    commit=$(git -C "$prefix" rev-parse --quiet --verify "refs/remotes/origin/$ref^{commit}" ||
             git -C "$prefix" rev-parse --quiet --verify "$ref^{commit}") ||
        fail "no branch, tag or commit named $ref in $repo"
    git -C "$prefix" checkout --quiet --detach "$commit"
    # bin/hw reads this to find a Python new enough, whoever starts it.
    printf '%s\n' "$python" > "$prefix/.python"
    rm -f "$bindir/hw"
    printf '#!/bin/sh\nexec "%s" "$@"\n' "$prefix/bin/hw" > "$bindir/hw"
    chmod 755 "$bindir/hw"
    "$bindir/hw" install >/dev/null
    ok "Herdworks $(git -C "$prefix" rev-parse --short HEAD) ($ref) in $prefix"

    if [ "${HW_NO_MODIFY_PATH:-0}" != 1 ]; then
        add_to_path "$bindir" "$opencode_dir"
    fi

    printf '\n\033[1mDone.\033[0m Next:\n\n'
    if [ -n "${PATH_FILE:-}" ]; then
        printf '  1. Open a new terminal window (so it picks up %s)\n' "$PATH_FILE"
        printf '  2. Run:  hw setup\n\n'
    else
        printf '  Run:  hw setup\n\n'
    fi
    printf 'hw setup signs you in to GitHub and a model provider, then adds your first Project.\n'
    printf 'hw help explains everything else.\n'
}

step() { printf '\n\033[1m%s\033[0m\n' "$1"; }
ok() { printf '  \033[32m✓\033[0m %s\n' "$1"; }
fail() { printf '\n\033[31mHerdworks install stopped:\033[0m %s\n' "$1" >&2; exit 1; }
need() { command -v "$1" >/dev/null || fail "$1 is missing. To fix: $2"; }

# Downloads a tool's own installer, then runs it with the given command reading it on stdin.
run_installer() {
    local label=$1 url=$2 script
    shift 2
    script=$(mktemp)
    curl -fsSL "$url" -o "$script" || { rm -f "$script"; fail "could not download the $label installer from $url"; }
    quietly "$label" "$@" < "$script"
    rm -f "$script"
}

# Runs a step with its output kept aside, and shows that output only if the step fails.
quietly() {
    local label=$1 log
    shift
    log=$(mktemp)
    if ! "$@" >"$log" 2>&1; then
        cat "$log" >&2
        rm -f "$log"
        fail "$label did not install (its output is above)"
    fi
    rm -f "$log"
}

install_gh() {
    local os=$1 arch=$2 bindir=$3 tag version name archive url sums tmp
    tag=$(curl -fsSLI -o /dev/null -w '%{url_effective}' https://github.com/cli/cli/releases/latest)
    tag=${tag##*/}
    version=${tag#v}
    [ -n "$version" ] && [ "$version" != latest ] || fail "could not find the latest gh release"
    if [ "$os" = macos ]; then name="gh_${version}_macOS_${arch}"; archive="$name.zip"
    else name="gh_${version}_linux_${arch}"; archive="$name.tar.gz"; fi
    url="https://github.com/cli/cli/releases/download/$tag"
    tmp=$(mktemp -d)
    curl -fsSL "$url/$archive" -o "$tmp/$archive"
    curl -fsSL "$url/gh_${version}_checksums.txt" -o "$tmp/sums"
    sums=$(grep " $archive\$" "$tmp/sums" | cut -d' ' -f1)
    [ -n "$sums" ] && [ "$(sha256 "$tmp/$archive")" = "$sums" ] || fail "gh download failed its checksum"
    if [ "$os" = macos ]; then unzip -q "$tmp/$archive" -d "$tmp"; else tar -xzf "$tmp/$archive" -C "$tmp"; fi
    rm -rf "$HOME/.local/share/gh"
    mkdir -p "$HOME/.local/share"
    mv "$tmp/$name" "$HOME/.local/share/gh"
    ln -sfn "$HOME/.local/share/gh/bin/gh" "$bindir/gh"
    rm -rf "$tmp"
}

sha256() {
    if command -v sha256sum >/dev/null; then sha256sum "$1" | cut -d' ' -f1
    else shasum -a 256 "$1" | cut -d' ' -f1; fi
}

# Adds the command folders to the user's shell startup files, once each. Login shells
# (ssh host cmd, hc exec) read ~/.profile; Ubuntu's ~/.bashrc stops early for them.
add_to_path() {
    local file files marker='# Added by the Herdworks installer'
    case "$(basename "${SHELL:-/bin/sh}")" in
        zsh) files="$HOME/.zshrc $HOME/.zprofile" ;;
        bash) if [ "$(uname -s)" = Darwin ]; then files="$HOME/.bash_profile"; else files="$HOME/.bashrc $HOME/.profile"; fi ;;
        fish) files="$HOME/.config/fish/conf.d/herdworks.fish" ;;
        *) files="$HOME/.profile" ;;
    esac
    for file in $files; do
        if [ -f "$file" ] && grep -qF "$marker" "$file"; then continue; fi
        mkdir -p "$(dirname "$file")"
        if [ "${file##*.}" = fish ]; then
            printf '\n%s\nfish_add_path %s %s\n' "$marker" "$1" "$2" >> "$file"
        else
            printf '\n%s\nexport PATH="%s:%s:$PATH"\n' "$marker" "$1" "$2" >> "$file"
        fi
        PATH_FILE=${PATH_FILE:-$file}
    done
}

main "$@"
