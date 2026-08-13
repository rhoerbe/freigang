# System-space agent config always outranks user-space

**Scope: repo-wide.** Issue #51.

Agent configuration is to be readable from two tiers: `/etc/freigang/agents.d/` (root-owned, and the
tier a future enterprise deployment would manage centrally) and `~/.config/freigang/agents.d/` in the
launching operator's home. Today neither is a search path — `start_container.sh` hardcodes
`/etc/freigang/agents.d` twice and has no notion of a second location.

Adding a second tier raises a question that looks like lookup-order convenience and is not.

**Decision:** system-space always wins. A user-space config may define agents that
`/etc/freigang/agents.d/` does not define; it may never override, extend or partially merge into one
that it does. Resolution is per `agent_id`, not per key. The launcher logs which tier a config was
read from.

## Why

- **It is an enforcement boundary or it is decoration.** If user-space can override system-space,
  then any operator who can write their own home directory can grant themselves `mail.enabled: true`,
  additional secrets, or `bypassPermissions` — regardless of what the centrally managed tier says. A
  tier that anyone can overrule does not constrain anyone.
- **Per-key merging is worse than per-agent override**, not better: it makes the effective
  configuration of an agent a computation across two files, so no single artifact states what an
  agent is allowed to do.
- **The permissive rule is unrecoverable later.** Loosening a strict rule is a change; tightening a
  loose one breaks whatever came to depend on it.

## Consequences

- Local experimentation on an agent that system-space already defines requires editing system-space —
  deliberately. Experiments belong in a *new* `agent_id`, which user-space grants freely.
- The launcher must report the winning tier, so "my edit did nothing" is answerable at a glance.
- This rule is a spec obligation on the packaging/discovery work, which is where config discovery
  gets implemented; `start_container.sh` is not the right place to build it, being a script that work
  deletes.
