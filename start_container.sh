#!/bin/bash
# Start claude-ha-agent container with least-privilege configuration
# Uses rootless Podman with --userns=keep-id for UID mapping

podman run -it --name claude-ha-agent \
  --userns=keep-id \
  # SSH certificate (short-lived, signed by local CA)
  -v ~/.ssh/agent-ha-key:/home/$USER/.ssh/id_ed25519:ro,Z \
  -v ~/.ssh/agent-ha-key-cert.pub:/home/$USER/.ssh/id_ed25519-cert.pub:ro,Z \
  -v ./ssh_config:/home/$USER/.ssh/config:ro,Z \
  # MCP config
  -v ./mcp-config.json:/home/$USER/.claude/claude_code_config.json:ro,Z \
  # Workspace for git repos
  -v ./ha-workspace:/workspace:Z \
  # Session recording
  -v ./sessions:/sessions:Z \
  # Secrets via podman secrets
  --secret anthropic_api_key,target=/run/secrets/anthropic_api_key \
  --secret github_token,target=/run/secrets/github_token \
  --secret ha_access_token,target=/run/secrets/ha_access_token \
  # Network with egress filtering
  --network=ha-agent-net \
  claude-ha-agent \
  script -f /sessions/session-$(date +%Y%m%d-%H%M%S).log -c claude-code
