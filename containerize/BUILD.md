# Container Build and Distribution

## Build

Run as your normal user (e.g. `r2h2`) from the repo root:

```bash
cd containerize
./build.sh
```

This runs `podman build` and tags the result `localhost/claude-ha-agent:latest`.
Two cache-bust arguments control layer invalidation:

- `WEEKLY_CACHE_BUST` — forces weekly re-download of yq and Playwright
- `CLAUDE_CACHE_BUST` — forces daily re-download of Claude Code

## Transfer to the agent user

Rootless podman users have separate image stores, so the image must be explicitly
transferred to `ha_agent` after building:

```bash
cd containerize
./push_image.sh
```

This pipes `podman save | podman load` via sudo — no registry involved.
