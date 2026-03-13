#!/bin/bash
# Entrypoint script for claude-ha-agent container
# Native Claude Code auto-updates in the background
# Supports optional Chrome GUI mode with Xvfb/VNC for browser automation

set -e

BROWSER_MODE=${BROWSER_MODE:-none}
ENABLE_VNC=${ENABLE_VNC:-false}

start_xvfb() {
    echo "Starting Xvfb on :99"
    Xvfb :99 -screen 0 1920x1080x24 &
    export DISPLAY=:99
    # Wait for X server to be ready
    for i in {1..10}; do
        xdpyinfo -display :99 >/dev/null 2>&1 && break
        sleep 0.5
    done
}

start_vnc() {
    if [ "$ENABLE_VNC" = "true" ]; then
        echo "Starting x11vnc (localhost only)"
        x11vnc -display :99 -forever -localhost -quiet &
    fi
}

case "$BROWSER_MODE" in
    chrome)
        # Full Chrome mode for claude --chrome
        start_xvfb
        start_vnc
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

# Execute the command passed to the container
exec "$@"
