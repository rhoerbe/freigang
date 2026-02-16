#!/bin/bash
# Push container image to ha_agent account
# Run as the user who built the image (e.g., r2h2)
set -e

CONTAINER_NAME="claude-ha-agent"
AGENT_USER="ha_agent"
TMP_FILE="/tmp/${CONTAINER_NAME}.tar"

echo "Saving image $CONTAINER_NAME..."
podman save "$CONTAINER_NAME" -o "$TMP_FILE"

echo "Loading image as $AGENT_USER..."
sudo -u "$AGENT_USER" bash -c "export XDG_RUNTIME_DIR=/run/user/\$(id -u); podman load -i $TMP_FILE"

echo "Cleaning up..."
rm -f "$TMP_FILE"

echo "Done. Image available to $AGENT_USER:"
sudo -u "$AGENT_USER" bash -c "export XDG_RUNTIME_DIR=/run/user/\$(id -u); podman images $CONTAINER_NAME"
