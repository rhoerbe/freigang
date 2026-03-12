#!/bin/bash
# Start claude-ha-agent container with least-privilege configuration
# Uses rootless Podman with --userns=keep-id for UID mapping
#
# Usage:
#   start-ha-agent              # start Claude Code with TUI
#   start-ha-agent --quick      # start Claude Code without TUI (use defaults)
#   start-ha-agent --test       # run preflight and network connectivity tests
#   start-ha-agent bash         # start bash shell
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
SELECTED_MCP_SERVERS=("${DEFAULT_MCP_SERVERS[@]}")
SELECTED_SESSION=""
SKIP_TUI=false

# Parse initial arguments
for arg in "$@"; do
    case "$arg" in
        --quick)
            SKIP_TUI=true
            shift
            ;;
    esac
done

# ============================================================================
# TUI Functions
# ============================================================================

show_context() {
    local claude_args
    claude_args=$(build_claude_args)
    local mcp_list="${SELECTED_MCP_SERVERS[*]:-none}"

    echo ""
    echo "╔══════════════════════════════════════════════════════════════════════╗"
    echo "║             Freigang containerized agent startup                     ║"
    echo "╠══════════════════════════════════════════════════════════════════════╣"
    printf "║  Host:      %-57s ║\n" "$(hostname)"
    printf "║  Image:     %-57s ║\n" "$CONTAINER_IMAGE:latest"
    printf "║  Repo:      %-57s ║\n" "$REPO_NAME"
    printf "║  Command:   %-57s ║\n" "claude $claude_args"
    printf "║  MCP:       %-57s ║\n" "$mcp_list"
    echo "╚══════════════════════════════════════════════════════════════════════╝"
    echo ""
}

get_session_files() {
    local sessions_dir="$AGENT_HOME/workspace/$REPO_NAME/.claude/projects"
    SESSION_FILES=()
    if [[ -d "$sessions_dir" ]]; then
        while IFS= read -r -d '' file; do
            SESSION_FILES+=("$file")
        done < <(find "$sessions_dir" -name "*.jsonl" -type f -print0 2>/dev/null | head -z -n 5)
    fi
}

show_unified_form() {
    local checklist_args=()
    local state name package description

    # ── Permission Modes (radio-style: only one should be selected) ──
    for mode in "${PERMISSION_MODES[@]}"; do
        if [[ "$mode" == "$SELECTED_PERMISSION_MODE" ]]; then
            state="ON"
        else
            state="OFF"
        fi
        checklist_args+=("perm:$mode" "[Mode] $mode" "$state")
    done

    # ── MCP Servers (multi-select) ──
    for server in "${AVAILABLE_MCP_SERVERS[@]}"; do
        IFS=':' read -r name package description <<< "$server"
        state="OFF"
        for enabled in "${SELECTED_MCP_SERVERS[@]}"; do
            if [[ "$enabled" == "$name" ]]; then
                state="ON"
                break
            fi
        done
        checklist_args+=("mcp:$name" "[MCP] $description" "$state")
    done

    # ── Session Options (radio-style) ──
    get_session_files

    if [[ "$SELECTED_SESSION" == "" ]]; then
        state="ON"
    else
        state="OFF"
    fi
    checklist_args+=("sess:new" "[Session] Start fresh" "$state")

    if [[ ${#SESSION_FILES[@]} -gt 0 ]]; then
        if [[ "$SELECTED_SESSION" == "--continue" ]]; then
            state="ON"
        else
            state="OFF"
        fi
        checklist_args+=("sess:continue" "[Session] Continue last" "$state")

        for file in "${SESSION_FILES[@]}"; do
            local basename mtime date_str
            basename=$(basename "$file" .jsonl)
            mtime=$(stat -c '%Y' "$file" 2>/dev/null || echo "0")
            date_str=$(date -d "@$mtime" '+%Y-%m-%d %H:%M' 2>/dev/null || echo "unknown")
            if [[ "$SELECTED_SESSION" == "--resume $basename" ]]; then
                state="ON"
            else
                state="OFF"
            fi
            checklist_args+=("sess:$basename" "[Session] Resume: $date_str" "$state")
        done
    fi

    # ── Secrets Status (info only, always OFF) ──
    for secret in "${REQUIRED_SECRETS[@]}"; do
        IFS=':' read -r name description <<< "$secret"
        local filepath="$AGENT_HOME/workspace/.secrets/$name"
        if [[ -f "$filepath" ]]; then
            checklist_args+=("info:$name" "[Secret ✓] $name" "OFF")
        else
            checklist_args+=("info:$name" "[Secret ✗] $name MISSING" "OFF")
        fi
    done

    local num_items=${#checklist_args[@]}
    num_items=$((num_items / 3))
    local height=$((num_items + 8))
    [[ $height -gt 24 ]] && height=24

    local selections
    selections=$(whiptail --title "Freigang Agent Launcher" \
        --checklist "Configure and press OK to start (Cancel to exit):" \
        $height 70 $num_items \
        "${checklist_args[@]}" \
        3>&1 1>&2 2>&3) || return 1

    # Parse selections
    SELECTED_MCP_SERVERS=()
    local new_permission_mode=""
    local new_session=""

    for sel in $selections; do
        sel="${sel//\"/}"
        case "$sel" in
            perm:*)
                new_permission_mode="${sel#perm:}"
                ;;
            mcp:*)
                SELECTED_MCP_SERVERS+=("${sel#mcp:}")
                ;;
            sess:new)
                new_session=""
                ;;
            sess:continue)
                new_session="--continue"
                ;;
            sess:*)
                new_session="--resume ${sel#sess:}"
                ;;
            # info: items are ignored
        esac
    done

    # Apply permission mode (use last selected, or keep current if none)
    if [[ -n "$new_permission_mode" ]]; then
        SELECTED_PERMISSION_MODE="$new_permission_mode"
    fi

    # Apply session selection
    SELECTED_SESSION="$new_session"

    return 0
}

build_mcp_config() {
    local config_file="$AGENT_HOME/workspace/$REPO_NAME/.claude/settings.json"
    local temp_file="${config_file}.tmp"

    # Start building JSON
    echo '{' > "$temp_file"
    echo '  "mcpServers": {' >> "$temp_file"

    local first=true
    for server_name in "${SELECTED_MCP_SERVERS[@]}"; do
        # Find the package for this server
        for server in "${AVAILABLE_MCP_SERVERS[@]}"; do
            local name package description
            IFS=':' read -r name package description <<< "$server"
            if [[ "$name" == "$server_name" ]]; then
                if [[ "$first" == true ]]; then
                    first=false
                else
                    echo ',' >> "$temp_file"
                fi
                cat >> "$temp_file" << EOF
    "$name": {
      "command": "npx",
      "args": ["$package"]
    }
EOF
                break
            fi
        done
    done

    echo '' >> "$temp_file"
    echo '  }' >> "$temp_file"
    echo '}' >> "$temp_file"

    mv "$temp_file" "$config_file"
}

build_claude_args() {
    local args="--permission-mode $SELECTED_PERMISSION_MODE"

    if [[ -n "$SELECTED_SESSION" ]]; then
        args="$args $SELECTED_SESSION"
    fi

    echo "$args"
}

show_final_command() {
    local claude_args
    claude_args=$(build_claude_args)

    echo ""
    echo "Starting container with command:"
    echo "  claude $claude_args"
    echo ""
    echo "MCP Servers enabled: ${SELECTED_MCP_SERVERS[*]:-none}"
    echo ""
}

run_tui() {
    clear
    show_context

    if ! show_unified_form; then
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

# Load tokens for CLI tools
GH_TOKEN=$(cat "$AGENT_HOME/workspace/.secrets/github_token")
# ANTHROPIC_API_KEY=$(cat "$AGENT_HOME/workspace/.secrets/anthropic_api_key")  # using OAuth token instead
HA_ACCESS_TOKEN=$(cat "$AGENT_HOME/workspace/.secrets/ha_access_token")

# MQTT credentials (optional - create files if MQTT debugging is needed)
MQTT_USER=""
MQTT_PASS=""
if [[ -f "$AGENT_HOME/workspace/.secrets/mqtt_username" ]]; then
    MQTT_USER=$(cat "$AGENT_HOME/workspace/.secrets/mqtt_username")
fi
if [[ -f "$AGENT_HOME/workspace/.secrets/mqtt_password" ]]; then
    MQTT_PASS=$(cat "$AGENT_HOME/workspace/.secrets/mqtt_password")
fi

# Handle direct command execution (e.g., "start-ha-agent bash")
if [[ $# -gt 0 && "$1" != "--"* ]]; then
    # Remove old container if exists
    podman --cgroup-manager=cgroupfs rm -f "$CONTAINER_NAME" 2>/dev/null || true

    # Start container with the provided command
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
        -e MQTT_USER="$MQTT_USER" \
        -e MQTT_PASS="$MQTT_PASS" \
        "$CONTAINER_NAME" \
        "$@"
fi

# Run TUI if not skipped
if [[ "$SKIP_TUI" == false ]]; then
    # Check if whiptail is available
    if ! command -v whiptail &> /dev/null; then
        echo "Warning: whiptail not found, using default settings"
        SKIP_TUI=true
    else
        run_tui
    fi
fi

# Build MCP config from selections
build_mcp_config

# Build final Claude arguments
CLAUDE_ARGS=$(build_claude_args)

# Show final command
show_final_command

# Remove old container if exists
podman --cgroup-manager=cgroupfs rm -f "$CONTAINER_NAME" 2>/dev/null || true

# Start container with Claude
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
    -e MQTT_USER="$MQTT_USER" \
    -e MQTT_PASS="$MQTT_PASS" \
    "$CONTAINER_NAME" \
    claude $CLAUDE_ARGS