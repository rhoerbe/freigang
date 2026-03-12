#!/bin/bash
# Build claude-ha-agent container image
set -e

cd "$(dirname "$0")"

export XDG_RUNTIME_DIR=/run/user/$(id -u)

# WEEKLY_CACHE_BUST forces weekly re-download of yq and Playwright without invalidating bottom tier
# CLAUDE_CACHE_BUST forces daily re-download of Claude Code without invalidating earlier layers
podman --cgroup-manager=cgroupfs build \
    --build-arg WEEKLY_CACHE_BUST=$(date +%Y-%V) \
    --build-arg CLAUDE_CACHE_BUST=$(date +%Y-%m-%d) \
    -t claude-ha-agent .

echo "Build complete. Image: localhost/claude-ha-agent:latest"
podman --cgroup-manager=cgroupfs images claude-ha-agent
