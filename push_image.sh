#!/bin/bash
# Push container image to ha_agent account
# Run as the user who built the image (e.g., r2h2)
set -e

IMAGE_NAME="localhost/claude-ha-agent:latest"
AGENT_USER="ha_agent"

echo "Copying image to $AGENT_USER..."
# podman image scp "$IMAGE_NAME" "${AGENT_USER}@localhost::" # not working: fork/exec /usr/bin/podman: operation not permitted
podman save "$IMAGE_NAME" | sudo -u "$AGENT_USER" sh -c 'cd /tmp && podman load'

echo "Done."
