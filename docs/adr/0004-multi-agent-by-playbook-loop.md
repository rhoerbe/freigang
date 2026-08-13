# Multiple agents come from looping role invocations, not from roles that loop internally

**Scope: `ansible/`.** Issues #19, #51.

`agent_user` creates exactly one user; `agent_mail` syncs exactly one mailbox. Issue #19 wants
multiple agents for multiple projects with different capabilities. Removing the hardcoded values
(ADR-0001) is necessary but does not by itself say how N agents are provisioned.

Investigation found the roles are not merely single-agent — they are **unsafe when invoked more than
once in a play**:

- `agent_mail/tasks/renderer.yml` opens with `set_fact` resolving each setting as
  `x | default(<derived>)`. `set_fact` persists for the whole play, so on the second invocation those
  variables are already defined and `default()` never fires. Agent B silently inherits agent A's
  renderer root, `From:` address and `mail-out` directory — one agent sending mail as another.
- `agent_mail/handlers/main.yml` restarts `mbsync.timer` as `{{ agent_mail_username }}`. Handlers
  flush once, at end of play, with the variables as they stand then, so a config change for one agent
  restarts whichever agent the loop finished with. `renderer.yml` already documents avoiding this
  ("There is deliberately no handler here either").

**Decision:** agents are provisioned by invoking the per-agent roles once per agent from the
playbook, in `rhoerbe/hosting`. Roles do not loop internally.

The role set splits explicitly:

- **per-agent:** `agent_user`, `agent_mail`
- **per-host:** `tinyproxy`, `nftables`

The two bugs above are fixed as part of removing the hardcoded values, in the same change — not as a
follow-up. Renderer settings become role vars scoped to the invocation instead of play-scoped
`set_fact`; the handler is replaced by unconditional restart, the pattern `renderer.yml` already
uses.

## Why

- **N agents today, no role redesign.** Internal looping is speculative generality for a second agent
  that does not exist yet, and it makes targeting a single agent harder rather than easier.
- **Each agent stays independently runnable and independently debuggable.**
- **The fixes are not optional.** A de-hardcoded role that corrupts on its second invocation is not
  de-hardcoded; it is a single-agent role with the guard rail removed.
- **The per-host roles genuinely cannot loop.** `tinyproxy` is one daemon with one allowlist;
  `nftables` is one ruleset with one subnet. Looping them would have each iteration overwrite the
  last.

## Consequences

- Agents are assumed to run **concurrently**. Each therefore needs its own podman network and its own
  VNC port (ADR-0003); the current single `ha-agent-net` and hardcoded `5900` are collisions waiting
  to happen.
- **Per-agent capabilities are not yet fully expressible.** A single shared `tinyproxy` cannot say
  "agent A reaches Home Assistant, agent B does not" — and `agent_allowed_destinations` currently
  hardcodes SSH to `10.4.4.10`, which is exactly such a capability. Egress is the strongest capability
  boundary available, so this is a real gap, tracked as its own issue. Per-agent podman networks are
  the seam it will need.
- Adding an agent is an inventory change in `hosting`, not a change here.
