# Agent Isolation using Containers

## High-level Requirement
Agents shall have access privileges on a as-needed basis, using the JIT (just in time) principle, as opposed to the JIC (just in case).
This requires isolation from the human's development workstation, accounts and key material.

## Use Case
The main use cases from an agent tooling perspective are:
* Terminal only, e.g. for remote administration via SSH. In this case, we need no GUI or terminal. The container does not need to have a terminal, if it has an SSH server. A github repo will be used to access issues and PRs.
* Web Browser, e.g., remote administration. The agent has access to the Web Interface (Claude in chrome, Claude Cowork once available for Linux, Playwright?). 
* Email, Calendar, local documents, messaging. The agent will have a dedicated identity and email, the human user will only share mails etc. on a as-needed basis. May need Web access to site with authentication
* Development. Working in github repos with source code, the agent will update local repos.


## Design
### User Space Isolation
Plain containers (Podman/Docker) give you filesystem and process isolation but share the host kernel. 
This is usually sufficient - the agent can't see your home directory unless you bind-mount it, 
it gets its own network namespace if you want, and you control capabilities granularly. 
The risk is kernel exploits, but for a trusted agent (not adversarial code), this is fine.

The following picture shows agent isolation allowing ssh and web access to 10.4.4.10:
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

Alternatives:
- VM: good isolation, but fairly heavy.
- systemd-nspawn: no big advantages over containers
- MicroVM: hard to debug
- chroot env

## Network isolation
Design: do not use netfilter for web access, because it is IP-based instead of DNS.
Instead, use a forward proxy (tinyproxy) on the host.
When the container talks to the proxy on the host gateway (10.89.1.1), that's INPUT traffic, not FORWARD (host perspective). 
The only thing that needs FORWARD is the direct SSH connection to your HA node. 


Container (10.89.1.2)
  ¦
  +-- SSH to 10.4.4.10:22        ? FORWARD chain (routed through host)
  +-- HTTP proxy to host:8888     ? INPUT chain (destination is the host itself)

Host (tinyproxy on 10.89.1.1:8888)
  ¦
  +-- outbound to github, anthropic, etc. ? OUTPUT chain (host's own traffic)

Run a small HTTP proxy that allows only specific domains:
bash# tinyproxy.conf
Allow 10.89.1.0/24
FilterURLs On
Filter "/etc/tinyproxy/allowlist"

# allowlist (regex)
^10\.4\.4\.10
^(.*\.)?github\.com
^(.*\.)?githubusercontent\.com
^api\.anthropic\.com
^(.*\.)?npmjs\.org

Then run tinyproxy on the host or in a sidecar, and configure the container to use it:
bashpodman run ... \
  -e HTTP_PROXY=http://host.containers.internal:8888 \
  -e HTTPS_PROXY=http://host.containers.internal:8888 \
  ...
This handles domain-based filtering cleanly. SSH goes direct (not proxied), so we need the a nftables rule allowing 10.4.4.10:22.

Create a dedicated podman network, then firewall it:
bashpodman network create ha-agent-net --subnet 10.89.1.0/24
Then nftables rules on the host:
````bash
podman network create ha-agent-net --subnet 10.89.1.0/24
````

````nft
    nfttable inet agent-firewall {
        chain forward {
            type filter hook forward priority 0; policy accept;
    
            # Identify traffic from the agent container network
            ip saddr 10.89.1.0/24 jump agent-egress
        }
    
        chain agent-egress {
            # Allow established/related
            ct state established,related accept
    
            # Allow DNS (needed for github.com resolution)
            udp dport 53 accept
            tcp dport 53 accept
    
            # Allow HA node
            ip daddr 10.4.4.10 tcp dport { 22, 8123 } accept
    
            # Allow GitHub (IP ranges change, so use DNS  
            # or proxy through a forward proxy for tighter control)
            ip daddr { 140.82.112.0/20, 143.55.64.0/20, 192.30.252.0/22 } accept
    
            # Allow Anthropic API
            # (similarly, you'd resolve api.anthropic.com and allow those IPs,
            #  or use a proxy)
    
            # Drop everything else
            drop
        }
    }
 ````

## What Claude Code can then do
Inside the container, Claude Code is allowed to:

ssh ha "ha core check" - validate HA config
ssh ha "cat /config/configuration.yaml" - inspect config
Via Playwright MCP: navigate to http://10.4.4.10:8123, log in, browse integrations, check logs, configure automations through the UI
cd workspace/ha-config && git pull - work on config-as-code
gh issue list - check what needs doing
Edit files, commit, push, create PRs

## Design Decisions

### SSH Access Control
- **Forced commands**: Restrict SSH key to specific commands via `authorized_keys`:
  ```
  command="/usr/local/bin/ha-agent-shell",no-port-forwarding,no-X11-forwarding ssh-ed25519 AAAA...
  ```
- **SSH certificates**: Use short-lived certificates instead of static keys. Sign with a local CA, regenerate via cron:
  ```bash
  ssh-keygen -s ca_key -I "ha-agent" -n homeassistant -V +1d agent_key.pub
  ```

### Browser Authentication
- Use HA long-lived access tokens passed as environment variable
- Playwright uses API endpoints with `Authorization: Bearer $HA_ACCESS_TOKEN` where possible
- Fall back to UI automation only when API is insufficient

### Secrets Management
- Use `podman secret create` for sensitive values (API keys, tokens)
- Secrets stored in admin user filesystem on host
- Mount via `--secret` flag, not environment variables for sensitive data

### Audit Logging
- **Now**: Use `script` to capture terminal sessions
- **Later**: auditd inside container, syslog forwarding to host

### Network Isolation
Tighter nftables rules - only allow proxy port, block direct DNS:
```nft
ip saddr 10.89.1.0/24 tcp dport 8888 accept  # proxy only
ip saddr 10.89.1.0/24 ip daddr 10.4.4.10 tcp dport 22 accept
ip saddr 10.89.1.0/24 drop
```
Container DNS resolves through proxy or uses DoH.

### Deferred Items
- Container image pinning (digest-based FROM)
- Vault agent sidecar for dynamic secrets
- Full audit infrastructure

## Persistence
- Workspace volume persists git repos across container restarts
- Claude Code sessions are stateless; GitHub issues/PRs serve as persistent memory

