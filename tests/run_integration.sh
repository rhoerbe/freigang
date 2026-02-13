#!/bin/bash
# Host integration script - starts container and runs tests
# Run as: ha_agent user
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CONTAINER_NAME="claude-ha-agent-test"

export XDG_RUNTIME_DIR=/run/user/$(id -u)

echo "========================================"
echo "Agent Container Integration Test Runner"
echo "========================================"
echo ""

# Preflight checks
echo "Preflight checks..."

# Check podman
if ! command -v podman &>/dev/null; then
    echo "ERROR: podman not found"
    exit 2
fi

# Check network exists
if ! podman --cgroup-manager=cgroupfs network exists ha-agent-net 2>/dev/null; then
    echo "ERROR: podman network 'ha-agent-net' not found"
    echo "Create with: podman network create ha-agent-net --subnet 10.89.1.0/24"
    exit 2
fi

# Check tinyproxy is running
if ! curl -s --max-time 2 -o /dev/null http://localhost:8888 2>/dev/null; then
    # Try via podman network gateway
    if ! curl -s --max-time 2 -o /dev/null http://10.89.1.1:8888 2>/dev/null; then
        echo "WARNING: tinyproxy may not be running on port 8888"
    fi
fi

# Check secrets exist
for secret in anthropic_api_key github_token ha_access_token; do
    if ! podman --cgroup-manager=cgroupfs secret inspect "$secret" &>/dev/null; then
        echo "ERROR: podman secret '$secret' not found"
        exit 2
    fi
done

# Check image exists
if ! podman --cgroup-manager=cgroupfs image exists claude-ha-agent; then
    echo "ERROR: container image 'claude-ha-agent' not found"
    echo "Build with: ./build.sh"
    exit 2
fi

echo "Preflight checks passed."
echo ""

# Cleanup any existing test container
podman --cgroup-manager=cgroupfs rm -f "$CONTAINER_NAME" 2>/dev/null || true

# Create screenshots directory
mkdir -p "$SCRIPT_DIR/screenshots"

echo "Starting test container..."

# Run tests in container
podman --cgroup-manager=cgroupfs run --rm \
    --name "$CONTAINER_NAME" \
    --userns=keep-id \
    -v "$SCRIPT_DIR":/tests:Z \
    --secret anthropic_api_key,target=/run/secrets/anthropic_api_key \
    --secret github_token,target=/run/secrets/github_token \
    --secret ha_access_token,target=/run/secrets/ha_access_token \
    --network=ha-agent-net \
    -e HTTP_PROXY=http://host.containers.internal:8888 \
    -e HTTPS_PROXY=http://host.containers.internal:8888 \
    -e HOME=/workspace \
    claude-ha-agent \
    /tests/run_tests.sh

EXIT_CODE=$?

echo ""
if [[ $EXIT_CODE -eq 0 ]]; then
    echo "All tests passed!"
else
    echo "Some tests failed (exit code: $EXIT_CODE)"
fi

exit $EXIT_CODE
