#!/bin/bash
# Refresh the claude-ha-agent container image: pull base, build, push, prune.
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CONTAINERIZE_DIR="$SCRIPT_DIR/../containerize"

export XDG_RUNTIME_DIR=/run/user/$(id -u)

echo "=== Pulling latest base image ==="
podman --cgroup-manager=cgroupfs pull node:22-bookworm

echo "=== Building container image ==="
"$CONTAINERIZE_DIR/build.sh"

echo "=== Pushing image ==="
"$CONTAINERIZE_DIR/push_image.sh"

echo "=== Removing dangling image layers ==="
DANGLING=$(podman images --filter dangling=true -q)
if [ -n "$DANGLING" ]; then
    echo "$DANGLING" | xargs podman rmi 2>&1 | grep -v "image is in use" || true
    echo "Removed dangling layers (skipped any in use by running containers)."
else
    echo "No dangling layers found."
fi

echo "=== Done ==="
