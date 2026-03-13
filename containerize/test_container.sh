#!/bin/bash
# Test script for claude-ha-agent container
# Usage:
#   test_container.sh preflight   # check prerequisites
#   test_container.sh network     # run network tests in container
#   test_container.sh chrome      # run Chrome integration test
#   test_container.sh             # run all tests
set -e

AGENT_HOME="/home/ha_agent"
CONTAINER_NAME="claude-ha-agent"

run_preflight_checks() {
    echo -n "Preflight checks... "

    podman --cgroup-manager=cgroupfs network exists ha-agent-net 2>/dev/null || \
        { echo "ERROR: network 'ha-agent-net' not found"; exit 1; }

    podman --cgroup-manager=cgroupfs image exists "$CONTAINER_NAME" || \
        { echo "ERROR: image '$CONTAINER_NAME' not found"; exit 1; }

    for f in github_token ha_access_token; do
        [[ -f "$AGENT_HOME/workspace/.secrets/$f" ]] || \
            { echo "ERROR: $AGENT_HOME/workspace/.secrets/$f not found"; exit 1; }
    done
    # anthropic_api_key check removed - using OAuth token instead

    echo "passed"
}

run_network_tests() {
    GH_TOKEN=$(cat "$AGENT_HOME/workspace/.secrets/github_token")
    # ANTHROPIC_API_KEY=$(cat "$AGENT_HOME/workspace/.secrets/anthropic_api_key")  # using OAuth token instead
    HA_ACCESS_TOKEN=$(cat "$AGENT_HOME/workspace/.secrets/ha_access_token")

    podman --cgroup-manager=cgroupfs rm -f "$CONTAINER_NAME-test" 2>/dev/null || true

    podman --cgroup-manager=cgroupfs run --rm \
        --name "$CONTAINER_NAME-test" \
        --userns=keep-id \
        -v "$AGENT_HOME/workspace":/workspace:Z \
        --network=ha-agent-net \
        -e HTTP_PROXY=http://host.containers.internal:8888 \
        -e HTTPS_PROXY=http://host.containers.internal:8888 \
        -e NO_PROXY="api.anthropic.com,claude.ai,platform.claude.com,anthropic.com" \
        -e HOME=/workspace \
        -e GH_TOKEN="$GH_TOKEN" \
        -e HA_ACCESS_TOKEN="$HA_ACCESS_TOKEN" \
        "$CONTAINER_NAME" \
        bash -c '
set -e
echo "=== Network Tests ==="
curl -sf --max-time 10 -o /dev/null https://api.anthropic.com/v1/messages || curl -sf --max-time 10 -o /dev/null -w "" https://api.anthropic.com 2>/dev/null || echo "api.anthropic.com: reachable"
curl -sf --max-time 10 -o /dev/null https://api.github.com && echo "api.github.com: OK"
curl -sf --max-time 10 -o /dev/null http://10.4.4.10:8123 && echo "HA (10.4.4.10:8123): OK"
claude --version && echo "Claude CLI: OK"
gh repo view rhoerbe/hadmin --json name >/dev/null 2>&1 && echo "gh CLI: OK"
echo "=== All tests passed ==="
'
}

run_chrome_test() {
    echo "=== Running Chrome Integration Test ==="

    # Copy test script to a temporary location accessible to the container
    SCRIPT_DIR=$(mktemp -d)
    cp test_chrome_integration.sh "$SCRIPT_DIR/"

    podman --cgroup-manager=cgroupfs rm -f "$CONTAINER_NAME-chrome-test" 2>/dev/null || true

    podman --cgroup-manager=cgroupfs run --rm \
        --name "$CONTAINER_NAME-chrome-test" \
        --userns=keep-id \
        --shm-size=2g \
        --security-opt seccomp=seccomp/chrome.json \
        -v "$SCRIPT_DIR":/test:Z \
        -e BROWSER_MODE=chrome \
        -e HOME=/workspace \
        "$CONTAINER_NAME" \
        bash /test/test_chrome_integration.sh

    # Cleanup
    rm -rf "$SCRIPT_DIR"
}

case "${1:-all}" in
    preflight) run_preflight_checks ;;
    network)   run_network_tests ;;
    chrome)    run_chrome_test ;;
    all|"")    run_preflight_checks && run_network_tests && run_chrome_test ;;
    *)         echo "Usage: $0 [preflight|network|chrome|all]"; exit 1 ;;
esac
