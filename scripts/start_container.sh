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
    echo ""
    echo "╔════════════════════════════════════════════════════════════╗"
    echo "║           Claude Code Container Startup                    ║"
    echo "╠════════════════════════════════════════════════════════════╣"
    printf "║  Host:      %-47s ║\n" "$(hostname)"
    printf "║  Image:     %-47s ║\n" "$CONTAINER_IMAGE:latest"
    printf "║  Repo:      %-47s ║\n" "$REPO_NAME"
    printf "║  Mode:      %-47s ║\n" "$SELECTED_PERMISSION_MODE"
    echo "╚════════════════════════════════════════════════════════════╝"
    echo ""
}

show_main_menu() {
    local choice
    choice=$(whiptail --title "Claude Code Launcher" \
        --menu "Select an action:" 16 60 6 \
        "1" "Start Claude (current settings)" \
        "2" "Configure MCP Servers" \
        "3" "View Secret Status" \
        "4" "Select Permission Mode" \
        "5" "Resume Session" \
        "6" "Exit" \
        3>&1 1>&2 2>&3) || return 1

    echo "$choice"
}

configure_mcp() {
    local checklist_args=()
    local name package description state

    for server in "${AVAILABLE_MCP_SERVERS[@]}"; do
        IFS=':' read -r name package description <<< "$server"
        state="OFF"
        for enabled in "${SELECTED_MCP_SERVERS[@]}"; do
            if [[ "$enabled" == "$name" ]]; then
                state="ON"
                break
            fi
        done
        checklist_args+=("$name" "$description" "$state")
    done

    local selections
    selections=$(whiptail --title "Configure MCP Servers" \
        --checklist "Select MCP servers to enable:" 16 70 6 \
        "${checklist_args[@]}" \
        3>&1 1>&2 2>&3) || return 1

    # Parse selections (whiptail returns quoted strings)
    SELECTED_MCP_SERVERS=()
    for sel in $selections; do
        # Remove quotes
        sel="${sel//\"/}"
        SELECTED_MCP_SERVERS+=("$sel")
    done
}

show_secrets_status() {
    local msg=""
    local name description filepath

    msg+="Required Secrets:\n"
    msg+="─────────────────────────────────────\n"
    for secret in "${REQUIRED_SECRETS[@]}"; do
        IFS=':' read -r name description <<< "$secret"
        filepath="$AGENT_HOME/workspace/.secrets/$name"
        if [[ -f "$filepath" ]]; then
            msg+="[✓] $name\n    $description\n"
        else
            msg+="[✗] $name (MISSING)\n    $description\n"
        fi
    done

    msg+="\nOptional Secrets:\n"
    msg+="─────────────────────────────────────\n"
    for secret in "${OPTIONAL_SECRETS[@]}"; do
        IFS=':' read -r name description <<< "$secret"
        filepath="$AGENT_HOME/workspace/.secrets/$name"
        if [[ -f "$filepath" ]]; then
            msg+="[✓] $name\n    $description\n"
        else
            msg+="[ ] $name (not configured)\n    $description\n"
        fi
    done

    msg+="\nSecret files location:\n$AGENT_HOME/workspace/.secrets/"

    whiptail --title "Secret Status" --msgbox "$msg" 24 60
}

select_permission_mode() {
    local radiolist_args=()
    local state

    for mode in "${PERMISSION_MODES[@]}"; do
        if [[ "$mode" == "$SELECTED_PERMISSION_MODE" ]]; then
            state="ON"
        else
            state="OFF"
        fi
        radiolist_args+=("$mode" "" "$state")
    done

    local selection
    selection=$(whiptail --title "Permission Mode" \
        --radiolist "Select permission mode for Claude:" 14 50 5 \
        "${radiolist_args[@]}" \
        3>&1 1>&2 2>&3) || return 1

    if [[ -n "$selection" ]]; then
        SELECTED_PERMISSION_MODE="$selection"
    fi
}

select_session() {
    local sessions_dir="$AGENT_HOME/workspace/$REPO_NAME/.claude/projects"
    local session_files=()
    local menu_args=()

    # Find session files (*.jsonl)
    if [[ -d "$sessions_dir" ]]; then
        while IFS= read -r -d '' file; do
            session_files+=("$file")
        done < <(find "$sessions_dir" -name "*.jsonl" -type f -print0 2>/dev/null | head -z -n 20)
    fi

    if [[ ${#session_files[@]} -eq 0 ]]; then
        whiptail --title "Resume Session" --msgbox "No previous sessions found.\n\nSessions are stored in:\n$sessions_dir" 12 60
        return 1
    fi

    menu_args+=("new" "Start fresh session" "")
    menu_args+=("continue" "Continue last session (--continue)" "")

    for file in "${session_files[@]}"; do
        local basename
        basename=$(basename "$file" .jsonl)
        local mtime
        mtime=$(stat -c '%Y' "$file" 2>/dev/null || echo "0")
        local date_str
        date_str=$(date -d "@$mtime" '+%Y-%m-%d %H:%M' 2>/dev/null || echo "unknown")
        menu_args+=("$basename" "$date_str" "")
    done

    local selection
    selection=$(whiptail --title "Resume Session" \
        --menu "Select a session:" 20 70 12 \
        "${menu_args[@]}" \
        3>&1 1>&2 2>&3) || return 1

    case "$selection" in
        new)
            SELECTED_SESSION=""
            ;;
        continue)
            SELECTED_SESSION="--continue"
            ;;
        *)
            SELECTED_SESSION="--resume $selection"
            ;;
    esac
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
    while true; do
        clear
        show_context

        local choice
        choice=$(show_main_menu) || {
            # User pressed cancel/escape
            echo "Cancelled."
            exit 0
        }

        case "$choice" in
            1)
                # Start Claude
                return 0
                ;;
            2)
                configure_mcp
                ;;
            3)
                show_secrets_status
                ;;
            4)
                select_permission_mode
                ;;
            5)
                select_session
                ;;
            6)
                echo "Exiting."
                exit 0
                ;;
        esac
    done
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