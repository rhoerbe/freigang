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
- `/mail` - Read-only synced mailbox (see Mail below; present only when enabled for this session)
- `/workspace/mail-out` - Draft output directory (see Mail below); part of the `/workspace` mount, not a separate one

## Blocked
- All other outbound network access
- Host filesystem outside mounted volumes
- Privileged operations
- IMAP/SMTP to the mail server: the container never has a network path to it and never holds a
  mail credential (see Mail below)

## Mail (issue #37)

Agents whose config carries a `mail:` block with `enabled: true` may be offered read access to a
mailbox, gated per session by a TUI toggle that defaults **off**. The design goal is that "the
agent cannot send mail on my behalf" is true because the container is structurally unable to, not
because a policy says not to.

- **The agent has no IMAP access and no mail credential.** There is no IMAP client library wired
  in for the agent to use even if it wanted to, no network path from the container to the mail
  server, and the IMAP password is never written into any directory that is mounted into the
  container. All IMAP traffic (both reading the mailbox and posting drafts) happens on the host,
  outside the container, as the host `ha_agent` account.
- **The agent cannot send mail.** The only upward path is a host-side renderer that appends
  agent-proposed text to the mailbox's `Drafts` folder for the human to review and send manually
  from their own mail client; nothing the agent writes is ever transmitted as an outgoing message.
- `/mail` - a host-side `mbsync` job pulls the mailbox down into a Maildir on the host, on a
  timer; that Maildir is bind-mounted **read-only** into the container at `/mail`, as a sibling of
  `/sessions` (not nested under `/workspace`). The mount exists only for sessions where both the
  agent's config has `mail.enabled: true` **and** the per-session TUI toggle was switched on; if
  either is false the mount is absent entirely - not present-but-empty. A container-side `mail`
  CLI (`mail ls` / `mail show <id>` / `mail attach <id> <n>`) reads this Maildir; every message
  body it prints is wrapped in an explicit untrusted-content delimiter, and attachments are only
  ever extracted on-demand into `/workspace/mail-attachments/`, never automatically.
- `/workspace/mail-out` - the agent writes a plain-text draft body plus a small sidecar (subject,
  optional `In-Reply-To`, any *proposed* recipient as data, never as a header) here. A separate
  host-side process drains this directory, renders an RFC822 message through a closed header
  allowlist (`From`/`To` hard-coded, `Date` generated, only `Subject`/`In-Reply-To` come from the
  agent), and `APPEND`s it to `Drafts` over IMAP. Any recipient the agent proposed appears only as
  a visible line in the body, never in a header, so sending still requires the human to type an
  address.

See [Multi-Agent Setup Guide](docs/multi-agent-setup.md#mail-setup-issue-37) for how an operator
enables this per agent, and GitHub issue #37 for the full design and rationale.

## Purpose
Administer Home Assistant at 10.4.4.10 via API, Playwright MCP, and MQTT debugging.

## Policy Configuration

Agent access policies are now defined in YAML files:

- **Agent Configuration**: `/etc/freigang/agents.d/ha_agent.yaml` - Defines agent identity, repository, and available resources
- **Policy File**: `/etc/freigang/policies/ha_agent_policy.yaml` - Specifies allowed MCP servers, secrets, network access, and filesystem permissions

For details on the policy format and multi-agent setup, see:
- [Multi-Agent Setup Guide](docs/multi-agent-setup.md)
- [Agent Configuration Schema](docs/agent-config-schema.md)
