#!/bin/bash
# Start claude-ha-agent container with least-privilege configuration
# Uses rootless Podman with --userns=keep-id for UID mapping
#
# Can be run from anywhere - automatically switches to ha_agent user
set -e

AGENT_USER="ha_agent"
AGENT_HOME="/home/$AGENT_USER"

# Re-exec as ha_agent if not already
if [[ "$(id -un)" != "$AGENT_USER" ]]; then
    exec sudo -iu "$AGENT_USER" "$AGENT_HOME/start_container.sh" "$@"
fi

CONTAINER_NAME="claude-ha-agent"

export XDG_RUNTIME_DIR=/run/user/$(id -u)

# Create directories if they don't exist
mkdir -p "$AGENT_HOME/workspace" "$AGENT_HOME/sessions"

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

# Load GitHub token for gh CLI
GH_TOKEN=$(cat "$AGENT_HOME/.secrets/github_token")

# Remove old container if exists
podman --cgroup-manager=cgroupfs rm -f "$CONTAINER_NAME" 2>/dev/null || true

# Start container with TTY
exec podman --cgroup-manager=cgroupfs run --rm -it \
    --name "$CONTAINER_NAME" \
    --userns=keep-id \
    -v "$AGENT_HOME/.claude":/workspace/.claude:Z \
    -v "$AGENT_HOME/workspace":/workspace/code:Z \
    -v "$AGENT_HOME/sessions":/sessions:Z \
    --secret anthropic_api_key,target=/run/secrets/anthropic_api_key \
    --secret github_token,target=/run/secrets/github_token \
    --secret ha_access_token,target=/run/secrets/ha_access_token \
    --network=ha-agent-net \
    -e HTTP_PROXY=http://host.containers.internal:8888 \
    -e HTTPS_PROXY=http://host.containers.internal:8888 \
    -e NO_PROXY="api.anthropic.com,claude.ai,platform.claude.com,anthropic.com" \
    -e HOME=/workspace \
    -e GH_TOKEN="$GH_TOKEN" \
    "$CONTAINER_NAME" \
    "${@:-claude}"
