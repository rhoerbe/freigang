#!/bin/bash
# Start claude-ha-agent container with least-privilege configuration
# Uses rootless Podman with --userns=keep-id for UID mapping
#
# Usage:
#   start-ha-agent          # start Claude Code
#   start-ha-agent --test   # run network connectivity tests
#   start-ha-agent bash     # start bash shell
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

# Load tokens for CLI tools
GH_TOKEN=$(cat "$AGENT_HOME/.secrets/github_token")
ANTHROPIC_API_KEY=$(cat "$AGENT_HOME/.secrets/anthropic_api_key")

# Network test script to run inside container
NETWORK_TEST_SCRIPT='
#!/bin/bash
RED="\033[0;31m"
GREEN="\033[0;32m"
NC="\033[0m"
PASSED=0
FAILED=0

test_url() {
    local name="$1"
    local url="$2"
    local expected="$3"

    code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 "$url" 2>/dev/null)
    if [[ "$code" =~ ^($expected)$ ]]; then
        echo -e "${GREEN}[PASS]${NC} $name (HTTP $code)"
        PASSED=$((PASSED + 1))
    else
        echo -e "${RED}[FAIL]${NC} $name (HTTP $code, expected $expected)"
        FAILED=$((FAILED + 1))
    fi
}

echo "========================================"
echo "Container Network Connectivity Tests"
echo "========================================"
echo ""

# Test Anthropic API (direct, NO_PROXY)
echo "--- Anthropic/Claude (direct) ---"
test_url "api.anthropic.com" "https://api.anthropic.com/v1/messages" "401|403|404|405"
test_url "platform.claude.com" "https://platform.claude.com" "200|301|302"

# Test via proxy
echo ""
echo "--- Via Proxy ---"
test_url "GitHub API" "https://api.github.com" "200"
test_url "GitHub raw" "https://raw.githubusercontent.com" "200|301|400"
test_url "npmjs registry" "https://registry.npmjs.org" "200"

# Test Home Assistant
echo ""
echo "--- Home Assistant ---"
test_url "HA Web UI" "http://10.4.4.10:8123" "200"

HA_TOKEN=$(cat /run/secrets/ha_access_token 2>/dev/null)
if [[ -n "$HA_TOKEN" ]]; then
    code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 \
        -H "Authorization: Bearer $HA_TOKEN" \
        "http://10.4.4.10:8123/api/" 2>/dev/null)
    if [[ "$code" == "200" || "$code" == "201" ]]; then
        echo -e "${GREEN}[PASS]${NC} HA API authenticated (HTTP $code)"
        PASSED=$((PASSED + 1))
    else
        echo -e "${RED}[FAIL]${NC} HA API authenticated (HTTP $code)"
        FAILED=$((FAILED + 1))
    fi
fi

# Test Claude CLI
echo ""
echo "--- Claude CLI ---"
if claude --version >/dev/null 2>&1; then
    echo -e "${GREEN}[PASS]${NC} Claude CLI: $(claude --version)"
    PASSED=$((PASSED + 1))
else
    echo -e "${RED}[FAIL]${NC} Claude CLI not working"
    FAILED=$((FAILED + 1))
fi

# Test gh CLI
echo ""
echo "--- GitHub CLI ---"
if gh auth status >/dev/null 2>&1; then
    echo -e "${GREEN}[PASS]${NC} gh CLI authenticated"
    PASSED=$((PASSED + 1))
else
    # Try with token
    if gh repo view rhoerbe/hadmin --json name >/dev/null 2>&1; then
        echo -e "${GREEN}[PASS]${NC} gh CLI working (via GH_TOKEN)"
        PASSED=$((PASSED + 1))
    else
        echo -e "${RED}[FAIL]${NC} gh CLI not authenticated"
        FAILED=$((FAILED + 1))
    fi
fi

echo ""
echo "========================================"
echo "Results: $PASSED passed, $FAILED failed"
echo "========================================"

[[ $FAILED -eq 0 ]]
'

# Handle --test flag
if [[ "$1" == "--test" ]]; then
    echo "Running network connectivity tests..."
    echo ""

    podman --cgroup-manager=cgroupfs rm -f "$CONTAINER_NAME" 2>/dev/null || true

    podman --cgroup-manager=cgroupfs run --rm \
        --name "$CONTAINER_NAME-test" \
        --userns=keep-id \
        -v "$AGENT_HOME/.claude":/workspace/.claude:Z \
        --secret anthropic_api_key,target=/run/secrets/anthropic_api_key \
        --secret github_token,target=/run/secrets/github_token \
        --secret ha_access_token,target=/run/secrets/ha_access_token \
        --network=ha-agent-net \
        -e HTTP_PROXY=http://host.containers.internal:8888 \
        -e HTTPS_PROXY=http://host.containers.internal:8888 \
        -e NO_PROXY="api.anthropic.com,claude.ai,platform.claude.com,anthropic.com" \
        -e HOME=/workspace \
        -e GH_TOKEN="$GH_TOKEN" \
        -e ANTHROPIC_API_KEY="$ANTHROPIC_API_KEY" \
        "$CONTAINER_NAME" \
        bash -c "$NETWORK_TEST_SCRIPT"

    exit $?
fi

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
    -e ANTHROPIC_API_KEY="$ANTHROPIC_API_KEY" \
    "$CONTAINER_NAME" \
    "${@:-claude}"
