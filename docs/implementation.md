# Agent Container Implementation

Implementation details for the agent isolation design described in [README.md](prototype_spec.md).

## Prerequisites

Rootless Podman requires:
```bash
export XDG_RUNTIME_DIR=/run/user/$(id -u)
```

If systemd user session is unavailable (e.g., SSH without `loginctl enable-linger`), use cgroupfs:
```bash
podman --cgroup-manager=cgroupfs <command>
```

## Container Setup

### Build the container image
```bash
cd agent_containers
podman --cgroup-manager=cgroupfs build -t claude-ha-agent .
```

### Create podman network
```bash
podman --cgroup-manager=cgroupfs network create ha-agent-net --subnet 10.89.1.0/24
```

### Create podman secrets
```bash
podman secret create anthropic_api_key ~/.secrets/anthropic_api_key
podman secret create github_token ~/.secrets/github_token
podman secret create ha_access_token ~/.secrets/ha_access_token
```

### Home Directory Configuration
The container sets `/workspace` as the home directory for the node user in `/etc/passwd`. This is critical for SSH
client functionality because SSH reads configuration from the home directory specified in `/etc/passwd`, not from the
`$HOME` environment variable.

With this configuration:
- SSH looks for `~/.ssh/config` at `/workspace/.ssh/config`
- Git config, GPG keys, and other user-specific files are stored in the persisted workspace volume
- The workspace volume mount preserves all user configuration across container restarts

### "Always Latest" Startup Hook
The container automatically updates Claude Code to the latest version on every startup. This ensures you're always
running the most recent release without manual intervention.

The update process:
- Executes via `entrypoint.sh` before Claude Code starts
- Uses npm cache at `/workspace/.npm` to minimize download times
- The workspace volume persists the cache across container restarts

To see the update status, watch container startup output for "Checking for Claude Code updates..."

### Run the container
Uses `--userns=keep-id` to map host UID into container, simplifying volume permissions.

```bash
podman --cgroup-manager=cgroupfs run -it --name claude-ha-agent \
  --userns=keep-id \
  -v ./workspace:/workspace:Z \
  -v ./sessions:/sessions:Z \
  --secret anthropic_api_key,target=/run/secrets/anthropic_api_key \
  --secret github_token,target=/run/secrets/github_token \
  --secret ha_access_token,target=/run/secrets/ha_access_token \
  --network=ha-agent-net \
  -e HTTP_PROXY=http://host.containers.internal:8888 \
  -e HTTPS_PROXY=http://host.containers.internal:8888 \
  -e HOME=/workspace \
  claude-ha-agent \
  bash
```

## Home Assistant Access

The agent uses the HA REST API with a Long-Lived Access Token:

```bash
HA_TOKEN=$(cat /run/secrets/ha_access_token)
curl -H "Authorization: Bearer $HA_TOKEN" http://10.4.4.10:8123/api/states
```

## Network Isolation

### Deploy via Ansible
Deploys tinyproxy and nftables rules:
```bash
cd agent_containers/ansible
ansible-playbook playbooks/agent-proxy.yml
```

### Tinyproxy
- Listens on `0.0.0.0:8888` (podman network interface is ephemeral)
- Access restricted via `Allow` directive to container subnets
- Domain allowlist with `FilterDefaultDeny Yes` and `FilterType ere` (extended regex)

Allowed domains (configured in `roles/tinyproxy/defaults/main.yml`):
- `10.4.4.10` (Home Assistant)
- `*.github.com`, `*.githubusercontent.com`
- `api.anthropic.com`
- `*.npmjs.org`

### nftables rules

Note: With rootless podman (slirp4netns/pasta), nftables FORWARD chain is bypassed.
Security is enforced via tinyproxy `FilterDefaultDeny` instead.

```nft
table inet agent-firewall {
    chain forward {
        type filter hook forward priority filter; policy accept;
        ip saddr 10.89.1.0/24 jump agent-egress
    }

    chain agent-egress {
        ct state established,related accept
        ip daddr 10.89.1.1 tcp dport 8888 accept   # proxy
        ip daddr 10.4.4.10 accept                   # HA (HTTP API)
        log prefix "agent-blocked: " drop
    }
}
```

## MCP Configuration

Claude Code MCP config (`~/.claude/claude_code_config.json`):
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

Sessions can be recorded via `script` to a mounted volume:
```bash
script -f /sessions/session-$(date +%Y%m%d-%H%M%S).log -c claude-code
```

Replay with:
```bash
scriptreplay sessions/session-YYYYMMDD-HHMMSS.log
```
