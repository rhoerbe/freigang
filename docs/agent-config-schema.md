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

# Mail capability (optional)
mail:
  enabled: boolean                  # Whether this agent may read mail / propose drafts
  maildir: string                   # Dir name under linux_user.home holding the synced Maildir
  imap_host: string                 # IMAP server hostname (informational; host sync/renderer use)
  drafts_folder: string             # IMAP folder the draft renderer appends generated drafts to

# Available resources for TUI (required)
resources:
  # Secrets that can be selected in TUI
  selectable_secrets:
    - name: string                  # Secret file name (stored in .secrets/)
      display: string               # Display name in TUI
      required: boolean             # Whether this secret is required

  # MCP servers offered in the TUI for this agent
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

### `mail` Object (optional)

Deliberately minimal -- kept to the four fields below so that adding a second mail-capable agent
never requires a schema refactor. No poll intervals, filters, or multi-account support.

Absent entirely means the agent has no mail capability: no mail rows in the TUI, and no `/mail`
mount is ever offered, regardless of any per-session toggle. When present, `mail.enabled: true` is
what makes the (default-off) TUI toggle appear at all; the TUI toggle itself then controls whether
`/mail` is actually mounted for a given session. The container itself never speaks IMAP -- see
Component 1/2 of the design in issue #37 for the host-side sync that populates the Maildir, and
Component 4 for the draft-renderer that reads `/workspace/mail-out/`.

#### `mail.enabled`
- **Type**: boolean
- **Required**: No (whole `mail` block is optional)
- **Description**: Whether this agent may be offered mail access at all. Gates the TUI toggle's
  visibility; it does not itself mount anything.
- **Example**: `true`
- **Default**: `false` (also the effective value when the `mail` block is absent)

#### `mail.maildir`
- **Type**: string
- **Required**: No
- **Description**: Directory name under `linux_user.home` holding the Maildir kept in sync by the
  host-side down-sync (see #37 Component 1). Mounted read-only inside the container at `/mail`, as
  a sibling of `/sessions` -- **not** nested under `/workspace`, since `linux_user.home/workspace`
  is already bind-mounted wholesale at `/workspace`.
- **Example**: `"mail"` (resolves to `$AGENT_HOME/mail`)
- **Default**: `"mail"`

#### `mail.imap_host`
- **Type**: string
- **Required**: No
- **Description**: IMAP server hostname for this agent's mailbox. Informational at this layer --
  consumed by the host-side sync and draft-renderer (#37 Components 1/4), not by the mount itself.
- **Example**: `"www646.your-server.de"`

#### `mail.drafts_folder`
- **Type**: string
- **Required**: No
- **Description**: IMAP folder name the host-side draft renderer `APPEND`s generated drafts to.
  Informational at this layer -- consumed by #37 Component 4.
- **Example**: `"Drafts"`
- **Default**: `"Drafts"`

**Example**:
```yaml
mail:
  enabled: true
  maildir: mail
  imap_host: www646.your-server.de
  drafts_folder: Drafts
```

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

## No Per-Agent Policy Enforcement Layer

There is currently no per-agent policy enforcement layer. A `policy_file` field and an
`/etc/freigang/policies/<agent>_policy.yaml` schema (MCP server allow-lists, a `secrets.allowed`
list, a `filesystem.writable_paths` list, and proxy settings) existed in this doc and in deployed
configs, but nothing in the codebase ever read or enforced them -- see
[ADR-0003](adr/0003-pydantic-schema-and-policy-file-removal.md). They have been removed rather than
kept as documentation shaped like a config file.

The real boundaries an agent operates within today are:

- **The container**: what the image includes and what processes can run inside it.
- **The mounts**: which host paths are bind-mounted into the container, and whether each is
  read-only or read-write (see `start_container.sh`).
- **The secrets actually passed**: only the secret files actually mounted or exported into the
  container's environment are reachable by the agent, regardless of any `defaults.secrets` or
  `resources.selectable_secrets` list in the agent config -- those lists only drive what the TUI
  offers to enable, not what is enforced.
- **The proxy allowlist**: whatever network egress rules the host-side proxy actually applies.

A real enforcement layer (for example, a Cedar-based policy engine) is a separate,
security-focused project and is out of scope here. This doc will be updated when one exists.

## Validation

Agent configurations should be validated before use. Basic validation includes:

1. **File Syntax**: Valid YAML
2. **Required Fields**: All required fields present
3. **Field Types**: Correct data types
4. **User Exists**: `linux_user.username` is a valid system user
5. **Home Directory**: `linux_user.home` exists
6. **Image Exists**: `container.image` is built (warning if not)
7. **Network Exists**: `container.network` is created (warning if not)

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
- `MAIL_ENABLED` - Whether the agent config has `mail.enabled: true` (`false` if `mail` is absent)
- `MAIL_MAILDIR` - `mail.maildir` value (directory name under `AGENT_HOME`; default `mail`)
- `MAIL_IMAP_HOST` - `mail.imap_host` value, informational
- `MAIL_DRAFTS_FOLDER` - `mail.drafts_folder` value (default `Drafts`), informational

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
