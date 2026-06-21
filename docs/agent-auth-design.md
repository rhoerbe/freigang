# Agent Authentication Design — one subscription, many systems

Status: **draft for review** · Date: 2026-06-21 · Context: issue #30, PR #31

## Objective

Run Claude Code **agents across many systems** — Win 11 notebook, WSL, Linux VMs, and
rootless-Podman containers (the Freigang `*_agent` model) — all backed by **one Claude
subscription** (currently **Pro**), without per-agent interactive `/login` babysitting,
while **not precluding** occasional Remote Control of a session.

## TL;DR — the decision

Two tiers, chosen per agent:

| Tier | For | Auth | Lifetime | Remote Control |
|---|---|---|---|---|
| **1 — Baseline** (default) | every headless / unattended / container agent | `CLAUDE_CODE_OAUTH_TOKEN` from `claude setup-token` | ~1 year | ❌ inference-only |
| **2 — RC on demand** (opt-in, occasional) | a session you want to drive from phone/web | `unset CLAUDE_CODE_OAUTH_TOKEN` → `claude auth login` (full-scope) → `claude remote-control` | ~8 h, self-refreshing while running | ✅ |

Rationale: subscription `/login` credentials are the *wrong primitive* for an
**intermittently launched** headless agent — they assume a long-lived interactive session
doing the token refresh; an idle container's credential simply rots (this is exactly how
`ha_agent` died). A `setup-token` is idle-proof. Remote Control needs a *full-scope* login
token, so it is handled as a deliberate, occasional switch rather than the baseline.

## How Claude Code authentication actually works (verified 2026-06-21, CLI 2.1.185)

### Credential precedence (Claude picks the first present)

1. Cloud provider (Bedrock / Vertex / Foundry)
2. `ANTHROPIC_AUTH_TOKEN` — Bearer; for LLM gateways/proxies
3. `ANTHROPIC_API_KEY` — Console key; **metered**, sent as `x-api-key`
4. `apiKeyHelper` — script returning a key (called on 401 / every 5 min)
5. **`CLAUDE_CODE_OAUTH_TOKEN`** — long-lived token from `claude setup-token`
6. **`/login`** subscription OAuth — the interactive default

> Trap: #5 sits **above** #6. With the baseline env var set, an in-container `claude auth
> login` is silently ignored and Remote Control fails with *"requires a full-scope login
> token"*. Tier-2 **must** start by unsetting `CLAUDE_CODE_OAUTH_TOKEN`.

### Token types vs capabilities

| Token | Source | Lifetime | Inference | Remote Control |
|---|---|---|---|---|
| `/login` full-scope session | `claude` / `claude auth login` | ~8 h access + rotating single-use refresh; needs a live session to stay alive | ✅ | ✅ |
| `setup-token` → `CLAUDE_CODE_OAUTH_TOKEN` | `claude setup-token` | ~1 year, no rotation | ✅ | ❌ (*"scoped to inference only"*) |
| `ANTHROPIC_API_KEY` | Console (platform.claude.com) | static | ✅ (metered) | ❌ (*"API keys are not supported"*) |

Remote Control requires CLI **≥ 2.1.51**, claude.ai OAuth, and is available on Pro.

### Verified behaviours (the `claude auth status` oracle)

`claude auth status` reports the active method non-interactively. On a throwaway
`CLAUDE_CONFIG_DIR`:

| Config state | `CLAUDE_CODE_OAUTH_TOKEN` | Result |
|---|---|---|
| fresh, no token | — | `loggedIn:false, authMethod:none` |
| fresh, **not onboarded** | set | `loggedIn:true, authMethod:oauth_token` |
| onboarded | set | `loggedIn:true, authMethod:oauth_token` |

And `claude -p "…"`: fails with *"Not logged in · Please run /login"* without a token,
returns a completion **with** the env token — on a fresh, never-logged-in config dir.

**Conclusion:** the env token is **never ignored at the auth layer**. The "select a login
method" screen seen on a fresh machine is the **interactive onboarding wizard** (shown when
`.claude.json` is absent), not an auth failure. Remedies for fresh *interactive* machines:
seed `.claude.json` with `hasCompletedOnboarding: true`, or run once to complete onboarding,
or use `-p` (which skips onboarding entirely).

## Post-mortem: why the container kept demanding `/login` (issue #30 / PR #31)

Two independent breakages, both live on 2026-06-21:

1. **PR #31 was never deployed.** Agents run as `sudo -iu ha_agent`, executing the
   **deployed** `/home/ha_agent/start_container.sh` — dated **16 March**, with *no* token
   injection. The PR's injection code exists only on branch `issue-30`; `deploy.sh` was not
   re-run. So the container launched with **no Anthropic credential** and fell through to
   `ha_agent`'s own `~/.claude/.credentials.json`, which had **expired 20 Jun 04:12** (a
   `/login` token dead from idleness).
2. **Wrong token type even if deployed.** The artifact the PR injects,
   `.secrets/claude_oauth_token`, is **not** a `setup-token` — it is a **copied `/login`
   access token** (`sk-ant-oat01-…`, 108 chars) written by the stopgap
   `sync_oauth_token.sh`. Access tokens die in ~8 h, so it would 401 within hours anyway.

PR #31's *description* (use `setup-token`) is correct; its *implementation* (copy an access
token) is not. The "setup-token is broken" note in `sync_oauth_token.sh` was a February
condition — `claude setup-token` works on 2.1.185.

Also found: `.secrets/anthropic_api_key` is a 26-char `oauth-via-…` placeholder, not a real
Console key.

## Per-environment plan

| Environment | Mode | Baseline auth | Notes |
|---|---|---|---|
| Containers (`*_agent`) | interactive `claude` (CMD), unattended | inject `CLAUDE_CODE_OAUTH_TOKEN` (setup-token) | onboarding already seeded (`hasCompletedOnboarding:true`); works once a *valid* token is injected |
| Linux VMs (SSH'd) | headless `-p` or interactive | setup-token env var | callback server unreachable over SSH → never rely on interactive `/login` |
| WSL | interactive or `-p` | setup-token env var | known callback-unreachable case |
| Win 11 notebook | interactive (you sit here) | `/login` | the natural place to mint the setup-token and to run Tier-2 RC |
| CI | `-p` | setup-token in CI secret | the canonical setup-token use case |

All of the above draw from the **same shared subscription quota** (web + every agent). Pro
is the smallest pool; a fleet of concurrent agents will hit rate limits before auth does.

## Operational invariants the launcher/TUI must assert

The issue #30 incident traces to silent drift. `start_container.sh` (and the TUI) should
refuse to launch — loudly — unless **all** hold:

1. **Run-as identity** = the agent user (the "User Mismatch" guard exists for YAML-config
   mode; extend it to legacy mode too).
2. **Deployed == source.** Stamp `git rev-parse HEAD` (or a version) into the script header
   at `deploy.sh` time; compare against the repo at launch and warn on mismatch.
3. **Credential is valid.** Preflight with a live `claude -p` probe and fail with a clear
   message instead of dropping the agent at a `/login` it cannot complete. Note: `claude
   auth status` only reports a token is *present* — a bogus token still shows
   `loggedIn:true` — so a real inference call (which 401s on a dead token) is the only
   reliable validator. (Implemented as `validate_claude_token` with a `SKIP_AUTH_PROBE=1`
   opt-out.)

## PR #31 — required corrections

- Replace the access-token copy with a real **`setup-token`** secret
  (`.secrets/claude_setup_token`); inject it as `CLAUDE_CODE_OAUTH_TOKEN`.
- Demote/remove `sync_oauth_token.sh` (it can never enable Remote Control and expires in
  hours); keep only as a documented emergency bridge, if at all.
- Add the three launch invariants above.
- Add a `claude-rc` helper for Tier-2: `unset CLAUDE_CODE_OAUTH_TOKEN; claude auth login;
  claude remote-control`.
- Fix `AGENT_ACCESS.md`: the `CLAUDE_CODE_OAUTH_TOKEN` line should describe a `setup-token`
  (it currently does, but the implementation must match it).
- Note the RC ≥ 2.1.51 requirement (applies to Tier-2 only).

## Open questions / tests still to run

1. ✅ **One token, many machines, concurrently — VERIFIED** (2026-06-21, #32): a single
   `CLAUDE_CODE_OAUTH_TOKEN` authenticated ray (2.1.176) and riva (2.1.185) with overlapping
   `claude -p` calls — both exit 0, no 401. → baseline is **one shared setup-token** for the
   fleet, not one per agent. Quota stays shared (see #4).
2. **Does minting a new `setup-token` revoke a prior one?** (Verified: it does **not**
   invalidate the interactive `/login` session.)
3. **rainova cross-machine kill** — when `/login` on riva apparently invalidated rainova:
   shared credential file, or an account-level grant cap? (Local evidence shows ≥2 `/login`
   grants — r2h2 + ha_agent — coexisting, so a hard "1 device" cap is unlikely.)
4. **Pro quota** sufficiency for N concurrent agents; Max if not. (Parked tier decision.)
5. **ray loose end:** `claude` is not installed for `agent` or `r2h2` on 10.2.2.50 — confirm
   which user/path ran the interactive `claude` that showed the onboarding picker.

## References

- Authentication — https://code.claude.com/docs/en/authentication
- Remote Control — https://code.claude.com/docs/en/remote-control
- Use Claude Code with Pro/Max — https://support.claude.com/en/articles/11145838
- Related: [multi-agent-setup.md](multi-agent-setup.md), [../AGENT_ACCESS.md](../AGENT_ACCESS.md)
