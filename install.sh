#!/usr/bin/env bash
# One-shot installer for macOS / Linux volunteers.
#
#   bash <(curl -sSL https://raw.githubusercontent.com/bulgariamitko/bg-izbori-monitor/main/install.sh)
#
# Installs: git, python3, ffmpeg, yt-dlp, gh (GitHub CLI).
# Then: gh auth login (device flow — no account? the login page has a "Sign up" link).
# Then: forks the repo, clones your fork, sets up a venv.
# Then: runs contribute.py --loop.
#
# Safe to run multiple times. Skips what's already installed/cloned.
set -euo pipefail

REPO="bulgariamitko/bg-izbori-monitor"
LOCAL_DIR="${LOCAL_DIR:-$HOME/bg-izbori-monitor}"
PY_MIN="3.11"

say()  { printf "\033[1;36m» %s\033[0m\n" "$*"; }
warn() { printf "\033[1;33m⚠ %s\033[0m\n" "$*"; }
err()  { printf "\033[1;31m✗ %s\033[0m\n" "$*" >&2; exit 1; }

have() { command -v "$1" >/dev/null 2>&1; }

detect_os() {
    case "$(uname -s)" in
        Darwin) OS=mac ;;
        Linux)
            if   have apt-get;  then OS=debian
            elif have dnf;      then OS=fedora
            elif have pacman;   then OS=arch
            else OS=linux; fi ;;
        *) err "Unsupported OS: $(uname -s)" ;;
    esac
    say "Detected OS: $OS"
}

install_pkgs_mac() {
    if ! have brew; then
        say "Homebrew missing — installing (needs sudo once)"
        /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    fi
    local pkgs=()
    have git       || pkgs+=(git)
    have python3   || pkgs+=(python@3.12)
    have ffmpeg    || pkgs+=(ffmpeg)
    have yt-dlp    || pkgs+=(yt-dlp)
    have gh        || pkgs+=(gh)
    if (( ${#pkgs[@]} )); then
        say "brew install ${pkgs[*]}"
        brew install "${pkgs[@]}"
    fi
}

install_pkgs_debian() {
    say "apt-get install"
    sudo apt-get update -qq
    sudo apt-get install -y -qq git python3 python3-venv python3-pip ffmpeg curl
    have yt-dlp || sudo apt-get install -y -qq yt-dlp || python3 -m pip install --user -q yt-dlp
    if ! have gh; then
        curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
          | sudo dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg >/dev/null
        sudo chmod go+r /usr/share/keyrings/githubcli-archive-keyring.gpg
        echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
          | sudo tee /etc/apt/sources.list.d/github-cli.list >/dev/null
        sudo apt-get update -qq && sudo apt-get install -y -qq gh
    fi
}

install_pkgs_fedora() {
    sudo dnf install -y git python3 python3-pip ffmpeg yt-dlp gh
}
install_pkgs_arch() {
    sudo pacman -Sy --needed --noconfirm git python python-pip ffmpeg yt-dlp github-cli
}
install_pkgs_linux() {
    warn "Unknown Linux distro — please install git, python3, ffmpeg, yt-dlp, gh manually, then rerun this."
    exit 1
}

setup_gh_auth() {
    if gh auth status >/dev/null 2>&1; then
        say "GitHub CLI already logged in"
    else
        say "Logging you into GitHub (device flow — will open your browser)"
        warn "Don't have a GitHub account yet? The login page has a 'Sign up' link."
        gh auth login --git-protocol https --web --hostname github.com
    fi
}

fork_and_clone() {
    if [[ -d "$LOCAL_DIR/.git" ]]; then
        say "Repo already at $LOCAL_DIR — hard-syncing with upstream"
        # Ensure upstream remote exists (older installs may be missing it).
        git -C "$LOCAL_DIR" remote add upstream "https://github.com/$REPO.git" 2>/dev/null || true
        git -C "$LOCAL_DIR" fetch upstream main
        # main tracks upstream/main — reset discards any stale local state
        # (the contribute flow only commits on branches, never on main).
        git -C "$LOCAL_DIR" checkout main 2>/dev/null || true
        git -C "$LOCAL_DIR" reset --hard upstream/main
        return
    fi
    say "Forking $REPO and cloning to $LOCAL_DIR"
    gh repo fork "$REPO" --clone=false --default-branch-only >/dev/null 2>&1 || true
    USER_LOGIN=$(gh api user --jq .login)
    git clone "https://github.com/$USER_LOGIN/bg-izbori-monitor.git" "$LOCAL_DIR"
    git -C "$LOCAL_DIR" remote add upstream "https://github.com/$REPO.git" 2>/dev/null || true
    git -C "$LOCAL_DIR" fetch upstream
    git -C "$LOCAL_DIR" reset --hard upstream/main
    git -C "$LOCAL_DIR" branch --set-upstream-to=origin/main main || true
    # Default to rebase on pull so the per-transcript branch flow stays clean.
    git -C "$LOCAL_DIR" config pull.rebase true
}

setup_venv() {
    cd "$LOCAL_DIR"
    if [[ ! -d venv ]]; then
        say "Creating Python venv"
        python3 -m venv venv
    fi
    # shellcheck disable=SC1091
    source venv/bin/activate
    say "Installing Python deps"
    pip install --quiet --upgrade pip
    pip install --quiet -r requirements.txt
}

announce_cf_note() {
    warn "IMPORTANT: Open https://evideo.bg/ once in Chrome so Cloudflare"
    warn "gives your browser a cookie — yt-dlp reuses it. Then press Enter."
    read -r -p "Press Enter when you've opened evideo.bg in Chrome … " _
}

run_contribute() {
    cd "$LOCAL_DIR"
    # shellcheck disable=SC1091
    source venv/bin/activate
    GH_HANDLE=$(gh api user --jq .login 2>/dev/null || echo "")
    say "Starting transcription loop as '$GH_HANDLE' — Ctrl-C to stop"
    # Outer loop: pull latest upstream code + data BEFORE every iteration, so
    # a long-running volunteer automatically picks up config.py / sections.json
    # / risk_tiers.json changes (e.g. when the owner flips the slug on election
    # day). contribute.py runs one section per invocation; the bash loop keeps
    # the "sync → process one → sync → process next" rhythm.
    while true; do
        say "Sync with upstream (latest code + sections)…"
        git fetch upstream main >/dev/null 2>&1 || true
        git checkout main --quiet 2>/dev/null || true
        git reset --hard upstream/main --quiet 2>/dev/null || true
        pip install --quiet -r requirements.txt 2>/dev/null || true
        if python contribute.py --gh-handle "$GH_HANDLE"; then
            :
        else
            warn "contribute.py exited with error — retrying in 30s"
            sleep 30
        fi
        # tiny gap so we don't hammer the repo when the work queue is empty
        sleep 5
    done
}

main() {
    detect_os
    case "$OS" in
        mac)     install_pkgs_mac ;;
        debian)  install_pkgs_debian ;;
        fedora)  install_pkgs_fedora ;;
        arch)    install_pkgs_arch ;;
        linux)   install_pkgs_linux ;;
    esac
    setup_gh_auth
    fork_and_clone
    setup_venv
    announce_cf_note
    run_contribute
}

main "$@"
