#!/bin/bash
# Start claude-ha-agent container with least-privilege configuration

podman run -it --name claude-ha-agent \
  # SSH certificate (short-lived, signed by local CA)
  -v ./agent-ha-key:/home/agent/.ssh/id_ed25519:ro,Z \
  -v ./agent-ha-key-cert.pub:/home/agent/.ssh/id_ed25519-cert.pub:ro,Z \
  -v ./ssh_config:/home/agent/.ssh/config:ro,Z \
  # Workspace for git repos
  -v ./ha-workspace:/home/agent/workspace:Z \
  # Session recording
  -v ./sessions:/home/agent/sessions:Z \
  # Secrets via podman secrets (not env vars)
  --secret anthropic_api_key,target=/run/secrets/anthropic_api_key \
  --secret github_token,target=/run/secrets/github_token \
  --secret ha_access_token,target=/run/secrets/ha_access_token \
  # Network with egress filtering
  --network=ha-agent-net \
  claude-ha-agent \
  script -f /home/agent/sessions/session-$(date +%Y%m%d-%H%M%S).log -c claude-code
