# Agent Container Implementation

Implementation details for the agent isolation design described in [agent_containers/README.md](../agent_containers/README.md).

## Container Setup

### Build the container image
```bash
cd agent_containers
podman build -t claude-ha-agent .
```

### Create podman network
```bash
podman network create ha-agent-net --subnet 10.89.1.0/24
```

### Create podman secrets
```bash
podman secret create anthropic_api_key ~/.secrets/anthropic_api_key
podman secret create github_token ~/.secrets/github_token
podman secret create ha_access_token ~/.secrets/ha_access_token
```

### Run the container
```bash
podman run -it --name claude-ha-agent \
  -v ./agent-ha-key:/home/agent/.ssh/id_ed25519:ro,Z \
  -v ./agent-ha-key-cert.pub:/home/agent/.ssh/id_ed25519-cert.pub:ro,Z \
  -v ./ssh_config:/home/agent/.ssh/config:ro,Z \
  -v ./ha-workspace:/home/agent/workspace:Z \
  -v ./sessions:/home/agent/sessions:Z \
  --secret anthropic_api_key,target=/run/secrets/anthropic_api_key \
  --secret github_token,target=/run/secrets/github_token \
  --secret ha_access_token,target=/run/secrets/ha_access_token \
  --network=ha-agent-net \
  claude-ha-agent \
  script -f /home/agent/sessions/session-$(date +%Y%m%d-%H%M%S).log -c claude-code
```

## SSH Configuration

### SSH certificate signing (on management host)
```bash
# Generate CA key (once)
ssh-keygen -t ed25519 -f ca_key -C "agent-ca"

# Sign agent's public key (daily via cron)
ssh-keygen -s ca_key -I "ha-agent" -n homeassistant -V +1d agent_key.pub
```

### authorized_keys on HA host
```
command="/usr/local/bin/ha-agent-shell",no-port-forwarding,no-X11-forwarding ssh-ed25519 AAAA...
```

### SSH config (container)
```
Host ha
    HostName 10.4.4.10
    User homeassistant
    StrictHostKeyChecking accept-new
```

## Network Isolation

### Tinyproxy on host (tinyproxy.conf)
```
Allow 10.89.1.0/24
FilterURLs On
Filter "/etc/tinyproxy/allowlist"
```

### Domain allowlist (/etc/tinyproxy/allowlist)
```
^10\.4\.4\.10
^(.*\.)?github\.com
^(.*\.)?githubusercontent\.com
^api\.anthropic\.com
^(.*\.)?npmjs\.org
```

### nftables rules on host
```nft
table inet agent-firewall {
    chain forward {
        type filter hook forward priority 0; policy drop;

        # Identify traffic from the agent container network
        ip saddr 10.89.1.0/24 jump agent-egress
    }

    chain agent-egress {
        # Allow established/related
        ct state established,related accept

        # Allow proxy port on host
        ip daddr 10.89.1.1 tcp dport 8888 accept

        # Allow SSH to HA node
        ip daddr 10.4.4.10 tcp dport 22 accept

        # Drop everything else (implicit via policy)
    }
}
```

### Container proxy environment
Set in container or Dockerfile:
```bash
export HTTP_PROXY=http://host.containers.internal:8888
export HTTPS_PROXY=http://host.containers.internal:8888
```

## MCP Configuration

### Claude Code MCP config (~/.claude/claude_code_config.json)
```json
{
  "mcpServers": {
    "playwright": {
      "command": "npx",
      "args": ["@anthropic-ai/mcp-server-playwright"]
    }
  }
}
```

## Session Recording

Sessions are recorded via `script` to the mounted `sessions/` volume.
Replay with:
```bash
scriptreplay sessions/session-YYYYMMDD-HHMMSS.log
```
