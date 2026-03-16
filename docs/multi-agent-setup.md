# Multi-Agent Setup Guide

This guide walks through configuring multiple agents in Freigang using the YAML-based configuration system.

## Overview

Freigang supports running multiple agents, each with:
- Separate Linux user accounts for audit trails
- Independent repositories
- Customizable container images
- Per-agent policies for MCP servers and secrets
- Optional auto-sync on container startup

## Quick Start

### 1. Create Agent Configuration

Create a YAML file in `/etc/freigang/agents.d/` for each agent:

```bash
sudo nano /etc/freigang/agents.d/myagent.yaml
```

Example configuration:

```yaml
agent_id: myagent
agent_description: "My custom agent"

linux_user:
  username: myagent
  home: /home/myagent

repository:
  name: myrepo
  url: git@github.com:username/myrepo.git
  branch: main
  auto_sync: false

container:
  image: claude-myagent
  name_prefix: my-agent
  network: my-agent-net

defaults:
  permission_mode: bypassPermissions
  browser_mode: none
  enable_vnc: false
  mcp_servers: []
  secrets: [github_token]

policy_file: /etc/freigang/policies/myagent_policy.yaml

resources:
  selectable_secrets:
    - name: github_token
      display: "GitHub token"
      required: true
    - name: custom_api_key
      display: "Custom API"
      required: false

  allowed_mcp_servers:
    - playwright

  permission_modes:
    - default
    - acceptEdits
    - bypassPermissions
    - plan
    - dontAsk
```

### 2. Create Policy File

Create a policy file at the path specified in the agent config:

```bash
sudo nano /etc/freigang/policies/myagent_policy.yaml
```

Example policy:

```yaml
version: 1
agent_id: myagent

mcp_servers:
  playwright:
    allowed: true
    network_access: inherit
    filesystem_access:
      - /workspace
      - /tmp

secrets:
  storage_path: /home/myagent/workspace/.secrets
  allowed:
    - github_token
    - custom_api_key

network:
  proxy:
    http_proxy: http://host.containers.internal:8888
    https_proxy: http://host.containers.internal:8888
    no_proxy:
      - api.anthropic.com
      - claude.ai

filesystem:
  writable_paths:
    - /workspace
    - /sessions
    - /tmp
```

### 3. Create Linux User

Create a dedicated Linux user for the agent:

```bash
sudo useradd -m -s /bin/bash myagent
sudo usermod -aG podman myagent
```

### 4. Set Up Repository

As the agent user, clone the repository:

```bash
sudo -u myagent git clone git@github.com:username/myrepo.git /home/myagent/workspace/myrepo
```

### 5. Build Container Image

Build a container image with the name specified in the agent config:

```bash
cd /home/r2h2/devl/freigang/containerize
podman build -t claude-myagent .
```

### 6. Run the Agent

```bash
# Let the script auto-select the agent (if only one exists)
sudo -u myagent /home/myagent/start_container.sh

# Or explicitly specify the agent
sudo -u myagent /home/myagent/start_container.sh --agent myagent
```

## Configuration Reference

### Agent Configuration Fields

#### `agent_id` (string, required)
Unique identifier for the agent.

#### `agent_description` (string, required)
Human-readable description shown in the TUI.

#### `linux_user` (object, required)
- `username`: Linux username for the agent
- `home`: Home directory path

#### `repository` (object, required)
- `name`: Repository directory name
- `url`: Git clone URL
- `branch`: Branch to use
- `auto_sync`: If true, git pull on container startup

#### `container` (object, required)
- `image`: Container image name
- `name_prefix`: Prefix for container names
- `network`: Podman network name

#### `defaults` (object, required)
- `permission_mode`: Default Claude permission mode
- `browser_mode`: Default browser (none/playwright/chrome)
- `enable_vnc`: Default VNC setting
- `mcp_servers`: Default enabled MCP servers (list)
- `secrets`: Default enabled secrets (list)

#### `policy_file` (string, required)
Path to the agent's policy file.

#### `resources` (object, required)
- `selectable_secrets`: List of secrets available in TUI
  - `name`: Secret file name
  - `display`: Display name in TUI
  - `required`: Whether secret is required
- `allowed_mcp_servers`: List of MCP server names allowed
- `permission_modes`: List of permission modes available

### Policy File Fields

#### `version` (number, required)
Policy format version (currently 1).

#### `agent_id` (string, required)
Must match the agent configuration.

#### `mcp_servers` (object)
Per-server configuration:
- `allowed`: Whether server is allowed
- `network_access`: Network access mode
- `filesystem_access`: List of allowed paths

#### `secrets` (object)
- `storage_path`: Where secrets are stored
- `allowed`: List of allowed secret names

#### `network` (object)
- `proxy`: Proxy configuration
  - `http_proxy`: HTTP proxy URL
  - `https_proxy`: HTTPS proxy URL
  - `no_proxy`: List of domains to bypass

#### `filesystem` (object)
- `writable_paths`: List of writable mount points

## Auto-Sync Repository

To enable automatic git pull on container startup:

```yaml
repository:
  auto_sync: true
```

This is useful for:
- Keeping the agent's workspace up to date
- Pulling latest policy changes
- Syncing configuration updates

**Note**: Only fast-forward merges are performed (`git pull --ff-only`). If there are local changes, the sync will fail silently.

## Multiple Agents

When multiple agent configs exist, you'll see an interactive menu:

```
Available agents:
  1) ha_agent - Home Assistant administration agent
  2) wiki_agent - Wiki management agent
  3) dev_agent - Development agent

Select agent [1-3]:
```

Or use the `--agent` flag to skip the menu:

```bash
./start_container.sh --agent ha_agent
```

## Legacy Mode

If no agent configurations exist in `/etc/freigang/agents.d/`, the script runs in legacy mode with hardcoded configuration. This ensures backward compatibility.

## Security Considerations

1. **File Permissions**: Agent configs and policies are owned by root (0644) to prevent modification by agent users.

2. **User Isolation**: Each agent runs as a separate Linux user for clear audit trails.

3. **Policy Enforcement**: MCP servers and secrets are filtered by the policy file.

4. **No Inference**: Agent identity is never inferred from the current Linux user - it must be explicitly selected or configured.

## Troubleshooting

### Agent Not Found

```
Error: Agent config not found: myagent
```

**Solution**: Check that `/etc/freigang/agents.d/myagent.yaml` exists and is readable.

### User Mismatch

```
Error: Agent 'ha_agent' requires user 'ha_agent' but you are 'r2h2'
```

**Solution**: Run the script as the correct user:

```bash
sudo -u ha_agent ./start_container.sh
```

### MCP Servers Not Showing

If expected MCP servers don't appear in the TUI, check:

1. Server is listed in `/etc/freigang/mcp-servers/manifest.json`
2. Server is in the `allowed_mcp_servers` list in agent config
3. Container image includes the server

### Auto-Sync Failing

If `auto_sync: true` doesn't work:

1. Check git remote is configured correctly
2. Ensure SSH keys are set up for the agent user
3. Check container logs for git errors
4. Verify no local uncommitted changes exist

## Next Steps

- See [Agent Configuration Schema](agent-config-schema.md) for detailed field documentation
- See [AGENT_ACCESS.md](../AGENT_ACCESS.md) for access control details
- See [README.md](../README.md) for project overview
