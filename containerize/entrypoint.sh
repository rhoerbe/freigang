#!/bin/bash
# Entrypoint script for claude-ha-agent container
# Claude Code is shipped in the image (/usr/local/share/claude-native) and seeded
# into the user's $HOME/.local on start as a proper native installation. Its
# self-updater is disabled (DISABLE_AUTOUPDATER=1) so updates only come from
# rebuilding the image. See the Dockerfile and seed_claude_install() for rationale.
# Supports optional Chrome GUI mode with Xvfb/VNC for browser automation

set -e

BROWSER_MODE=${BROWSER_MODE:-none}
ENABLE_VNC=${ENABLE_VNC:-false}

seed_claude_install() {
    # Materialize a single, proper native Claude Code installation in $HOME/.local.
    #
    # $HOME (/workspace) is a host bind mount the image cannot pre-populate, so we
    # copy the image-staged native build into it on start. This yields exactly one
    # installation that `claude doctor` recognizes as native (binary under
    # ~/.local/share/claude/versions, symlinked from ~/.local/bin/claude, with
    # installMethod recorded in ~/.claude.json). Fully offline - no download.
    local stage=/usr/local/share/claude-native
    [[ -d "$stage/versions" ]] || return 0

    local ver
    ver=$(ls "$stage/versions" | sort -V | tail -1)
    [[ -n "$ver" ]] || return 0

    local dest="$HOME/.local/share/claude/versions/$ver"
    if [[ ! -f "$dest" ]]; then
        echo "Seeding Claude $ver into $HOME/.local"
        mkdir -p "$HOME/.local/bin" "$HOME/.local/share/claude/versions"
        # Drop versions left by a previous (older) image so only the current remains
        rm -rf "${HOME:?}/.local/share/claude/versions"/*
        cp -a "$stage/versions/$ver" "$dest"
    fi
    ln -sfn "$dest" "$HOME/.local/bin/claude"

    # Record install method so `claude doctor` recognizes the native install and
    # does not flag the binary as an unmanaged/leftover global installation.
    local cj="$HOME/.claude.json"
    [[ -f "$cj" ]] || echo "{}" > "$cj"
    local tmp
    tmp=$(mktemp)
    if jq '.installMethod = "native" | .autoUpdatesProtectedForNative = true' "$cj" > "$tmp" 2>/dev/null; then
        mv "$tmp" "$cj"
    else
        rm -f "$tmp"
    fi
}

sync_mail_skill() {
    # The mail skill must be present exactly when the capability is. /mail is
    # mounted only for sessions where the user enabled mail in the TUI, and
    # $HOME is a persistent bind mount - so a skill seeded in an earlier session
    # would otherwise linger and advertise a `mail` command with nothing behind
    # it. Seed when mounted, remove when not.
    local stage=/usr/local/share/freigang-skills/mail
    local dest="$HOME/.claude/skills/mail"
    if [[ -d /mail ]]; then
        [[ -d "$stage" ]] || return 0
        mkdir -p "$dest"
        cp -a "$stage/." "$dest/"
    else
        rm -rf "$dest"
    fi
}

# Seed only for invocations that actually use Claude (the agent or a shell),
# not for lightweight image queries like `cat /etc/freigang/mcp-manifest.json`.
case "$(basename "${1:-claude}")" in
    claude|bash|sh) seed_claude_install; sync_mail_skill ;;
esac

start_xvfb() {
    echo "Starting Xvfb on :99"
    # Redirect Xvfb stderr to suppress /tmp/.X11-unix warning (expected in containers)
    Xvfb :99 -screen 0 1920x1080x24 2>/dev/null &
    export DISPLAY=:99
    # Wait for X server to be ready
    for i in {1..10}; do
        xdpyinfo -display :99 >/dev/null 2>&1 && break
        sleep 0.5
    done
}

start_vnc() {
    if [ "$ENABLE_VNC" = "true" ]; then
        echo "Starting x11vnc on port 5900"
        # Note: Binds to all interfaces so it can be accessed via port mapping
        # Security: Port 5900 is only exposed when user enables VNC in TUI
        x11vnc -display :99 -forever -nopw -quiet &
    fi
}

start_chrome() {
    echo "Starting Chrome with Claude extension"

    # Start a minimal dbus session to reduce Chrome errors
    eval $(dbus-launch --sh-syntax)
    export DBUS_SESSION_BUS_ADDRESS

    # Clean up stale Chrome lock files from previous runs
    PROFILE_DIR="/workspace/.chrome-profile"
    if [ -d "$PROFILE_DIR" ]; then
        rm -f "$PROFILE_DIR/SingletonLock" "$PROFILE_DIR/.lock" "$PROFILE_DIR/lockfile"
        echo "Cleaned up stale Chrome profile locks"
    fi

    # Launch Chrome in the background
    # Claude Code connects to Chrome via the extension
    # Redirect stderr to suppress harmless dbus/GPU errors
    google-chrome \
        --no-first-run \
        --no-default-browser-check \
        --disable-default-apps \
        --disable-sync \
        --disable-gpu \
        --disable-software-rasterizer \
        --disable-dev-shm-usage \
        --log-level=3 \
        --silent-debugger-extension-api \
        --user-data-dir="$PROFILE_DIR" \
        "https://claude.ai" \
        >/dev/null 2>&1 &

    CHROME_PID=$!

    # Wait for Chrome to initialize and extension to install
    echo "Waiting for Chrome to initialize (PID: $CHROME_PID)..."
    sleep 5

    # Check if extension directory exists
    EXT_DIR="/workspace/.chrome-profile/Default/Extensions/fcoeoabgfenejglbffodgkkbkcdhcgfn"
    if [ -d "$EXT_DIR" ]; then
        echo "✓ Claude extension installed"
    else
        echo "⚠ Claude extension not found - may download on first use"
    fi

    echo "Chrome started on DISPLAY=$DISPLAY"
}

case "$BROWSER_MODE" in
    chrome)
        # Full Chrome mode for claude --chrome
        start_xvfb
        start_vnc
        start_chrome
        echo "Chrome mode: DISPLAY=$DISPLAY"
        ;;
    playwright)
        # Playwright MCP - optionally headed for debugging
        if [ "$ENABLE_VNC" = "true" ]; then
            start_xvfb
            start_vnc
            echo "Playwright headed mode: DISPLAY=$DISPLAY"
        else
            unset DISPLAY
            echo "Playwright headless mode"
        fi
        ;;
    none)
        # No browser mode - neither Chrome nor Playwright GUI
        unset DISPLAY
        echo "Browser mode disabled"
        ;;
    *)
        echo "Unknown BROWSER_MODE: $BROWSER_MODE"
        exit 1
        ;;
esac

# Initialize Claude settings with statusline on first run
CLAUDE_SETTINGS="/workspace/.claude/settings.json"
if [[ ! -f "$CLAUDE_SETTINGS" ]]; then
    mkdir -p "$(dirname "$CLAUDE_SETTINGS")"
    cat > "$CLAUDE_SETTINGS" <<'EOF'
{
  "statusLine": {
    "type": "command",
    "command": "bash /usr/local/bin/agent-statusline.sh"
  }
}
EOF
fi

# Auto-sync repository if configured
if [[ "$REPO_AUTO_SYNC" == "true" ]]; then
    echo "Auto-syncing repository: $REPO_NAME"
    cd "/workspace/$REPO_NAME" 2>/dev/null || true
    if [[ -d .git ]]; then
        git pull --ff-only 2>&1 | head -5
    fi
    cd /workspace
fi

# Execute the command passed to the container
exec "$@"
