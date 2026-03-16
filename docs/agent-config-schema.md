# Agent Configuration Schema

This document provides the complete schema for Freigang agent configuration files.

## File Location

Agent configurations are stored in `/etc/freigang/agents.d/` as YAML files.

Example: `/etc/freigang/agents.d/ha_agent.yaml`

## Schema Version

Current schema version: 1

## Complete Schema

```yaml
# Agent identity (required)
agent_id: string                    # Unique identifier for this agent
agent_description: string           # Human-readable description

# Linux user configuration (required)
linux_user:
  username: string                  # Linux username for this agent
  home: string                      # Absolute path to home directory

# Repository configuration (required)
repository:
  name: string                      # Directory name for the repository
  url: string                       # Git clone URL (SSH or HTTPS)
  branch: string                    # Branch to checkout
  auto_sync: boolean                # Whether to git pull on startup

# Container configuration (required)
container:
  image: string                     # Podman image name
  name_prefix: string               # Prefix for container names
  network: string                   # Podman network name

# Default settings (required)
defaults:
  permission_mode: string           # Default Claude permission mode
  browser_mode: string              # Default browser mode (none/playwright/chrome)
  enable_vnc: boolean               # Default VNC setting
  mcp_servers: [string]             # List of default enabled MCP servers
  secrets: [string]                 # List of default enabled secrets

# Policy file reference (required)
policy_file: string                 # Absolute path to policy YAML file

# Available resources for TUI (required)
resources:
  # Secrets that can be selected in TUI
  selectable_secrets:
    - name: string                  # Secret file name (stored in .secrets/)
      display: string               # Display name in TUI
      required: boolean             # Whether this secret is required

  # MCP servers allowed by policy
  allowed_mcp_servers: [string]     # List of MCP server names

  # Permission modes available in TUI
  permission_modes: [string]        # List of valid permission mode strings
```

## Field Definitions

### Top-Level Fields

#### `agent_id`
- **Type**: string
- **Required**: Yes
- **Description**: Unique identifier for the agent. Used in logging and policy references.
- **Example**: `"ha_agent"`
- **Validation**: Must be alphanumeric with underscores/hyphens only.

#### `agent_description`
- **Type**: string
- **Required**: Yes
- **Description**: Human-readable description shown in TUI and logs.
- **Example**: `"Home Assistant administration agent"`

### `linux_user` Object

#### `linux_user.username`
- **Type**: string
- **Required**: Yes
- **Description**: Linux username that will run this agent. Must exist on the system.
- **Example**: `"ha_agent"`
- **Validation**: Must match an existing Linux user account.

#### `linux_user.home`
- **Type**: string
- **Required**: Yes
- **Description**: Absolute path to the user's home directory.
- **Example**: `"/home/ha_agent"`
- **Validation**: Must be an absolute path and exist on the filesystem.

### `repository` Object

#### `repository.name`
- **Type**: string
- **Required**: Yes
- **Description**: Directory name for the repository (used as workspace subdirectory).
- **Example**: `"hadmin"`

#### `repository.url`
- **Type**: string
- **Required**: Yes
- **Description**: Git clone URL. Can be SSH or HTTPS.
- **Example**: `"git@github.com:rhoerbe/hadmin.git"`

#### `repository.branch`
- **Type**: string
- **Required**: Yes
- **Description**: Git branch to checkout.
- **Example**: `"main"`

#### `repository.auto_sync`
- **Type**: boolean
- **Required**: Yes
- **Description**: If true, performs `git pull --ff-only` on container startup.
- **Example**: `false`
- **Default**: `false`
- **Note**: Only fast-forward merges are allowed. Fails silently on conflicts.

### `container` Object

#### `container.image`
- **Type**: string
- **Required**: Yes
- **Description**: Name of the Podman container image to use.
- **Example**: `"claude-ha-agent"`
- **Note**: Image must be built before running the agent.

#### `container.name_prefix`
- **Type**: string
- **Required**: Yes
- **Description**: Prefix for the running container name.
- **Example**: `"ha-agent"`

#### `container.network`
- **Type**: string
- **Required**: Yes
- **Description**: Podman network to attach the container to.
- **Example**: `"ha-agent-net"`
- **Note**: Network must be created before running the agent.

### `defaults` Object

#### `defaults.permission_mode`
- **Type**: string
- **Required**: Yes
- **Description**: Default Claude Code permission mode.
- **Example**: `"bypassPermissions"`
- **Valid Values**:
  - `"default"` - Ask for all operations
  - `"acceptEdits"` - Auto-approve edits
  - `"bypassPermissions"` - No permission prompts
  - `"plan"` - Plan mode
  - `"dontAsk"` - Never ask

#### `defaults.browser_mode`
- **Type**: string
- **Required**: Yes
- **Description**: Default browser automation mode.
- **Example**: `"none"`
- **Valid Values**:
  - `"none"` - No browser
  - `"playwright"` - Playwright MCP
  - `"chrome"` - Chrome with Claude extension

#### `defaults.enable_vnc`
- **Type**: boolean
- **Required**: Yes
- **Description**: Whether to enable VNC by default for browser viewing.
- **Example**: `false`

#### `defaults.mcp_servers`
- **Type**: array of strings
- **Required**: Yes
- **Description**: List of MCP server names to enable by default.
- **Example**: `[]`
- **Note**: Empty array means no servers enabled by default.

#### `defaults.secrets`
- **Type**: array of strings
- **Required**: Yes
- **Description**: List of secret names to enable by default.
- **Example**: `["github_token"]`

### `policy_file` Field

#### `policy_file`
- **Type**: string
- **Required**: Yes
- **Description**: Absolute path to the agent's policy YAML file.
- **Example**: `"/etc/freigang/policies/ha_agent_policy.yaml"`
- **Validation**: File must exist and be readable.

### `resources` Object

#### `resources.selectable_secrets`
- **Type**: array of objects
- **Required**: Yes
- **Description**: List of secrets that can be selected in the TUI.

Each secret object contains:
- **name** (string, required): Secret file name (stored in `.secrets/` directory)
- **display** (string, required): Display name shown in TUI
- **required** (boolean, required): Whether this secret must be provided

**Example**:
```yaml
selectable_secrets:
  - name: github_token
    display: "GitHub token"
    required: true
  - name: ha_access_token
    display: "HA token"
    required: false
```

#### `resources.allowed_mcp_servers`
- **Type**: array of strings
- **Required**: Yes
- **Description**: List of MCP server names allowed for this agent.
- **Example**: `["playwright"]`
- **Note**: Only servers in this list will appear in the TUI, even if installed.

#### `resources.permission_modes`
- **Type**: array of strings
- **Required**: Yes
- **Description**: List of Claude permission modes available in TUI.
- **Example**: `["default", "acceptEdits", "bypassPermissions", "plan", "dontAsk"]`

## Policy File Schema

Policy files are referenced by `policy_file` and stored separately.

### Location
`/etc/freigang/policies/<agent>_policy.yaml`

### Schema

```yaml
version: number                     # Policy schema version (currently 1)
agent_id: string                    # Must match agent config

# MCP server policies
mcp_servers:
  <server_name>:
    allowed: boolean                # Whether server is allowed
    network_access: string          # Network access mode
    filesystem_access: [string]     # Allowed filesystem paths

# Secret policies
secrets:
  storage_path: string              # Where secrets are stored
  allowed: [string]                 # List of allowed secret names

# Network policies
network:
  proxy:
    http_proxy: string              # HTTP proxy URL
    https_proxy: string             # HTTPS proxy URL
    no_proxy: [string]              # Domains to bypass proxy

# Filesystem policies
filesystem:
  writable_paths: [string]          # List of writable paths
```

### Example Policy

```yaml
version: 1
agent_id: ha_agent

mcp_servers:
  playwright:
    allowed: true
    network_access: inherit
    filesystem_access:
      - /workspace
      - /tmp

secrets:
  storage_path: /home/ha_agent/workspace/.secrets
  allowed:
    - github_token
    - ha_access_token
    - mqtt_username
    - mqtt_password

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

## Validation

Agent configurations should be validated before use. Basic validation includes:

1. **File Syntax**: Valid YAML
2. **Required Fields**: All required fields present
3. **Field Types**: Correct data types
4. **User Exists**: `linux_user.username` is a valid system user
5. **Home Directory**: `linux_user.home` exists
6. **Policy File**: `policy_file` exists and is readable
7. **Image Exists**: `container.image` is built (warning if not)
8. **Network Exists**: `container.network` is created (warning if not)

## Environment Variables

When an agent config is loaded, these environment variables are set:

- `AGENT_CONFIG_FILE` - Path to the config file
- `AGENT_ID` - Agent identifier
- `AGENT_DESC` - Agent description
- `AGENT_USER` - Linux username
- `AGENT_HOME` - Home directory
- `REPO_NAME` - Repository name
- `REPO_URL` - Repository URL
- `REPO_BRANCH` - Repository branch
- `REPO_AUTO_SYNC` - Auto-sync setting
- `CONTAINER_IMAGE` - Container image name
- `CONTAINER_NAME_PREFIX` - Container name prefix
- `CONTAINER_NETWORK` - Podman network
- `DEFAULT_PERMISSION_MODE` - Default permission mode
- `DEFAULT_BROWSER_MODE` - Default browser mode
- `DEFAULT_VNC` - Default VNC setting
- `POLICY_FILE` - Policy file path

## Future Extensions

Planned additions to the schema:

- **Resource Limits**: CPU/memory constraints per agent
- **Logging**: Per-agent log configuration
- **Networking**: Fine-grained network policies
- **Cedar Policies**: Migration to Cedar policy language
- **Multi-Instance**: Running multiple containers per agent

## See Also

- [Multi-Agent Setup Guide](multi-agent-setup.md)
- [AGENT_ACCESS.md](../AGENT_ACCESS.md)
- [README.md](../README.md)
