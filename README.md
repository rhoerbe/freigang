# Design Document: Least-Privilege AI Agent Execution Environment

## 1. Vision & Problem Statement

AI agents (like Claude Code) possess the dual nature of an assistant and an operator. 
They face specific risks that traditional IAM doesn't fully cover:

* Overprovisioning (Just-in-Case vs. Just-in-Time): Agents often possess persistent keys, 
  too many tools and access permissions that should only be active during a specific task execution.
* The Von Neumann Gap: LLMs do not strictly separate "data" from "instructions," making them inherently vulnerable 
  to Prompt Injection.
* Agents need dedicated non-human identities, but users will bypass security if the process is too complex.

## 2. Architecture Overview

- The architecture follows a "Launcher" pattern. Instead of agents being started manually, a policy-aware launcher 
mediates all lifecycle events.
- The launcher can run many agents in parallel with task-specific policies.
- The system uses rootless Podman for process isolation and Cedar for fine-grained policy validation.
Other isolation mechanisms (virtual machines, bare metal) could be used but are not implemented.

### 2.1 Domain Taxonomy

* Agent: A loose umbrella term for concepts below. In this context only used for an Agent Instance:
  * `Agent Tool`: A service or tool that executes in a loop calling LLMs and tools, such as Claude Code CLI or OpenCode. 
  * `Agent Instance` or just `Agent`:  Instance of an Agent Tool that has been isolated from the user environment and provisioned with certain capabilities.
* Allowed Models: The LLMs that an Agent Instance is allowed to use.
* Deployed MCP Servers: MCP servers that are available to an Agent Instance and can be added at startup time.
* Active MCP Servers: MCP servers that have been added at startup time.
* Agent Instance Capabilities: The file system and network access that an Agent can use with the internal tool, e.g. WebSearch.
* MCP Server Capabilities: The file system and network access that an MCP Server is entitled to.
* Privilege Mode: 

### 2.1 Identity & Isolation Model

* Rootless Execution: Container UID 0 maps to an agent-specific host user.
* User Namespacing: Uses `--userns=keep-id` to simplify volume permissions while maintaining host-level unprivileged status.
* Persistence Strategy: Workspace volumes are used for Git state and persistent user configuration (`~/.ssh/config` maps to `/workspace/.ssh/config`).

### 2.2 Core Components

* Identity: Agents run as a non-privileged Linux user (`ha_agent`) using Rootless Podman.
* Policy Engine (Cedar): A declarative language used to define what an agent is permitted to do (Network egress, Tool access, Secret retrieval).
* Orchestration (Quadlets): Systemd-integrated Podman configuration files that define the "Unit of Work."
* MCP Sidecars: High-risk tools (Browsers, DB clients) are isolated in separate containers within the same Podman Pod, communicating via Unix Domain Sockets (UDS).

### 2.3 Multi-Agent Architecture

Freigang supports multiple agents with independent configurations:

* **Agent Configuration**: YAML-based configuration files in `/etc/freigang/agents.d/` define per-agent settings
* **Policy Files**: Separate policy files in `/etc/freigang/policies/` specify MCP server access, secrets, and network rules
* **Agent Selection**: Interactive menu or `--agent` flag for explicit selection
* **User Isolation**: Each agent runs as a dedicated Linux user for clear audit trails
* **Repository Management**: Per-agent repositories with optional auto-sync on container startup
* **Container Customization**: Configurable container images per agent for different tool requirements

**Configuration Structure**:
```
/etc/freigang/
├── agents.d/                   # Agent definitions
│   ├── ha_agent.yaml
│   └── wiki_agent.yaml
├── policies/                   # Per-agent policies
│   ├── ha_agent_policy.yaml
│   └── wiki_agent_policy.yaml
└── mcp-servers/
    └── manifest.json           # Available MCP servers
```

**Key Features**:
- Backward compatible with legacy hardcoded configuration
- No inference from current user - explicit selection required
- Policy-based MCP server filtering (only allowed servers shown in TUI)
- Separate secrets and permissions per agent
- Optional git auto-sync for keeping workspaces current

For detailed setup instructions, see [Multi-Agent Setup Guide](docs/multi-agent-setup.md) and [Agent Configuration Schema](docs/agent-config-schema.md).

---

## 3. The Incremental Evolution Path

### Phase 1: Developer Pilot (Local Governance)

* Goal: Move from raw `podman run` to policy-validated Quadlets.
* Workflow: Developer maintains a local `.cedar` file. The launcher validates the request and writes Quadlets to `~/.config/containers/systemd/`.
* Networking: Host-based or basic bridge networking.

### Phase 2: Agent-as-a-Service (Managed Catalog)

* Goal: Centralize policy and provide a "Form-based" experience.
* Workflow: Admins provide Cedar Policy Templates. Users instantiate these via a UI (e.g., selecting "Web Researcher" or "Code Assistant" profiles).
* Networking: Agents move to managed systems with restricted Netavark/Firewalld zones.

### Phase 3: Enterprise Integration (Full IGA/ITSM)

* Goal: Zero-trust lifecycle management.
* Workflow: Agent identity is managed in an IGA system (e.g., Okta/SailPoint). Launching requires an approved ITSM ticket ID (ServiceNow) passed in the Cedar context.
* Secrets: OpenBao integration for dynamic, short-lived API keys.

---

## 4. Security & Isolation Model

### 4.1 Sidecar Isolation (The "One MCP, One Sandbox" Rule)

To prevent an agent from abusing a powerful tool (like a browser), each MCP server is deployed as a sidecar.

* Communication: No TCP/IP between Agent and MCP. They share a Unix Domain Socket mounted in a shared volume.
* Constraints: An MCP container can have `Network=none` while the Agent container has `Network=managed`, preventing the tool from being used for exfiltration.

### 4.2 Network Policy

The Launcher translates Cedar `context.allowed_egress` into:

1. Netavark DNS Filtering: Restricting resolution to approved domains.
2. Firewalld/IPTable Rules: Bound to the specific Podman network interface created for that agent.

### 4.3 Github Policy

* Agents are provisioned with fine-grained access tokens which define the scope of access.
* Tokens should be rather short-lived, but exceed the life time of a container session.
* Permissions:
  * Read access to actions and metadata.
  * Read and write access to checks, code, discussions, issues, pull requests, and workflows.
* Repository access:  Single-repo by default, all repos if required.

---

## 5. Decision Log

* Why Cedar? Better readability than Rego (OPA) and native support for "Policy Templates" which enables form-based editing for non-security users.
* Why Quadlets? Provides "Systemd-native" management. If the host reboots, the agent resumes. It avoids the overhead of K8s while providing structured declarations.
* Why Unix Sockets? Removes the need for port management within the Pod and leverages Linux filesystem permissions for an extra layer of AuthZ.

---

# Addendum: Implementation Details

### A.1 Sample Cedar Policy (Phase 2 Template)

This template defines a "Web Research" profile.

```cedar
// Template for a Web Research Agent
permit (
    principal == ?principal,
    action == Action::"Launch",
    resource == AgentProfile::"WebResearcher"
)
when {
    context.mcp_servers.contains("playwright") &&
    context.network_zone == "restricted-egress" &&
    context.volumes.all(v | v.readOnly == true)
};

```

### A.2 Sample Quadlet Structure (Generated)

The launcher would output these files to `/etc/containers/systemd/` (or user equivalent).

agent-alpha.pod

```ini
[Pod]
Network=agent-net-123.network
Volume=mcp-sockets.volume

```

agent-alpha-cli.container

```ini
[Container]
Pod=agent-alpha.pod
Image=docker.io/library/claude-code:latest
Exec=claude-code --mcp-unix /sockets/playwright.sock
Volume=mcp-sockets.volume:/sockets:rw

```

agent-alpha-playwright.container

```ini
[Container]
Pod=agent-alpha.pod
Image=ghcr.io/mcp/playwright:latest
# Completely isolated from the internet, only talks to the agent via socket
Network=none 
Volume=mcp-sockets.volume:/sockets:rw

```

---

Next Step:
Would you like me to focus on the Network Configuration specifically, exploring how to define the `Netavark` policies that would support these Phase 2/3 requirements?