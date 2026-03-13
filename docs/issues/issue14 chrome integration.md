## Problem Statement

Users shall have the option to use either:
1. Playwright MCP - Programmatic browser automation (works headless, no GUI required)
2. Claude `--chrome` option (available from 2.0.78 onwards) - Full browser with Claude extension (requires GUI)

For the `--chrome` option, a graphical Chrome instance is required. Headless mode is not supported for this use case.
To maintain security and environment consistency, we run this inside an isolated container.
Chrome must run in sandbox mode (no `--no-sandbox` flag).
The container must execute with minimal privileges in rootless mode (no `--cap-add=SYS_ADMIN`).
Note: Standard X11 forwarding from the host is not an option because it compromises isolation.

## Requirements

* Engine: Must run using Podman in rootless mode.
* Display: Must provide a virtual display buffer (X-server) inside the container for `--chrome` mode.
* Chrome Integration: Requires `--shm-size=2g` and appropriate seccomp profile for sandbox support.
* Network: Isolated network stack with optional proxy support (implementation out of scope for this issue)
* Environment variables control mode:
  - `BROWSER_MODE=chrome` - Enable full Chrome with GUI for `--chrome` option
  - `BROWSER_MODE=playwright` - Playwright MCP, optionally headed for debugging
  - `ENABLE_VNC=true` - Enable VNC server for remote observation
  - By default, neither Chrome nor Playwright are enabled

---

## Proposed Isolation Options

AI agent may visit untrusted or adversarial websites. As it is currently not feasible to defend completely against prompt injection attacks, the agent must be sandboxed with a high security level.

### Option A: Pure Xvfb (headless from the user perspective)
Run a virtual framebuffer in memory only.
* Pros: Lowest overhead, maximum performance.
* Cons: Zero visibility. If the agent hangs on a CAPTCHA or unexpected modal, debugging is next to impossible.

### Option B: Xvfb + VNC (Preferred)

Run Xvfb with a VNC server (e.g., `x11vnc`) layered on top.
* Why this is preferred:
  * Observability: Provides the ability to "attach" a viewer to the container in real-time to monitor agent behavior.
  * Low Overhead: When no VNC client is connected, the performance cost is negligible compared to pure Xvfb.
  * Reliability: Easier to troubleshoot "agent-loops" or rendering issues that only appear in GUI-mode.

### Option C: Headless Wayland (Sway/Weston)
The modern alternative to X11, offering better security and native isolation between windows.
* Pros: Native window isolation (more secure than X11); future-proof.
* Cons: Higher complexity; x11vnc is incompatible—requires Wayland-specific tools like wayvnc for observability.

### Option D: Hardware-Isolated MicroVMs (Kata & libkrun)
Using a MicroVM runtime ensures the agent runs in its own dedicated virtual kernel. Podman supports this with the `--runtime` option.

1. libkrun (Performance Focused)
   libkrun is a dynamic library that allows programs to run in a tiny VM as if they were a process. It is generally the easiest "MicroVM" to run rootless.
   * Pros: Extremely fast boot; minimal resource footprint.
   * Cons: Less mature than Kata; requires host support for KVM.

2. Kata Containers (Production Standard)
   Kata Containers provides a more robust, "VM-as-a-Pod" experience. It is the enterprise standard for hardware isolation.
   * Pros: Strongest security boundary; supports different hypervisors (QEMU, Firecracker).
   * Cons: Slightly slower boot than libkrun; requires more complex host configuration.

---

## Proposed Implementation

- Add Xvfb and x11vnc for virtual display
- Add Google Chrome Stable
- Install the Claude in Chrome extension (for `--chrome` mode only)
- Configure custom seccomp profile enabling Chrome sandbox
- Start services conditionally based on `BROWSER_MODE`

### Dockerfile Additions (based on node:22-bookworm)

1. Install Chrome dependencies and X11 tools
```dockerfile
RUN apt-get update && apt-get install -y \
    wget \
    gnupg \
    ca-certificates \
    xvfb \
    x11vnc \
    dbus-x11 \
    libnss3 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxcomposite1 \
    libxdamage1 \
    libxrandr2 \
    libgbm1 \
    libasound2 \
    x11-utils \
    --no-install-recommends && \
    rm -rf /var/lib/apt/lists/*
```

2. Install Google Chrome Stable
```dockerfile
RUN wget -q -O - https://dl-ssl.google.com/linux/linux_signing_key.pub | gpg --dearmor > /usr/share/keyrings/google-chrome.gpg && \
    echo "deb [arch=amd64 signed-by=/usr/share/keyrings/google-chrome.gpg] http://dl.google.com/linux/chrome/deb/ stable main" \
    > /etc/apt/sources.list.d/google-chrome.list && \
    apt-get update && apt-get install -y google-chrome-stable --no-install-recommends && \
    rm -rf /var/lib/apt/lists/*
```

3. Pre-configure the Claude Extension (for `--chrome` mode)
```dockerfile
# Official Extension ID for Claude in Chrome (Beta)
RUN mkdir -p /opt/google/chrome/extensions && \
    echo '{ "external_update_url": "https://clients2.google.com/service/update2/crx" }' \
    > /opt/google/chrome/extensions/fcoeoabgfenejglbffodgkkbkcdhcgfn.json
```

4. Add custom seccomp profile
```dockerfile
COPY seccomp/chrome.json /etc/seccomp/chrome.json
```

### Chrome Seccomp Profile

Chrome's sandbox fails in containers because Podman's default security profile blocks the `unshare` syscall and restricts `clone` with `CLONE_NEWUSER` flag—both require `CAP_SYS_ADMIN` in the default profile.

The full profile is at `containerize/seccomp/chrome.json`. It is based on [Moby's default seccomp profile (v0.1.0)](https://github.com/moby/profiles/blob/seccomp/v0.1.0/seccomp/default.json) with Chrome-specific modifications:

**Chrome-specific additions (at the start of syscalls array):**
```json
{
    "comment": "CHROME MODIFICATION: Allow unshare unconditionally (Moby default requires CAP_SYS_ADMIN)",
    "names": ["unshare"],
    "action": "SCMP_ACT_ALLOW"
},
{
    "comment": "CHROME MODIFICATION: Allow clone/clone3 with all flags unconditionally",
    "names": ["clone", "clone3"],
    "action": "SCMP_ACT_ALLOW"
}
```

**Why this works:**
- Moby default allows `unshare` only with `CAP_SYS_ADMIN` capability
- Moby default blocks `clone` with namespace flags (value `0x7E020000` = `CLONE_NEWUSER | CLONE_NEWPID | ...`) without `CAP_SYS_ADMIN`
- Our profile allows these unconditionally, enabling Chrome's sandbox in rootless Podman

**Security note:** This profile is more permissive than the Moby default for namespace operations. The container's user namespace isolation (rootless Podman) provides the primary security boundary.

### Container Startup

Add following options to `podman run`:
```bash
--shm-size=2g \
--security-opt seccomp=containerize/seccomp/chrome.json
```

For VNC access during debugging (localhost only by default):
```bash
# Connect via: podman exec -it <container> vncviewer localhost:5900
# Or expose port for remote access (development only):
# -p 5900:5900
```

entrypoint.sh:
```bash
#!/bin/bash
set -e

BROWSER_MODE=${BROWSER_MODE:-playwright}
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
    *)
        echo "Unknown BROWSER_MODE: $BROWSER_MODE"
        exit 1
        ;;
esac

exec "$@"
```

Note: VNC binds to localhost only. To connect remotely, use `podman exec` to establish a tunnel, or explicitly expose port 5900 for development/debugging.

### Integration Test

This script runs inside the container to verify the stack:

```bash
#!/bin/bash
set -e

echo "=== Chrome Integration Test ==="

# 1. Check if the DISPLAY is active
if ! xdpyinfo -display :99 >/dev/null 2>&1; then
    echo "FAIL: X-server (Xvfb) is not running on :99"
    exit 1
fi
echo "PASS: Xvfb is running"

# 2. Start Chrome with CDP (Chrome DevTools Protocol)
google-chrome \
    --remote-debugging-port=9222 \
    --disable-gpu \
    --no-first-run \
    --disable-default-apps \
    "https://example.com" &
CHROME_PID=$!
echo "Started Chrome (PID: $CHROME_PID)"

# 3. Wait for Chrome to initialize
sleep 5

# 4. Verify CDP is responding
if curl -s "http://localhost:9222/json" | jq -e '.[0].url' >/dev/null 2>&1; then
    PAGE_URL=$(curl -s "http://localhost:9222/json" | jq -r '.[0].url')
    echo "PASS: Chrome CDP active, loaded: $PAGE_URL"
else
    echo "FAIL: Chrome CDP not responding"
    kill $CHROME_PID 2>/dev/null
    exit 1
fi

# 5. Cleanup
kill $CHROME_PID 2>/dev/null
echo "=== All tests passed ==="
exit 0
```

To force the test to fail, start podman with `--network none`.

---

## Next Steps

1. Update the Dockerfile to include Chrome, Xvfb, and x11vnc
2. ~~Create the custom seccomp profile~~ ✓ Done: `containerize/seccomp/chrome.json`
3. Test the seccomp profile: verify Chrome runs with sandbox enabled (no `--no-sandbox`)
4. Test Playwright MCP in headed mode with VNC observation
5. Test Claude `--chrome` option connects to the Chrome instance
6. Document VNC connection methods for debugging

---
