#!/bin/bash

# Configuration for Freigang agent

# Check if running in new config mode (AGENT_CONFIG_FILE set by start_container.sh)
if [[ -n "$AGENT_CONFIG_FILE" ]] && [[ -f "$AGENT_CONFIG_FILE" ]]; then
    # New mode: Values already loaded from YAML by start_container.sh
    # These variables are already exported:
    # REPO_NAME, CONTAINER_IMAGE, DEFAULT_PERMISSION_MODE, etc.

    # Build permission modes list from YAML
    PERMISSION_MODES=()
    mode_count=$(yq eval '.resources.permission_modes | length' "$AGENT_CONFIG_FILE")
    for ((i=0; i<mode_count; i++)); do
        mode=$(yq eval ".resources.permission_modes[$i]" "$AGENT_CONFIG_FILE")
        PERMISSION_MODES+=("$mode")
    done

    # Build selectable secrets list from YAML (format: "name:display")
    SELECTABLE_SECRETS=()
    secret_count=$(yq eval '.resources.selectable_secrets | length' "$AGENT_CONFIG_FILE")
    for ((i=0; i<secret_count; i++)); do
        name=$(yq eval ".resources.selectable_secrets[$i].name" "$AGENT_CONFIG_FILE")
        display=$(yq eval ".resources.selectable_secrets[$i].display" "$AGENT_CONFIG_FILE")
        SELECTABLE_SECRETS+=("${name}:${display}")
    done

else
    # Legacy mode: Hardcoded values
    REPO_NAME="hadmin"
    CONTAINER_IMAGE="claude-ha-agent"
    DEFAULT_PERMISSION_MODE="bypassPermissions"

    # Available permission modes for TUI selection
    PERMISSION_MODES=(
        "default"
        "acceptEdits"
        "bypassPermissions"
        "plan"
        "dontAsk"
    )

    # Selectable secrets - shown in TUI for user selection
    SELECTABLE_SECRETS=(
        "github_token:GitHub token"
        "ha_access_token:HA token"
        "mqtt_username:MQTT user"
        "mqtt_password:MQTT pass"
    )
fi

# Default Claude arguments (common to both modes)
CLAUDE_ARGS="--permission-mode $DEFAULT_PERMISSION_MODE"

# MCP servers are defined in containerize/mcp-manifest.json (or /etc/freigang/mcp-manifest.json in container)
# Default enabled MCP servers (must be listed in manifest as "installed")
# NOTE: All MCP servers are OFF by default on first start. Filesystem access is always on via Claude Code itself.
# User preferences are persisted in $AGENT_HOME/workspace/$REPO_NAME/.claude/launcher_preferences.json
DEFAULT_MCP_SERVERS=()
