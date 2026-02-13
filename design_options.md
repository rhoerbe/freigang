## Vault Agent Sidecar Pattern with Podman

  The sidecar pattern runs a OpenBoa/HashiCorp Vault agent alongside the main container. The agent authenticates to Vault, retrieves
  secrets, and renders them to a shared volume.

 ### How it works

  ┌─────────────────────────────────────────────────────────┐
  │  Pod (podman pod)                                       │
  │                                                         │
  │  ┌─────────────────┐     ┌──────────────────────────┐   │
  │  │ vault-agent     │     │ claude-ha-agent          │   │
  │  │                 │     │                          │   │
  │  │ - authenticates │     │ - reads secrets from     │   │
  │  │   to Vault      │     │   /secrets/*             │   │
  │  │ - renders       │────▶│ - SSH cert appears at    │   │
  │  │   templates     │     │   /secrets/ssh/id_ed25519│   │
  │  │ - renews leases │     │ - HA token at            │   │
  │  │                 │     │   /secrets/ha_token      │   │
  │  └─────────────────┘     └──────────────────────────┘   │
  │           │                         │                   │
  │           └─────────┬───────────────┘                   │
  │                     │                                   │
  │              tmpfs volume                               │
  │              /secrets (0700)                            │
  └─────────────────────────────────────────────────────────┘
                        │
                        ▼
                Vault Server
  

  ### Comparison: Podman Secrets vs Vault Sidecar
  ┌──────────────────┬────────────────┬───────────────────────────────────┐
  │      Aspect      │ Podman Secrets │           Vault Sidecar           │
  ├──────────────────┼────────────────┼───────────────────────────────────┤
  │ Setup complexity │ Low            │ High (needs Vault infrastructure) │
  ├──────────────────┼────────────────┼───────────────────────────────────┤
  │ Secret rotation  │ Manual restart │ Automatic (vault-agent renews)    │
  ├──────────────────┼────────────────┼───────────────────────────────────┤
  │ SSH certificates │ Not supported  │ Native (Vault SSH secrets engine) │
  ├──────────────────┼────────────────┼───────────────────────────────────┤
  │ Audit trail      │ None           │ Full audit log in Vault           │
  ├──────────────────┼────────────────┼───────────────────────────────────┤
  │ Lease/expiry     │ None           │ Built-in TTL enforcement          │
  ├──────────────────┼────────────────┼───────────────────────────────────┤
  │ Dynamic secrets  │ No             │ Yes (DB creds, cloud IAM, etc.)   │
  ├──────────────────┼────────────────┼───────────────────────────────────┤
  │ Dependencies     │ None           │ Vault server required             │
  └──────────────────┴────────────────┴───────────────────────────────────┘
  Practical recommendation

  Given your constraints:

  1. Phase 1 (now): Use podman secrets for ANTHROPIC_API_KEY and GITHUB_TOKEN. Generate SSH certs manually with a local CA:
      # On management host, sign agent's public key
      ssh-keygen -s ca_key -I "ha-agent" -n homeassistant -V +1d agent_key.pub
  1. Mount the cert into the container, regenerate daily via cron.
  2. Phase 2 (later): If you need dynamic secrets, audit logging, or manage multiple agents, deploy Vault with SSH secrets engine.
  The sidecar pattern then automates cert rotation.

  The sidecar adds operational overhead. It's justified when you have:
  - Multiple agents needing different credential scopes
  - Compliance requirements for secret access audit
  - Need for automatic credential rotation without container restarts


