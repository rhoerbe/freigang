# freigang is a value-free collection; deployment values live in a private inventory repo

**Scope: repo-wide.** Issue #51.

`/etc/freigang/agents.d/<agent>.yaml` gates every per-agent capability and was maintained entirely
by hand: not in the repo, no template, not touched by the `agent_user` or `agent_mail` roles. The
same was true of `/etc/freigang/policies/<agent>_policy.yaml`.

Issue #37 records the consequence. The `agent_mail` role provisioned the sync, the credential, the
renderer and the timers, and the launcher shipped a Mail toggle — but the toggle never appeared,
because nothing had added the `mail:` block to the deployed config. The infrastructure was fully in
place and the capability was invisible.

It happened a second time: after #38 moved secrets to `/home/ha_agent/.secrets`, the deployed policy
file still declared `storage_path: /home/ha_agent/workspace/.secrets` — a path `deploy.sh` actively
deletes.

The underlying cause is not a missing template. It is that this repo mixed a reusable engine with one
deployment's values: `agent_user` hardcoded `ha_agent`, and `agent_mail` published
`ha_agent@hoerbe.at` and `mail.your-server.de` as role defaults. Values that live in role defaults
cannot be per-agent, and a public repo cannot hold them anyway.

**Decision:** freigang becomes a value-free Ansible collection, `rhoerbe.freigang`, versioned by
semver and consumed by tag. Every per-agent value and every secret lives in `rhoerbe/hosting` — the
private repo that already manages these hosts and already has an ansible-vault arrangement
(hosting's ADR-0001). Role variables carry no deployment defaults and are declared required through
`meta/argument_specs.yml`.

## Why

- **The drift becomes structurally impossible, not merely detected.** When the same `host_vars`
  parameterise the roles and generate the agent config, provisioning a capability and enabling it are
  the same Ansible run. Issue #51 proposed validating the config and failing loudly; that is a guard
  around a defect this removes.
- **`argument_specs.yml` is the loud failure, delivered through the role interface.** A required arg
  with no default fails with a clear message when a value is missing — #51's option 3 without a
  bespoke validator.
- **The repo is public.** Deployment values had nowhere legitimate to live here. A private inventory
  repo is where they belong, and one already exists and already manages riva and ray.
- **Pinning by tag, not branch.** An unpinned branch means a host is provisioned differently
  depending on when the playbook runs — the same drift class, relocated.

Rejected: templating the agent config from values held *in this repo* (impossible while it is
public); a bespoke validator as the primary mechanism (guards a defect rather than removing it); a
sample config in `examples/` (documents the schema, prevents nothing).

## Consequences

- Freigang can no longer deploy anything on its own. It keeps a fixture playbook and a dummy
  inventory with obviously-fake values so the roles stay syntax-checkable and testable in CI, and for
  no other purpose.
- Editing an agent's configuration means editing `host_vars` in `hosting` and re-running the
  playbook, not editing YAML on the target host. This is friction, and it is the point.
- Two repos, two epics, two branch-per-issue histories: freigang #51 and rhoerbe/hosting#75.
- The legacy code path (`config.sh`'s hardcoded branch, `start_container.sh`'s legacy fallback,
  `deploy.sh`) survives only until riva migrates, so the fallback node keeps working in the meantime.
