#!/bin/bash
# Deploy scripts to ha_agent's home directory
# Run as a user with sudo access (e.g., r2h2)
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
AGENT_USER="ha_agent"
AGENT_HOME="/home/$AGENT_USER"

# Deploy provenance stamped into the deployed scripts (issue #30: a stale deploy
# silently ran for months). Surfaced by start_container.sh at launch.
COMMIT="$(git -C "$REPO_ROOT" rev-parse --short HEAD 2>/dev/null || echo unknown)"
git -C "$REPO_ROOT" diff --quiet 2>/dev/null || COMMIT="${COMMIT}-dirty"
DEPLOY_STAMP="$(date '+%Y-%m-%d %H:%M:%S')"

echo "Deploying scripts to $AGENT_HOME (version $COMMIT)..."

# Scripts from scripts/
sudo cp "$SCRIPT_DIR/start_container.sh" "$AGENT_HOME/"
# Replace only the assignment lines (anchored) - a global match would also rewrite
# the sentinel in show_deploy_provenance's comparison and defeat drift detection.
sudo sed -i \
    -e "s|^DEPLOYED_COMMIT=.*|DEPLOYED_COMMIT=\"$COMMIT\"|" \
    -e "s|^DEPLOYED_AT=.*|DEPLOYED_AT=\"$DEPLOY_STAMP\"|" \
    "$AGENT_HOME/start_container.sh"
sudo cp "$SCRIPT_DIR/config.sh" "$AGENT_HOME/"
sudo cp "$SCRIPT_DIR/launcher_tui.py" "$AGENT_HOME/"
sudo cp "$SCRIPT_DIR/sync_mail.sh" "$AGENT_HOME/"

# Scripts from containerize/
sudo cp "$REPO_ROOT/containerize/test_container.sh" "$AGENT_HOME/"
sudo cp "$REPO_ROOT/containerize/mcp-config.json" "$AGENT_HOME/"
sudo cp "$REPO_ROOT/containerize/mcp-manifest.json" "$AGENT_HOME/"

# Set ownership and permissions
sudo chown "$AGENT_USER:$AGENT_USER" \
    "$AGENT_HOME/start_container.sh" \
    "$AGENT_HOME/config.sh" \
    "$AGENT_HOME/launcher_tui.py" \
    "$AGENT_HOME/test_container.sh" \
    "$AGENT_HOME/mcp-config.json" \
    "$AGENT_HOME/mcp-manifest.json"

sudo chmod +x "$AGENT_HOME/start_container.sh" "$AGENT_HOME/test_container.sh" "$AGENT_HOME/launcher_tui.py"

echo "Deployed:"
sudo ls -la "$AGENT_HOME"/*.sh "$AGENT_HOME"/*.py "$AGENT_HOME"/*.json 2>/dev/null | sed 's/^/  /'

echo "Done."
