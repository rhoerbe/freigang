# An agent never communicates outward autonomously

**Scope: repo-wide.** Issues #37, #51.

Issue #37 built the mail capability around a property that is easy to lose and hard to recover: the
container never speaks IMAP and never holds the mail credential. Mail is synced **down** by the host
to a read-only mount at `/mail`; the only upward path is a drop directory the agent writes to, drained
by a root-owned renderer that `APPEND`s to a `Drafts` folder. The agent proposes; a human sends.

Per-agent Matrix identities now raise the same question, and the tempting answer — hand the container
an access token and let it talk to the homeserver through the proxy allowlist — is much simpler.

**Decision:** every outward channel an agent is given follows the mail shape:

1. The container never holds the channel's credential.
2. Inbound content reaches the agent through a host-side sync into a **read-only** mount.
3. Outbound content is written to a **drop directory** inside the agent's writable tree and drained
   by a **root-owned** host-side process the agent cannot modify.
4. Nothing leaves without a human acting on it.

A channel that cannot meet this ships **read-only** until it can.

## Why

- **It is the property the whole sandbox exists to provide.** A compromised or confused agent that
  can autonomously send mail or messages has an exfiltration path and an impersonation path, and both
  bypass every other boundary here — the content leaves from *inside* the trusted position.
- **Matrix is worse than mail, not better.** Messages are instant and there is no `Drafts` folder
  acting as a review gate. The mail design gets a human checkpoint almost for free from the medium;
  Matrix has to be given one deliberately.
- **A private network is not a mitigation.** Human error forwards poisoned content into private
  networks routinely, and a private homeserver is exactly where a message from a known identity is
  trusted least critically.
- **Architecture over convention.** The mail store for agents is IMAP-only with no inbound SMTP
  (rhoerbe/hosting#75): mail enters an agent's mailbox only when a human moves it there. This turns
  #37's guarantee from a credential-placement convention into a property of a service with no other
  path.

Rejected: giving the container a scoped or short-lived token. Scoping reduces blast radius; it does
not restore the human checkpoint, which is the actual property.

## Consequences

- Every new channel costs a host-side sync process and a host-side drain process. That is the price
  of the property, and it is why channels should be added deliberately rather than opportunistically.
- Agents cannot answer anything in real time. This is intended.
- The drop directory sits in the agent's writable tree, so the draining process must treat everything
  in it as **untrusted input** — it runs as root, and the agent controls its contents.
- Read-only-first is an acceptable first cut for any new channel, and is preferable to shipping a
  send path that skips the checkpoint.
