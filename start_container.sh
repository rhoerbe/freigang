#!/bin/bash
# Start claude-ha-agent container with least-privilege configuration
# Run as: ha_agent user
# Uses rootless Podman with --userns=keep-id for UID mapping
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CONTAINER_NAME="claude-ha-agent"

export XDG_RUNTIME_DIR=/run/user/$(id -u)

# Create directories if they don't exist
mkdir -p "$SCRIPT_DIR/workspace" "$SCRIPT_DIR/sessions"

# Preflight checks
echo "Preflight checks..."

if ! podman --cgroup-manager=cgroupfs network exists ha-agent-net 2>/dev/null; then
    echo "ERROR: podman network 'ha-agent-net' not found"
    echo "Create with: podman --cgroup-manager=cgroupfs network create ha-agent-net --subnet 10.89.1.0/24"
    exit 1
fi

for secret in anthropic_api_key github_token ha_access_token; do
    if ! podman --cgroup-manager=cgroupfs secret inspect "$secret" &>/dev/null; then
        echo "ERROR: podman secret '$secret' not found"
        exit 1
    fi
done

if ! podman --cgroup-manager=cgroupfs image exists "$CONTAINER_NAME"; then
    echo "ERROR: container image '$CONTAINER_NAME' not found"
    echo "Build with: podman --cgroup-manager=cgroupfs build -t $CONTAINER_NAME ."
    exit 1
fi

echo "Preflight checks passed."

# Remove old container if exists
podman --cgroup-manager=cgroupfs rm -f "$CONTAINER_NAME" 2>/dev/null || true

# Start container
exec podman --cgroup-manager=cgroupfs run --rm -it \
    --name "$CONTAINER_NAME" \
    --userns=keep-id \
    -v "$SCRIPT_DIR/workspace":/workspace:Z \
    -v "$SCRIPT_DIR/sessions":/sessions:Z \
    --secret anthropic_api_key,target=/run/secrets/anthropic_api_key \
    --secret github_token,target=/run/secrets/github_token \
    --secret ha_access_token,target=/run/secrets/ha_access_token \
    --network=ha-agent-net \
    -e HTTP_PROXY=http://host.containers.internal:8888 \
    -e HTTPS_PROXY=http://host.containers.internal:8888 \
    -e HOME=/workspace \
    "$CONTAINER_NAME" \
    "${@:-bash}"
