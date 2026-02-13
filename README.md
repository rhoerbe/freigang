# Agent Isolation using Containers
Agents can code, administrate, and monitor. There are multiple risks associated with having AI-agents in the team:
1. Depending on the role, the agent may be very restricted (guardian, observer), tightly bound to a human-in-the-loop
   (think of assistants in Office software or IDE-integrations for code completion),
   or be a less restricted collaborateur with human oversight only on critical changes.
2. General IAM principles applicable to humans need to be enforced for AI agents as well: PolP (Principle of least privilege)
   Just-in-time instead of just-in-case authorization, strong authentication.
3. Prompt Injection: LLMs suffer from a lack of separation between data and execution, a problem of classical von-Neumann-Architectures
   that has been increasingly mitigated in the last 50 years. LLMs are vulnerable to instructions embedded in input data.
   Sanitization is non-trivial.

## High-level Requirement
Agents shall have access privileges on a as-needed basis, using the JIT (just in time) principle, as opposed to the JIC (just in case).
This requires isolation from the human's development workstation, accounts and key material.
Read-only access to untrusted sources (i.e., almost everything) and interfaces (MCP) must be limited to avoid unwanted behavior.

## Use Cases
The main use cases from an agent tooling perspective are:
* Terminal only, e.g. for remote administration via SSH. A github repo will be used to access issues and PRs.
* Web Browser, e.g., remote administration via Playwright MCP.
* Email, Calendar, local documents, messaging. The agent will have a dedicated identity.
* Development. Working in github repos with source code.

## First Use Case: Home Assistant Administration
Target system: Home Assistant on 10.4.4.10 (ssh: 22; http: 8123)
Repo: rhoerbe:hadmin

## Design

### Isolation Model
Rootless Podman provides filesystem and process isolation while sharing the host kernel.
Container UID 0 maps to unprivileged host UID via user namespaces—no in-container non-root user needed.
Use `--userns=keep-id` to map host UID into container for clean volume permissions.
For trusted agents (not adversarial code), this isolation level is sufficient.

```
+-------------------------------------+
¦  Podman Container                   ¦
¦                                     ¦
¦  Claude Code                        ¦
¦    +-- bash (built-in) --- ssh -----+--? 10.4.4.10:22
¦    +-- MCP: Playwright --- chromium +--? 10.4.4.10:8123
¦    +-- bash --- git/gh ------------+--? github.com
¦                                     ¦
¦  Outbound: api.anthropic.com        ¦
¦            github.com               ¦
¦            10.4.4.10                ¦
+-------------------------------------+
```

Alternatives considered: VM (heavy), systemd-nspawn (no advantage), MicroVM (hard to debug), chroot (weaker isolation).

### Network Isolation
- HTTP(S) traffic routes through a forward proxy (tinyproxy) with domain allowlist
- SSH goes direct to target, controlled by nftables
- Default-deny egress policy

### Agent Capabilities
Inside the container, Claude Code can:
- SSH to HA: validate config, inspect files
- Playwright MCP: browse HA web UI, configure automations
- Git/GitHub: clone repos, create PRs, manage issues

## Design Decisions

### SSH Access Control
- Forced commands restrict SSH key to specific operations
- Short-lived SSH certificates (signed by local CA) instead of static keys

### Browser Authentication
- HA long-lived access tokens via podman secrets
- Playwright uses API endpoints with Bearer auth where possible

### Secrets Management
- Podman secrets for all sensitive values
- Stored in admin user filesystem on host

### Audit Logging
- Terminal sessions captured via `script`
- Later: auditd, syslog forwarding

### Network Isolation
- Only proxy port and SSH to HA node allowed in nftables
- Container DNS resolves through proxy

### Deferred Items
- Container image pinning
- Vault agent sidecar
- Full audit infrastructure

## Persistence
- Workspace volume persists git repos across container restarts
- Claude Code sessions are stateless; GitHub issues/PRs serve as persistent memory

## Implementation
See [docs/agent-container-implementation.md](../docs/agent-container-implementation.md)
