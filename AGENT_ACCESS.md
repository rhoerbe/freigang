# Agent Access Policy

Status: The project is currently supporting only a single project, single repo and single set of agent access.
This document shall be converted to a human-readable Cedar policy (without loosing information). 
Policies shall be linked to an agent in the context of a project, allowing different agens having different access policies. 

You are running in an isolated container with restricted tool and network access.

## Allowed Access

### Network
- **api.anthropic.com** - Claude API (direct, no proxy)
- **github.com** - Git operations, GitHub API (via proxy)
- **10.4.4.10:8123** - Home Assistant API and Web UI
- **10.4.4.10:1883** - MQTT (Home Assistant add-on)
- **10.4.4.17:1883** - MQTT bridge (Mulberry)

### MCP Servers
- **Playwright** - Browser automation for HA web UI

### CLI Tools
- **mosquitto_sub** / **mosquitto_pub** - MQTT client tools for debugging brokers

### Credentials (environment variables)
- `CLAUDE_CODE_OAUTH_TOKEN` - Long-lived Anthropic OAuth token from `claude setup-token` (secret `.secrets/claude_setup_token`), injected at launch so no interactive `/login` is needed. Inference-only: it cannot establish Remote Control. For occasional Remote Control, run `claude-rc` inside the container (Tier-2) - it unsets this token and does a full-scope `claude auth login` first. See [docs/agent-auth-design.md](docs/agent-auth-design.md).
- `GH_TOKEN` - GitHub personal access token for repo rhoerbe/hadmin
- `HA_ACCESS_TOKEN` - Home Assistant long-lived access token
- `MQTT_USER` - MQTT broker username
- `MQTT_PASS` - MQTT broker password

### Filesystem
- `/workspace` - Persistent workspace (mounted from host)
- `/workspace/hadmin` - Target repository
- `/sessions` - Session logs

## Blocked
- All other outbound network access
- Host filesystem outside mounted volumes
- Privileged operations

## Purpose
Administer Home Assistant at 10.4.4.10 via API, Playwright MCP, and MQTT debugging.

## Policy Configuration

Agent access policies are now defined in YAML files:

- **Agent Configuration**: `/etc/freigang/agents.d/ha_agent.yaml` - Defines agent identity, repository, and available resources
- **Policy File**: `/etc/freigang/policies/ha_agent_policy.yaml` - Specifies allowed MCP servers, secrets, network access, and filesystem permissions

For details on the policy format and multi-agent setup, see:
- [Multi-Agent Setup Guide](docs/multi-agent-setup.md)
- [Agent Configuration Schema](docs/agent-config-schema.md)
