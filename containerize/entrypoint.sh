#!/bin/bash
# Entrypoint script for claude-ha-agent container
# Native Claude Code auto-updates in the background
# Supports optional Chrome GUI mode with Xvfb/VNC for browser automation

set -e

BROWSER_MODE=${BROWSER_MODE:-none}
ENABLE_VNC=${ENABLE_VNC:-false}

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
