#!/bin/bash
# Start claude-ha-agent container with least-privilege configuration
# Uses rootless Podman with --userns=keep-id for UID mapping
#
# Usage:
#   start-ha-agent          # start Claude Code
#   start-ha-agent --test   # run preflight and network connectivity tests
#   start-ha-agent bash     # start bash shell
set -e

AGENT_USER="ha_agent"
AGENT_HOME="/home/$AGENT_USER"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Re-exec as ha_agent if not already
if [[ "$(id -un)" != "$AGENT_USER" ]]; then
    exec sudo -iu "$AGENT_USER" "$AGENT_HOME/start_container.sh" "$@"
fi

CONTAINER_NAME="claude-ha-agent"

# Load configuration
source "$SCRIPT_DIR/config.sh"

export XDG_RUNTIME_DIR=/run/user/$(id -u)

# Create directories if they don't exist
mkdir -p "$AGENT_HOME/workspace" "$AGENT_HOME/sessions"

# Handle --test flag
if [[ "$1" == "--test" ]]; then
    exec "$SCRIPT_DIR/test_container.sh" all
fi

# Run preflight checks (exit on failure)
"$SCRIPT_DIR/test_container.sh" preflight || exit 1

# Load tokens for CLI tools
GH_TOKEN=$(cat "$AGENT_HOME/workspace/.secrets/github_token")
# ANTHROPIC_API_KEY=$(cat "$AGENT_HOME/workspace/.secrets/anthropic_api_key")  # using OAuth token instead
HA_ACCESS_TOKEN=$(cat "$AGENT_HOME/workspace/.secrets/ha_access_token")

# Remove old container if exists
podman --cgroup-manager=cgroupfs rm -f "$CONTAINER_NAME" 2>/dev/null || true

# Start container with TTY
exec podman --cgroup-manager=cgroupfs run --rm -it \
    --name "$CONTAINER_NAME" \
    --userns=keep-id \
    -v "$AGENT_HOME/workspace":/workspace:Z \
    -v "$AGENT_HOME/sessions":/sessions:Z \
    -w "/workspace/$REPO_NAME" \
    --network=ha-agent-net \
    -e HTTP_PROXY=http://host.containers.internal:8888 \
    -e HTTPS_PROXY=http://host.containers.internal:8888 \
    -e NO_PROXY="api.anthropic.com,claude.ai,platform.claude.com,anthropic.com" \
    -e HOME=/workspace \
    -e GH_TOKEN="$GH_TOKEN" \
    -e HA_ACCESS_TOKEN="$HA_ACCESS_TOKEN" \
    "$CONTAINER_NAME" \
    "${@:-claude $CLAUDE_ARGS}"