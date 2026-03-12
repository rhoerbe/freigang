#!/bin/bash
# Deploy scripts to ha_agent's home directory
# Run as a user with sudo access (e.g., r2h2)
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
AGENT_USER="ha_agent"
AGENT_HOME="/home/$AGENT_USER"

echo "Deploying scripts to $AGENT_HOME..."

# Scripts from scripts/
sudo cp "$SCRIPT_DIR/start_container.sh" "$AGENT_HOME/"
sudo cp "$SCRIPT_DIR/config.sh" "$AGENT_HOME/"

# Scripts from containerize/
sudo cp "$REPO_ROOT/containerize/test_container.sh" "$AGENT_HOME/"
sudo cp "$REPO_ROOT/containerize/mcp-config.json" "$AGENT_HOME/"

# Set ownership and permissions
sudo chown "$AGENT_USER:$AGENT_USER" \
    "$AGENT_HOME/start_container.sh" \
    "$AGENT_HOME/config.sh" \
    "$AGENT_HOME/test_container.sh" \
    "$AGENT_HOME/mcp-config.json"

sudo chmod +x "$AGENT_HOME/start_container.sh" "$AGENT_HOME/test_container.sh"

echo "Deployed:"
ls -la "$AGENT_HOME"/*.sh "$AGENT_HOME"/*.json 2>/dev/null | sed 's/^/  /'

echo "Done."
