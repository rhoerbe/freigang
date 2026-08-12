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
  storage_path: /home/myagent/.secrets
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

## Mail Setup (issue #37)

An agent can be given read access to a mailbox and the ability to propose draft replies, without
ever holding IMAP credentials or having network reachability to the mail server itself. This
section describes the full data flow and how an operator turns it on for an agent.

### Data flow, end to end

```
personal mailbox --(user drags mail in)--> ha_agent@hoerbe.at INBOX
                                                  |
                                   host mbsync, one-way DOWN, timer (5 min)
                                                  v
                                        $AGENT_HOME/mail  (Maildir, host filesystem)
                                                  |
                                     bind-mounted read-only at /mail
                                                  v
                                  container: `mail ls` / `mail show` / `mail attach`
                                                  |
                              agent writes plain text + sidecar to /workspace/mail-out/
                                                  v
                          host mail-renderer, closed header allowlist, timer (10 min)
                                                  v
                                  IMAP APPEND to the mailbox's Drafts folder
                                                  |
                                                  v
                                 user opens their mail client, reviews, sends (or not)
```

The user is the airlock at both ends: nothing reaches the agent's mailbox unless the user
deliberately dragged it in, and nothing leaves as a real outgoing message unless the user opens
the resulting draft and sends it themselves.

### Design invariants

These hold regardless of configuration and are enforced structurally, not by policy:

- **One-way-down sync.** `mbsync` is configured `Sync Pull` only - no upward flag sync, no
  two-way channel. The container-writable `/workspace` tree is never a sync source.
- **The agent never speaks IMAP.** No IMAP client is wired into the container image for agent
  use, and the container has no network route to the mail server. All IMAP traffic - both the
  down-sync and the `Drafts` `APPEND` - happens on the host, as the host agent account.
- **The credential lives outside the mounted tree.** The IMAP password sits at
  `$AGENT_HOME/.mailsync/` (mode 0600), a sibling of `workspace`, `mail`, and `.secrets` that no
  `-v` flag in `scripts/start_container.sh` ever references, so it is unreadable from inside a
  running container regardless of TUI selection. (Same reasoning that moved `.secrets/` itself out
  from under `$AGENT_HOME/workspace/` and into `$AGENT_HOME/.secrets/` - see issue #38.)
- **Closed header allowlist on the way out.** The host-side draft renderer builds every message
  with `email.message.EmailMessage`, never hand-formatted strings, and only `From`/`To`
  (hard-coded, not agent input), `Date` (generated), `Subject` and `In-Reply-To` (the agent's only
  two inputs, both validated - `In-Reply-To` must match a Message-ID actually present in the
  synced Maildir) are allowed to exist on the rendered message. Any other header the agent
  proposes is dropped, not merged. A recipient the agent proposes is rendered as a visible line in
  the draft body, never as a header, so sending still requires the human to type an address.
- **The agent cannot send mail.** The only upward path is `APPEND` to `Drafts`; there is no code
  path from the container to an outgoing SMTP send.

### 1. Enable mail in the agent config

Add a `mail:` block to the agent's YAML in `/etc/freigang/agents.d/`:

```yaml
mail:
  enabled: true
  maildir: mail
  imap_host: mail.your-server.de
  drafts_folder: Drafts
```

- `enabled` - gates whether the (default-off) mail toggle appears in the TUI at all. Absent
  `mail:` block, or `enabled: false`, means no toggle, no mount, ever - see
  [Agent Configuration Schema](agent-config-schema.md#mail-object-optional).
- `maildir` - directory name under `linux_user.home` holding the Maildir kept in sync by the
  `agent_mail` role; mounted read-only at `/mail`.
- `imap_host` / `drafts_folder` - consumed by the host-side sync and renderer, not by the mount.

`enabled: true` only makes the toggle available; the per-session TUI checkbox (default off) still
has to be switched on for `/mail` to actually be bind-mounted for that run. Both the config gate
and the toggle must be true, or `scripts/start_container.sh` mounts nothing.

### 2. Run the `agent_mail` Ansible role

`ansible/roles/agent_mail/` installs `isync` (`mbsync`), deploys a one-way-down mbsync config, and
sets up a host `systemd --user` timer (5-minute cadence) plus, additively, the draft-renderer
service and timer (10-minute cadence). It is parameterized - `ha_agent` is only a default in
`defaults/main.yml`, not hard-coded into the role's tasks or templates. Key variables:

```yaml
agent_mail_username: ha_agent
agent_mail_address: ha_agent@hoerbe.at
agent_mail_imap_host: mail.your-server.de
agent_mail_maildir: "{{ agent_mail_home }}/mail"
agent_mail_credential_dir: "{{ agent_mail_home }}/.mailsync"
```

Wire it into `ansible/playbooks/agent-setup.yml` for the target agent, then run the playbook.

### 3. Place the IMAP credential by hand

**Do not add an ansible-vault file to this repo for the mail password.** freigang is a *public*
repo: committed vault ciphertext is published permanently and can be attacked offline at leisure,
and the vault passphrase on these control nodes is shared with a private repo's vault. A public
repo turns a shared passphrase into a shared liability. The mail credential is also
deployment-specific, so it does not belong in a general-purpose project at all.

Place it once, directly on the target host:

```bash
read -rs pw && printf '%s' "$pw" \
  | sudo install -o ha_agent -g ha_agent -m600 /dev/stdin \
    /home/ha_agent/.mailsync/imap_password
```

`read -rs` keeps the password off the terminal and out of shell history; `printf '%s'` writes no
trailing newline, which keeps mbsync's `PassCmd "cat ..."` clean.

The role installs a placeholder with `force: false` and enforces mode 0600, so re-running the
playbook never clobbers a hand-placed password. A host rebuild means re-copying it from your
password manager - cheap here, since rotating an IMAP password destroys nothing (unlike, say, a
Matrix macaroon key, where rotation logs out every device).

If you do want reproducible deploys, `agent_mail_imap_password` is still honoured when passed in
(`-e @/path/to/vault.yml --ask-vault-pass`) - keep that vault in a **private** repo, never here.

### 4. Confirm on the host

```bash
sudo -u ha_agent XDG_RUNTIME_DIR=/run/user/<uid> systemctl --user status mbsync.timer mail-renderer.timer
sudo stat -c '%a %U:%G %n' $AGENT_HOME/.mailsync $AGENT_HOME/.mailsync/imap_password $AGENT_HOME/mail
```

`.mailsync` and its contents should be `700`/`600`, owned by the agent user, and must never appear
in any `-v` flag in `scripts/start_container.sh` - only `$AGENT_HOME/mail` (read-only, as `/mail`)
and `$AGENT_HOME/workspace` are ever mounted.

## Next Steps

- See [Agent Configuration Schema](agent-config-schema.md) for detailed field documentation
- See [AGENT_ACCESS.md](../AGENT_ACCESS.md) for access control details
- See [README.md](../README.md) for project overview
