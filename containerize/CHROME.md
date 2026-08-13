# Chrome Integration Guide

## Overview

The container supports running Google Chrome in GUI mode for browser automation, with two modes:
1. **Playwright MCP** - Programmatic browser automation (works headless, no GUI required)
2. **Claude `--chrome` option** - Full browser with Claude extension (requires GUI)

Chrome runs in sandbox mode (no `--no-sandbox`) inside a rootless Podman container with minimal privileges.

## Environment Variables

- `BROWSER_MODE=chrome` - Enable full Chrome with GUI for `--chrome` option
- `BROWSER_MODE=playwright` - Playwright MCP, optionally headed for debugging
- `BROWSER_MODE=none` - Default, neither Chrome nor Playwright GUI enabled
- `ENABLE_VNC=true` - Enable VNC server for remote observation (localhost only by default)

## Running Chrome Mode

### Basic Chrome Mode
```bash
podman run --rm \
    --userns=keep-id \
    --shm-size=2g \
    --security-opt seccomp=containerize/seccomp/chrome.json \
    -e BROWSER_MODE=chrome \
    -e HOME=/workspace \
    -v "$PWD":/workspace:Z \
    claude-ha-agent \
    claude --chrome
```

### With VNC for Observation
```bash
podman run --rm \
    --userns=keep-id \
    --shm-size=2g \
    --security-opt seccomp=containerize/seccomp/chrome.json \
    -e BROWSER_MODE=chrome \
    -e ENABLE_VNC=true \
    -e HOME=/workspace \
    -v "$PWD":/workspace:Z \
    claude-ha-agent \
    claude --chrome
```

### Connecting to VNC

`x11vnc` inside the container runs with `-nopw` (no password). `start_container.sh`
publishes it to the host as `127.0.0.1:5900` only, so the session is reachable
from the host itself but not from the network. To connect:

```bash
# From another terminal, exec into the running container
podman exec -it <container-name> vncviewer localhost:5900

# Or, from the host (loopback-only publish):
vncviewer 127.0.0.1:5900

# Do NOT rebind to all interfaces (e.g. -p 5900:5900) — x11vnc has no
# password, so that exposes an unauthenticated session to the network.
```

## Required Podman Options

### `--shm-size=2g`
Chrome requires shared memory for rendering. Default is 64MB, which is insufficient.

### `--security-opt seccomp=containerize/seccomp/chrome.json`
Custom seccomp profile that allows Chrome's sandbox to work in rootless Podman.
- Allows `unshare` syscall unconditionally
- Allows `clone`/`clone3` with namespace flags unconditionally
- Based on Moby default profile with Chrome-specific modifications

## Architecture

### Display Stack
- **Xvfb** - Virtual framebuffer (X11 server in memory)
- **x11vnc** - VNC server (optional, for observation)
- **Chrome** - Runs in sandbox mode on the virtual display

### Extension Installation
The Claude Chrome extension (ID: `fcoeoabgfenejglbffodgkkbkcdhcgfn`) is configured for automatic installation via Chrome's enterprise policy (`ExtensionInstallForcelist`).

On first startup:
- Chrome will download the extension from the Chrome Web Store
- This requires internet access (respects HTTP_PROXY settings)
- The extension connects to Claude Code via local communication
- First run may take a few extra seconds for extension download

### Security Model
- Rootless Podman provides user namespace isolation
- Chrome runs in its own sandbox (enabled via custom seccomp profile)
- No `CAP_SYS_ADMIN` or other elevated capabilities required
- VNC is published to the host's loopback interface only (`127.0.0.1:5900`)
  by `start_container.sh`; `x11vnc` itself runs without a password (`-nopw`)

## Known Issues

### Chrome + VNC Mode
**Status:** Partial functionality - Chrome starts but extension connection unreliable

The Chrome browser launches successfully with VNC enabled, but the Claude Chrome extension may not connect properly to Claude Code. This is under investigation.

**Workaround:** Use Playwright mode for reliable browser automation:
```bash
./start_container.sh --browser=playwright
```

**Symptoms:**
- Chrome starts and displays on VNC
- Extension shows as not connected
- Claude Code cannot control the browser

## Testing

### Run Chrome Integration Test
```bash
cd containerize
./test_container.sh chrome
```

### Manual Chrome Test
```bash
podman run --rm \
    --userns=keep-id \
    --shm-size=2g \
    --security-opt seccomp=containerize/seccomp/chrome.json \
    -e BROWSER_MODE=chrome \
    -e HOME=/workspace \
    -v "$PWD":/workspace:Z \
    claude-ha-agent \
    bash /workspace/test_chrome_integration.sh
```

## Troubleshooting

### Chrome crashes with "namespace sandbox failed"
- Ensure `--security-opt seccomp=containerize/seccomp/chrome.json` is set
- Verify the seccomp profile path is correct (relative to working directory)

### Chrome crashes with "shared memory" errors
- Ensure `--shm-size=2g` is set (default 64MB is too small)

### VNC connection refused
- VNC is published to the host's loopback interface only (`127.0.0.1:5900`)
- Use `podman exec` to connect from inside the container, or `vncviewer 127.0.0.1:5900` from the host
- Do not rebind to all interfaces — `x11vnc` runs with `-nopw` (no password), so that would expose an unauthenticated session

### X server not found
- Ensure `BROWSER_MODE=chrome` is set
- Check container logs for Xvfb startup messages
- Verify `DISPLAY=:99` is set in the container environment

## Playwright MCP Mode

For Playwright MCP with optional headed mode:

```bash
podman run --rm \
    --userns=keep-id \
    --shm-size=2g \
    --security-opt seccomp=containerize/seccomp/chrome.json \
    -e BROWSER_MODE=playwright \
    -e ENABLE_VNC=true \
    -e HOME=/workspace \
    -v "$PWD":/workspace:Z \
    claude-ha-agent \
    claude
```

Playwright will use Chromium in headless mode by default, or headed mode with VNC if `ENABLE_VNC=true`.

## References

- Issue #14 specification: `docs/issues/issue14 chrome integration.md`
- Seccomp profile: `containerize/seccomp/chrome.json`
- Integration test: `containerize/test_chrome_integration.sh`
