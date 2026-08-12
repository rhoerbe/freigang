#!/bin/bash
# Deploy scripts to ha_agent's home directory
# Run as a user with sudo access (e.g., r2h2)
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
AGENT_USER="ha_agent"
AGENT_HOME="/home/$AGENT_USER"
SECRETS_DIR="$AGENT_HOME/.secrets"
OLD_SECRETS_DIR="$AGENT_HOME/workspace/.secrets"

# Deploy provenance stamped into the deployed scripts (issue #30: a stale deploy
# silently ran for months). Surfaced by start_container.sh at launch.
COMMIT="$(git -C "$REPO_ROOT" rev-parse --short HEAD 2>/dev/null || echo unknown)"
git -C "$REPO_ROOT" diff --quiet 2>/dev/null || COMMIT="${COMMIT}-dirty"
DEPLOY_STAMP="$(date '+%Y-%m-%d %H:%M:%S')"

# Migrate secrets out of the bind-mounted workspace tree (issue #38). ansible's
# agent_user role provisions $SECRETS_DIR with mode 0700 (ansible/roles/agent_user/
# defaults/main.yml) but only creates the directory - it never moves files, so deploy.sh
# owns the actual migration of pre-existing secrets on hosts that predate #38. Idempotent:
# a no-op once $OLD_SECRETS_DIR is gone.
migrate_secrets() {
    # AGENT_HOME/workspace is mode 0700 (owner ha_agent only), so a plain [[ -d ]]
    # test from the deploying user (even a group member) silently sees "absent" on
    # EACCES and would treat a still-pending migration as a no-op. Use sudo test.
    if ! sudo test -d "$OLD_SECRETS_DIR"; then
        return 0
    fi

    echo "Migrating secrets from $OLD_SECRETS_DIR to $SECRETS_DIR ..."

    sudo mkdir -p "$SECRETS_DIR"
    sudo chown "$AGENT_USER:$AGENT_USER" "$SECRETS_DIR"
    sudo chmod 0700 "$SECRETS_DIR"

    # Drop stale _auth_cleanup_* leftover dirs first - they are not secrets, just debris
    # from an earlier cleanup pass, and would otherwise block the final rmdir below.
    local cleanup_dir
    while IFS= read -r -d '' cleanup_dir; do
        echo "Removing stale cleanup dir: $(basename "$cleanup_dir")"
        sudo rm -rf "$cleanup_dir"
    done < <(sudo find "$OLD_SECRETS_DIR" -mindepth 1 -maxdepth 1 -type d -name '_auth_cleanup_*' -print0)

    # Move each remaining secret file. If the same filename already exists at the
    # destination, fail loudly instead of silently overwriting - names only, never
    # contents, appear in the message.
    local f name dest
    while IFS= read -r -d '' f; do
        name="$(basename "$f")"
        dest="$SECRETS_DIR/$name"
        if [[ -e "$dest" ]]; then
            echo "ERROR: secret '$name' exists in both $OLD_SECRETS_DIR and $SECRETS_DIR." \
                "Refusing to overwrite - resolve manually and re-run." >&2
            exit 1
        fi
        sudo mv "$f" "$dest"
        sudo chown "$AGENT_USER:$AGENT_USER" "$dest"
        sudo chmod 0600 "$dest"
    done < <(sudo find "$OLD_SECRETS_DIR" -mindepth 1 -maxdepth 1 -type f -print0 | sort -z)

    # Anything left over (unexpected subdir, etc.) is a loud failure, not a silent skip.
    local remaining
    remaining="$(sudo find "$OLD_SECRETS_DIR" -mindepth 1 2>/dev/null)"
    if [[ -n "$remaining" ]]; then
        echo "ERROR: $OLD_SECRETS_DIR still has entries after migration:" >&2
        echo "$remaining" | sed 's/^/  /' >&2
        exit 1
    fi
    sudo rmdir "$OLD_SECRETS_DIR"

    if sudo test -d "$OLD_SECRETS_DIR"; then
        echo "ERROR: $OLD_SECRETS_DIR still exists after migration" >&2
        exit 1
    fi

    echo "Secrets migrated; $OLD_SECRETS_DIR removed."
}

migrate_secrets

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
sudo cp "$SCRIPT_DIR/post_drafts.sh" "$AGENT_HOME/"
sudo cp "$SCRIPT_DIR/lib_agent_systemd.sh" "$AGENT_HOME/"

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
    "$AGENT_HOME/mcp-manifest.json" \
    "$AGENT_HOME/sync_mail.sh" \
    "$AGENT_HOME/post_drafts.sh" \
    "$AGENT_HOME/lib_agent_systemd.sh"

sudo chmod +x "$AGENT_HOME/start_container.sh" "$AGENT_HOME/test_container.sh" "$AGENT_HOME/launcher_tui.py" "$AGENT_HOME/sync_mail.sh" "$AGENT_HOME/post_drafts.sh"

echo "Deployed:"
sudo ls -la "$AGENT_HOME"/*.sh "$AGENT_HOME"/*.py "$AGENT_HOME"/*.json 2>/dev/null | sed 's/^/  /'

echo "Done."
