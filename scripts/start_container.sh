#!/bin/bash
# Start claude-ha-agent container with least-privilege configuration
# Uses rootless Podman with --userns=keep-id for UID mapping
#
# Usage:
#   start-ha-agent              # start Claude Code with TUI
#   start-ha-agent --quick      # start Claude Code without TUI (use defaults)
#   start-ha-agent --test       # run preflight and network connectivity tests
#   start-ha-agent bash         # start bash shell
#
# MCP Server Configuration Flow (local scope - per project):
#   1. Container has MCP manifest at /etc/freigang/mcp-manifest.json (installed servers)
#   2. TUI reads ~/.claude.json projects.<path>.mcpServers to show current MCP state
#   3. TUI merges with manifest to show available vs enabled servers
#   4. User selects/deselects servers in TUI
#   5. TUI writes to ~/.claude.json projects./workspace/$REPO_NAME.mcpServers
#   6. Claude reads its config on startup - automatically trusted (no approval needed)
#
#   Bi-directional sync: Changes via TUI or `claude mcp add -s local` are both visible.
#   Inside container: /workspace/.claude.json (projects key uses /workspace/$REPO_NAME)
#   On host: $AGENT_HOME/workspace/.claude.json
#
set -e

AGENT_USER="ha_agent"
AGENT_HOME="/home/$AGENT_USER"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Re-exec as ha_agent if not already
if [[ "$(id -un)" != "$AGENT_USER" ]]; then
    exec sudo -iu "$AGENT_USER" "$AGENT_HOME/start_container.sh" "$@"
fi

# Determine paths based on environment (development repo vs deployed agent home)
if [[ -d "$SCRIPT_DIR/../containerize" ]]; then
    # Development: running from repo's scripts/ directory
    REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
    TEST_CONTAINER_SH="$REPO_ROOT/containerize/test_container.sh"
    MCP_CONFIG_SRC="$REPO_ROOT/mcp-config.json"
else
    # Production: deployed to agent's home directory
    TEST_CONTAINER_SH="$SCRIPT_DIR/test_container.sh"
    MCP_CONFIG_SRC="$SCRIPT_DIR/mcp-config.json"
fi

# Load configuration
source "$SCRIPT_DIR/config.sh"

CONTAINER_NAME="$CONTAINER_IMAGE"

# TUI state variables
SELECTED_PERMISSION_MODE="$DEFAULT_PERMISSION_MODE"
SELECTED_SECRETS=("github_token")  # Default: only github_token on first start
SELECTED_SESSION=""
SELECTED_MCP_SERVER_NAMES=""  # For display only - actual config in Claude's settings.json
SELECTED_BROWSER_MODE="none"
SELECTED_ENABLE_VNC="false"
SKIP_TUI=false

# Parse initial arguments
while [[ $# -gt 0 ]]; do
    case "$1" in
        --quick)
            SKIP_TUI=true
            shift
            ;;
        --browser=*)
            SELECTED_BROWSER_MODE="${1#*=}"
            SKIP_TUI=true
            shift
            ;;
        --vnc)
            SELECTED_ENABLE_VNC="true"
            shift
            ;;
        --test)
            # Leave --test for later handling
            break
            ;;
        *)
            # Unknown option or command, stop parsing
            break
            ;;
    esac
done

# ============================================================================
# TUI Functions
# ============================================================================

get_mcp_manifest_from_container() {
    # Query MCP manifest embedded in the container image
    # Cache by image ID to avoid slow container startup on every launch
    local cache_dir="$AGENT_HOME/.cache/freigang"
    mkdir -p "$cache_dir"

    # Get current image ID
    local image_id
    image_id=$(podman --cgroup-manager=cgroupfs images --format '{{.ID}}' "$CONTAINER_IMAGE" 2>/dev/null)
    if [[ -z "$image_id" ]]; then
        echo ""
        return
    fi

    local manifest_file="$cache_dir/mcp-manifest-${image_id}.json"

    # Return cached manifest if it exists for this image
    if [[ -f "$manifest_file" ]]; then
        echo "$manifest_file"
        return
    fi

    # Extract manifest from container (only on first run or after image update)
    if podman --cgroup-manager=cgroupfs run --rm "$CONTAINER_IMAGE" cat /etc/freigang/mcp-manifest.json > "$manifest_file" 2>/dev/null; then
        # Clean up old cached manifests
        find "$cache_dir" -name 'mcp-manifest-*.json' ! -name "mcp-manifest-${image_id}.json" -delete 2>/dev/null || true
        echo "$manifest_file"
    else
        rm -f "$manifest_file"
        echo ""
    fi
}

export_config_for_tui() {
    # Export configuration as environment variables for Python TUI
    export AGENT_HOME
    export REPO_NAME
    export CONTAINER_IMAGE

    # Permission modes as comma-separated
    export PERMISSION_MODES="${PERMISSION_MODES[*]}"
    PERMISSION_MODES="${PERMISSION_MODES// /,}"
    export DEFAULT_PERMISSION_MODE

    # MCP manifest path - prefer container-embedded manifest, fallback to local files
    local container_manifest
    container_manifest=$(get_mcp_manifest_from_container)
    if [[ -n "$container_manifest" && -f "$container_manifest" ]]; then
        export MCP_MANIFEST_PATH="$container_manifest"
    elif [[ -f "$SCRIPT_DIR/../containerize/mcp-manifest.json" ]]; then
        export MCP_MANIFEST_PATH="$SCRIPT_DIR/../containerize/mcp-manifest.json"
    elif [[ -f "$SCRIPT_DIR/mcp-manifest.json" ]]; then
        export MCP_MANIFEST_PATH="$SCRIPT_DIR/mcp-manifest.json"
    fi

    # User preferences path for persistence
    export LAUNCHER_PREFS_PATH="$AGENT_HOME/workspace/$REPO_NAME/.claude/launcher_preferences.json"

    export DEFAULT_MCP_SERVERS="${DEFAULT_MCP_SERVERS[*]}"
    DEFAULT_MCP_SERVERS="${DEFAULT_MCP_SERVERS// /,}"

    # Selectable secrets as pipe-separated (shown in TUI)
    local secrets_str=""
    for secret in "${SELECTABLE_SECRETS[@]}"; do
        [[ -n "$secrets_str" ]] && secrets_str+="|"
        secrets_str+="$secret"
    done
    export SELECTABLE_SECRETS="$secrets_str"
}

run_python_tui() {
    export_config_for_tui

    local tui_script="$SCRIPT_DIR/launcher_tui.py"
    if [[ ! -f "$tui_script" ]]; then
        echo "Error: TUI script not found: $tui_script" >&2
        return 1
    fi

    # Use venv python if available
    local py="python3"
    if [[ -x "$AGENT_HOME/.venv/bin/python" ]]; then
        py="$AGENT_HOME/.venv/bin/python"
    fi

    # Run TUI - JSON output is written to a temp file
    local tui_output_file="/tmp/launcher_tui_result.json"
    rm -f "$tui_output_file"
    export TUI_OUTPUT_FILE="$tui_output_file"

    if ! $py "$tui_script"; then
        return 1
    fi

    if [[ ! -f "$tui_output_file" ]]; then
        return 1
    fi

    local tui_output
    tui_output=$(cat "$tui_output_file")
    rm -f "$tui_output_file"

    if [[ -z "$tui_output" ]]; then
        return 1
    fi

    # Parse JSON output using python
    local action permission_mode mcp_servers session_arg
    action=$(echo "$tui_output" | $py -c "import sys, json; d=json.load(sys.stdin); print(d.get('action', ''))")

    if [[ "$action" != "start" ]]; then
        return 1
    fi

    permission_mode=$(echo "$tui_output" | $py -c "import sys, json; d=json.load(sys.stdin); print(d.get('permission_mode', ''))")
    secrets=$(echo "$tui_output" | $py -c "import sys, json; d=json.load(sys.stdin); print(','.join(d.get('secrets', [])))")
    session_arg=$(echo "$tui_output" | $py -c "import sys, json; d=json.load(sys.stdin); print(d.get('session_arg', ''))")
    browser_mode=$(echo "$tui_output" | $py -c "import sys, json; d=json.load(sys.stdin); print(d.get('browser_mode', 'none'))")
    enable_vnc=$(echo "$tui_output" | $py -c "import sys, json; d=json.load(sys.stdin); print(str(d.get('enable_vnc', False)).lower())")

    # Extract MCP server names for display (actual config is written to Claude's settings.json by TUI)
    mcp_names=$(echo "$tui_output" | $py -c "import sys, json; servers=json.load(sys.stdin).get('mcp_servers', []); print(' '.join(s['name'] if isinstance(s,dict) else s for s in servers))")

    # Apply selections
    SELECTED_PERMISSION_MODE="$permission_mode"
    IFS=',' read -ra SELECTED_SECRETS <<< "$secrets"
    SELECTED_SESSION="$session_arg"
    SELECTED_MCP_SERVER_NAMES="$mcp_names"
    SELECTED_BROWSER_MODE="$browser_mode"
    SELECTED_ENABLE_VNC="$enable_vnc"

    return 0
}

build_claude_args() {
    # MCP servers are configured in Claude's settings.json (written by TUI)
    local args="--permission-mode $SELECTED_PERMISSION_MODE"

    if [[ -n "$SELECTED_SESSION" ]]; then
        args="$args $SELECTED_SESSION"
    fi

    # Add --chrome flag if Chrome browser mode is selected
    if [[ "$SELECTED_BROWSER_MODE" == "chrome" ]]; then
        args="$args --chrome"
    fi

    echo "$args"
}

show_final_command() {
    local claude_args
    claude_args=$(build_claude_args)

    local browser_label="None"
    [[ "$SELECTED_BROWSER_MODE" == "playwright" ]] && browser_label="Playwright"
    [[ "$SELECTED_BROWSER_MODE" == "chrome" ]] && browser_label="Chrome"
    [[ "$SELECTED_ENABLE_VNC" == "true" ]] && browser_label="$browser_label+VNC"

    echo "Starting: \`claude $claude_args\`"
    echo "MCP Servers: ${SELECTED_MCP_SERVER_NAMES:-none}  |  Secrets: ${SELECTED_SECRETS[*]:-none}  |  Browser: $browser_label"
}

run_tui() {
    if ! run_python_tui; then
        echo "Cancelled."
        exit 0
    fi
    return 0
}

# ============================================================================
# Main Script
# ============================================================================

export XDG_RUNTIME_DIR=/run/user/$(id -u)

# Create directories if they don't exist
mkdir -p "$AGENT_HOME/workspace/$REPO_NAME/.claude/projects" "$AGENT_HOME/sessions"

# Handle --test flag
if [[ "$1" == "--test" ]]; then
    exec "$TEST_CONTAINER_SH" all
fi

# Run preflight checks (exit on failure)
"$TEST_CONTAINER_SH" preflight || exit 1

# Helper function to check if a secret is selected
is_secret_selected() {
    local secret_name="$1"
    for s in "${SELECTED_SECRETS[@]}"; do
        [[ "$s" == "$secret_name" ]] && return 0
    done
    return 1
}

# Load secrets based on selection (populated after TUI runs, but need defaults for --quick mode)
load_selected_secrets() {
    # Selectable secrets - only loaded if selected in TUI
    GH_TOKEN=""
    HA_ACCESS_TOKEN=""
    MQTT_USER=""
    MQTT_PASS=""

    if is_secret_selected "github_token" && [[ -f "$AGENT_HOME/workspace/.secrets/github_token" ]]; then
        GH_TOKEN=$(cat "$AGENT_HOME/workspace/.secrets/github_token")
    fi

    if is_secret_selected "ha_access_token" && [[ -f "$AGENT_HOME/workspace/.secrets/ha_access_token" ]]; then
        HA_ACCESS_TOKEN=$(cat "$AGENT_HOME/workspace/.secrets/ha_access_token")
    fi

    if is_secret_selected "mqtt_username" && [[ -f "$AGENT_HOME/workspace/.secrets/mqtt_username" ]]; then
        MQTT_USER=$(cat "$AGENT_HOME/workspace/.secrets/mqtt_username")
    fi

    if is_secret_selected "mqtt_password" && [[ -f "$AGENT_HOME/workspace/.secrets/mqtt_password" ]]; then
        MQTT_PASS=$(cat "$AGENT_HOME/workspace/.secrets/mqtt_password")
    fi
}

# Handle direct command execution (e.g., "start-ha-agent bash")
if [[ $# -gt 0 && "$1" != "--"* ]]; then
    # For direct commands, load all available secrets (bypass TUI selection)
    SELECTED_SECRETS=("github_token" "ha_access_token" "mqtt_username" "mqtt_password")
    load_selected_secrets

    # Remove old container if exists
    podman --cgroup-manager=cgroupfs rm -f "$CONTAINER_NAME" 2>/dev/null || true

    # Get seccomp profile path
    SECCOMP_PROFILE=""
    if [[ -f "$SCRIPT_DIR/../containerize/seccomp/chrome.json" ]]; then
        SECCOMP_PROFILE="$SCRIPT_DIR/../containerize/seccomp/chrome.json"
    elif [[ -f "$SCRIPT_DIR/seccomp/chrome.json" ]]; then
        SECCOMP_PROFILE="$SCRIPT_DIR/seccomp/chrome.json"
    fi

    # Build VNC port mapping if enabled
    VNC_PORT_MAPPING=""
    if [[ "$SELECTED_ENABLE_VNC" == "true" ]]; then
        VNC_PORT_MAPPING="-p 5900:5900"
    fi

    # Start container with the provided command
    exec podman --cgroup-manager=cgroupfs run --rm -it \
        --name "$CONTAINER_NAME" \
        --userns=keep-id \
        --shm-size=2g \
        ${SECCOMP_PROFILE:+--security-opt seccomp="$SECCOMP_PROFILE"} \
        ${VNC_PORT_MAPPING} \
        -v "$AGENT_HOME/workspace":/workspace:Z \
        -v "$AGENT_HOME/sessions":/sessions:Z \
        -w "/workspace/$REPO_NAME" \
        --network=ha-agent-net \
        -e HTTP_PROXY=http://host.containers.internal:8888 \
        -e HTTPS_PROXY=http://host.containers.internal:8888 \
        -e NO_PROXY="api.anthropic.com,claude.ai,platform.claude.com,anthropic.com" \
        -e HOME=/workspace \
        -e BROWSER_MODE="$SELECTED_BROWSER_MODE" \
        -e ENABLE_VNC="$SELECTED_ENABLE_VNC" \
        -e GH_TOKEN="$GH_TOKEN" \
        -e HA_ACCESS_TOKEN="$HA_ACCESS_TOKEN" \
        -e MQTT_USER="$MQTT_USER" \
        -e MQTT_PASS="$MQTT_PASS" \
        "$CONTAINER_NAME" \
        "$@"
fi

# Run TUI if not skipped
if [[ "$SKIP_TUI" == false ]]; then
    # Check if Python TUI dependencies are available (prefer venv)
    PYTHON_CMD="python3"
    if [[ -x "$AGENT_HOME/.venv/bin/python" ]]; then
        PYTHON_CMD="$AGENT_HOME/.venv/bin/python"
    fi
    if ! $PYTHON_CMD -c "import textual" &> /dev/null; then
        echo "Warning: textual not installed, using default settings"
        echo "Install with: python3 -m venv ~/.venv && ~/.venv/bin/pip install textual"
        SKIP_TUI=true
    else
        run_tui
    fi
fi

# If TUI was skipped, configure MCP servers based on browser mode
if [[ "$SKIP_TUI" == true ]]; then
    # If Playwright browser mode, enable Playwright MCP
    if [[ "$SELECTED_BROWSER_MODE" == "playwright" ]]; then
        SELECTED_MCP_SERVER_NAMES="playwright"
        # Update Claude's config to enable Playwright MCP
        CLAUDE_JSON="$AGENT_HOME/workspace/.claude.json"
        _py="python3"
        [[ -x "$AGENT_HOME/.venv/bin/python" ]] && _py="$AGENT_HOME/.venv/bin/python"

        $_py -c "
import json
from pathlib import Path

claude_json = Path('$CLAUDE_JSON')
config = {}
if claude_json.exists():
    with open(claude_json) as f:
        config = json.load(f)

if 'projects' not in config:
    config['projects'] = {}
if '/workspace/$REPO_NAME' not in config['projects']:
    config['projects']['/workspace/$REPO_NAME'] = {}
if 'mcpServers' not in config['projects']['/workspace/$REPO_NAME']:
    config['projects']['/workspace/$REPO_NAME']['mcpServers'] = {}

config['projects']['/workspace/$REPO_NAME']['mcpServers']['playwright'] = {
    'type': 'stdio',
    'command': 'npx',
    'args': ['@playwright/mcp'],
    'env': {}
}

claude_json.parent.mkdir(parents=True, exist_ok=True)
with open(claude_json, 'w') as f:
    json.dump(config, f, indent=2)
" 2>/dev/null || true
    fi

    # Read MCP server names from Claude's config for display
    if [[ -z "$SELECTED_MCP_SERVER_NAMES" ]]; then
        CLAUDE_JSON="$AGENT_HOME/workspace/.claude.json"
        if [[ -f "$CLAUDE_JSON" ]]; then
            _py="python3"
            [[ -x "$AGENT_HOME/.venv/bin/python" ]] && _py="$AGENT_HOME/.venv/bin/python"
            SELECTED_MCP_SERVER_NAMES=$($_py -c "
import json
with open('$CLAUDE_JSON') as f:
    config = json.load(f)
project = config.get('projects', {}).get('/workspace/$REPO_NAME', {})
print(' '.join(project.get('mcpServers', {}).keys()))
" 2>/dev/null || echo "")
        fi
    fi
fi

# Load secrets based on TUI selection (or defaults if TUI was skipped)
load_selected_secrets

# Build final Claude arguments
CLAUDE_ARGS=$(build_claude_args)

# Show final command
show_final_command

# Remove old container if exists
podman --cgroup-manager=cgroupfs rm -f "$CONTAINER_NAME" 2>/dev/null || true

# Get seccomp profile path
SECCOMP_PROFILE=""
if [[ -f "$SCRIPT_DIR/../containerize/seccomp/chrome.json" ]]; then
    SECCOMP_PROFILE="$SCRIPT_DIR/../containerize/seccomp/chrome.json"
elif [[ -f "$SCRIPT_DIR/seccomp/chrome.json" ]]; then
    SECCOMP_PROFILE="$SCRIPT_DIR/seccomp/chrome.json"
fi

# Build VNC port mapping if enabled
VNC_PORT_MAPPING=""
if [[ "$SELECTED_ENABLE_VNC" == "true" ]]; then
    VNC_PORT_MAPPING="-p 5900:5900"
fi

# Start container with Claude
exec podman --cgroup-manager=cgroupfs run --rm -it \
    --name "$CONTAINER_NAME" \
    --userns=keep-id \
    --shm-size=2g \
    ${SECCOMP_PROFILE:+--security-opt seccomp="$SECCOMP_PROFILE"} \
    ${VNC_PORT_MAPPING} \
    -v "$AGENT_HOME/workspace":/workspace:Z \
    -v "$AGENT_HOME/sessions":/sessions:Z \
    -w "/workspace/$REPO_NAME" \
    --network=ha-agent-net \
    -e HTTP_PROXY=http://host.containers.internal:8888 \
    -e HTTPS_PROXY=http://host.containers.internal:8888 \
    -e NO_PROXY="api.anthropic.com,claude.ai,platform.claude.com,anthropic.com" \
    -e HOME=/workspace \
    -e BROWSER_MODE="$SELECTED_BROWSER_MODE" \
    -e ENABLE_VNC="$SELECTED_ENABLE_VNC" \
    -e GH_TOKEN="$GH_TOKEN" \
    -e HA_ACCESS_TOKEN="$HA_ACCESS_TOKEN" \
    -e MQTT_USER="$MQTT_USER" \
    -e MQTT_PASS="$MQTT_PASS" \
    "$CONTAINER_NAME" \
    claude $CLAUDE_ARGS