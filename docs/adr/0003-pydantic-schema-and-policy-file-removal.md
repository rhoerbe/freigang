# The agent config schema is a pydantic model; the policy file is deleted

**Scope: repo-wide.** Issue #51.

`docs/agent-config-schema.md` describes the agent config in roughly 300 lines of prose. Nothing can
consume it, so nothing validates against it, and it drifts from the code it documents.

Separately, `/etc/freigang/policies/<agent>_policy.yaml` — carrying `secrets.allowed`,
`filesystem.writable_paths` and a proxy configuration — **enforces nothing**.
`start_container.sh:127` extracts `POLICY_FILE` and never uses it again; no other file in `scripts/`,
`containerize/` or `tests/` reads it. Its `storage_path` had already drifted to a directory `deploy.sh`
deletes, and nothing broke, because nothing reads it. A config that governs nothing but reads as a
security boundary is worse than no config: it invites the belief that the boundary exists.

**Decision:**

1. The agent config schema is a pydantic model, in its own package in this repo. The prose reference
   is generated from the model.
2. `resources.selectable_secrets`, `defaults`, `mail` and the rest keep their current shape.
   Identity fields — Linux username, mailbox, Matrix ID — are **explicit fields, never derived** from
   `agent_id`.
3. `container.vnc_port` becomes an explicit per-agent field.
4. The policy file, the `policy_file` field, and the policy section of the schema doc are **deleted**.

## Why

- **One artifact, not two.** A hand-written schema doc beside a machine-readable schema is the same
  disease this work exists to cure, one level up.
- **Its own package, not `freigang-mail-cli`.** `mail_cli` runs *inside* the container and currently
  declares zero dependencies. That footprint is a security property worth keeping; the config schema
  runs on the host and in CI, and pydantic has no business in the container image.
- **Explicit identities, because derivation is a constraint you cannot always satisfy.** A derived
  mailbox local-part or Linux username fails the moment an external system refuses the name or
  another agent collides. Convention (`<project>_agent`) is documented as a default; it is not
  enforced by construction. The existing `ha_agent`, whose name does not match its project
  (`hadmin`), is evidence enough.
- **Explicit VNC port, because agents run concurrently.** `5900` is hardcoded in two places. Computed
  ports collide silently; dynamic ports move the viewer target every launch.
- **The policy file is deleted rather than reserved.** Making it real — actually enforcing
  `secrets.allowed` and `writable_paths` — is a security-enforcement project that deserves its own
  issue rather than riding along inside a provisioning fix. Cedar is the likely successor and will
  want a different shape, so an empty reserved field would be one more thing to keep truthful for no
  benefit.

## Consequences

- The schema package is the artifact every other piece of this work conforms to — packaging and
  discovery, the user-space validator, `hosting`'s `host_vars` shape, and account provisioning. It
  lands first.
- Deleting `policy_file` is a breaking config change: every deployed `agents.d/*.yaml` carries it as
  a required field today.
- Until Cedar or an equivalent arrives, **there is no per-agent policy enforcement layer, and the
  repo should not imply that there is.** The real boundaries are the container, the mounts, the
  secrets actually passed, and the proxy allowlist.
