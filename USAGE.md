# Usage

Options reference for the deployment, container, CI and mail components. Every flag and variable
below was read from the source it documents; where a default is stated, it is the default in code.

- [Deployment](#deployment)
- [Container image](#container-image)
- [Launching an agent](#launching-an-agent)
- [Ansible](#ansible)
- [CI](#ci)
- [Mail](#mail)
- [Tests](#tests)
- [Home Assistant access](#home-assistant-access)

---

## Deployment

Two mechanisms exist and overlap. `deploy.sh` is the fast path for iterating on scripts; the Ansible
role is the one that provisions a host from scratch.

### `scripts/deploy.sh`

Copies the launcher and container files into the agent home. No options — run it and it does one
thing.

```bash
scripts/deploy.sh
```

Installs into `/home/ha_agent/`: `start_container.sh`, `config.sh`, `launcher_tui.py`,
`test_container.sh`, `mcp-config.json`, `mcp-manifest.json`.

It stamps the deployed `start_container.sh` with the source commit and a timestamp
(`DEPLOYED_COMMIT` / `DEPLOYED_AT`), which the launcher prints at startup. A `-dirty` suffix means
the working tree had uncommitted changes at deploy time. This exists because a stale deploy once ran
unnoticed for months (issue #30) — if the banner shows an old commit, redeploy before debugging
anything else.

### `ansible/playbooks/agent-setup.yml`

Full provisioning: creates the agent user, installs the same files, and configures mail. See
[Ansible](#ansible).

---

## Container image

### `scripts/refresh_container.sh`

The one-shot rebuild: pull base image, build, push to the agent account, prune dangling layers. No
options.

```bash
scripts/refresh_container.sh
```

**This publishes the image to the `ha_agent` account.** Nothing else in the repo does, so a code
change is not live for the agent until this runs.

### `containerize/build.sh`

Builds `localhost/claude-ha-agent:latest`. No options. Two build args are set automatically to
control layer caching:

| Build arg | Value | Effect |
|---|---|---|
| `WEEKLY_CACHE_BUST` | `date +%Y-%V` | Re-downloads yq and Playwright weekly |
| `CLAUDE_CACHE_BUST` | `date +%Y-%m-%d` | Re-downloads Claude Code daily |

Both are scoped so a bust does not invalidate the layers beneath it.

### `containerize/push_image.sh`

Copies the built image into the `ha_agent` account via `podman save | podman load`. No options.
(`podman image scp` is deliberately not used — see the comment in the script.)

---

## Launching an agent

`scripts/start_container.sh`, deployed as `/home/ha_agent/start_container.sh`. With no arguments it
shows the TUI, where MCP servers, secrets, browser mode, web filter and mail are selected per
session.

| Option | Effect |
|---|---|
| `--agent NAME`, `--agent=NAME` | Select the agent explicitly instead of via the menu. Reads `/etc/freigang/agents.d/NAME.yaml` |
| `--quick` | Skip the TUI and start with the agent's configured defaults |
| `--validate-auth` | Skip the TUI, run an in-container auth diagnostic, print the token state, exit. Implies `SKIP_AUTH_PROBE=1` |
| `--browser=MODE` | `none`, `playwright` or `chrome`. Implies `--quick` |
| `--vnc` | Enable VNC (only meaningful with a browser mode) |
| `--test` | Run preflight and network connectivity tests instead of starting the agent |
| `--debug` | `set -x` |
| *trailing command* | Anything unrecognised is passed to the container, e.g. `start_container.sh bash` |

| Environment variable | Effect |
|---|---|
| `SKIP_AUTH_PROBE=1` | Skip the live Anthropic token probe at launch. Use when the probe's network path is the problem, not the token |

Secret **selection** happens in the TUI; selected secrets are injected as environment variables
(`GH_TOKEN`, `HA_ACCESS_TOKEN`, `MQTT_USER`, `MQTT_PASS`, `CLAUDE_CODE_OAUTH_TOKEN`).

> Selecting fewer secrets in the TUI does not hide the others from the container: `.secrets/` lives
> inside the bind-mounted workspace, so every secret file is readable at `/workspace/.secrets/`
> regardless. Tracked as issue #38. The **mail** toggle is different — it adds or omits a mount, so
> unselected means genuinely absent.

### `scripts/sync_oauth_token.sh`

Last-resort fallback that copies the host user's short-lived `/login` access token into the agent
secret. Prefer `claude setup-token`, which mints a durable token. Reads `$CLAUDE_CREDENTIALS`
(default `~/.claude/.credentials.json`).

---

## Ansible

Run from the `ansible/` directory — `ansible.cfg` there is what resolves `roles_path`. From the repo
root you get a misleading "role not found".

```bash
cd ansible
ansible-playbook -i inventory/hosts.yml playbooks/agent-setup.yml
ansible-playbook -i inventory/hosts.yml playbooks/agent-proxy.yml
```

| Playbook | Roles | Purpose |
|---|---|---|
| `agent-setup.yml` | `agent_user`, `agent_mail` | Agent user, deployed files, mail sync + renderer |
| `agent-proxy.yml` | `tinyproxy`, `nftables` | Egress allowlist proxy and firewall rules |

Useful flags: `--check` (dry run), `--diff`, `--limit riva`, `-K` if sudo needs a password.

> `--check` fails at *"Enable and start the draft renderer timer"*, because check mode never writes
> the unit file it then tries to enable. That is a check-mode artifact, not a defect.

### `agent_mail` variables

| Variable | Default | Notes |
|---|---|---|
| `agent_mail_username` | `ha_agent` | Host user that owns the sync |
| `agent_mail_address` | `ha_agent@hoerbe.at` | Mailbox synced |
| `agent_mail_imap_host` | `mail.your-server.de` | Hostname, never an IP — shared-hosting IPs renumber |
| `agent_mail_imap_port` | `993` | |
| `agent_mail_maildir` | `{{ agent_mail_home }}/mail` | Outside `workspace/`, so the container cannot write it |
| `agent_mail_credential_dir` | `{{ agent_mail_home }}/.mailsync` | Never mounted into the container |
| `agent_mail_sync_interval` | `5min` | mbsync timer cadence |
| `agent_mail_imap_password` | *undefined* | See below |
| `agent_mail_renderer_root` | `{{ agent_mail_home }}/.mailrenderer` | Root-owned; the agent cannot modify renderer code |
| `agent_mail_renderer_from` | `{{ agent_mail_address }}` | Hard-coded `From:` on drafts |
| `agent_mail_renderer_to` | `{{ agent_mail_address }}` | Hard-coded `To:` on drafts |
| `agent_mail_renderer_drafts_folder` | `Drafts` | |
| `agent_mail_renderer_interval` | `10min` | Renderer timer cadence |
| `agent_mail_renderer_max_drafts` | `20` | Per run |
| `agent_mail_renderer_max_body_bytes` | `262144` | |
| `agent_mail_out_dir` | `{{ agent_mail_home }}/workspace/mail-out` | Agent-writable drop directory |

**The IMAP password is not in this repo and must not be.** freigang is public; committed
ansible-vault ciphertext would be permanently published and attackable offline, against a passphrase
shared with a private repo's vault. Place it by hand instead, once:

```bash
read -rs pw && printf '%s' "$pw" \
  | sudo install -o ha_agent -g ha_agent -m600 /dev/stdin \
    /home/ha_agent/.mailsync/imap_password
```

`read -rs` keeps it off the terminal and out of shell history; `printf '%s'` writes no trailing
newline, which keeps mbsync's `PassCmd "cat ..."` clean. The role installs its placeholder with
`force: false`, so re-running the playbook never clobbers a hand-placed password.

`agent_mail_imap_password` is still honoured if passed in (`-e @vault.yml --ask-vault-pass`) — keep
any such vault in a **private** repo.

### Checking the timers

```bash
u=$(id -u ha_agent)
sudo -u ha_agent env XDG_RUNTIME_DIR=/run/user/$u \
  DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$u/bus \
  systemctl --user list-timers
```

---

## CI

`.github/workflows/ci.yml`. Triggers: every push to `main`, and every pull request. No manual
dispatch, no schedule.

| Job | Steps |
|---|---|
| `pytest + ruff` | `uv run pytest -q`; `uvx ruff check mail_cli mail_renderer tests` |
| `ansible syntax` | `yaml.safe_load_all` over every `ansible/**/*.yml`; `ansible-playbook --syntax-check` per playbook |

The Ansible job exists because a role that could not parse survived several merges behind a green
Python suite (issue #37).

**What CI does not cover.** `--syntax-check` parses YAML but does not resolve `copy:` source paths,
so a task pointing at a non-existent file passes CI and fails on the host (issue #47). Catching that
needs `--check` against a real host with `become`. The bash test scripts under `tests/` and
`containerize/` are not run by CI either — they need a container and a live network.

Run the same checks locally:

```bash
uv run pytest -q
uvx ruff check mail_cli mail_renderer tests
cd ansible && ansible-playbook --syntax-check -i inventory/hosts.yml playbooks/agent-setup.yml
```

---

## Mail

Design and rationale: [docs/multi-agent-setup.md](docs/multi-agent-setup.md) and issue #37. The
container never speaks IMAP and holds no mail credential; all IMAP is host-side.

### `mail` — inside the container

Reads the read-only Maildir at `/mail`. Present only when the session's mail toggle is on.

| Command | Purpose |
|---|---|
| `mail ls` | List messages across all folders: date, folder, from, subject, attachment count, processed marker |
| `mail show <id>` | Decoded body, `text/plain` preferred, HTML stripped to text |
| `mail attach <id> <n>` | Extract attachment `n` (1-based, as numbered by `mail show`) |

| Option | Applies to | Effect |
|---|---|---|
| `--maildir PATH` | all | Override the Maildir (default `$MAIL_CLI_MAILDIR`, else `/mail`) |
| `--workspace PATH` | all | Override the workspace (default `$MAIL_CLI_WORKSPACE`, else `/workspace`) |
| `--folder NAME` | all | Restrict to one folder, case-insensitive (e.g. `--folder "Fronius Support"`) |
| `--no-mark-processed` | `show` | Do not record this message in the advisory processed-ledger |

| Environment variable | Default |
|---|---|
| `MAIL_CLI_MAILDIR` | `/mail` |
| `MAIL_CLI_WORKSPACE` | `/workspace` |
| `MAIL_CLI_ATTACH_MAX_BYTES` | `10485760` (10 MiB) |
| `MAIL_CLI_BODY_MAX_BYTES` | `512000` (500 KiB) |

Behaviour worth knowing before it surprises you:

- Every body is wrapped in an untrusted-content delimiter. That framing is in the tool, not in a
  prompt, so it cannot be forgotten.
- The processed-ledger is **advisory**: a marked message still appears in `mail ls`. Retire mail by
  dragging it out of the mailbox in your mail client.
- Attachments are extracted only on explicit `mail attach`, only for allowlisted types
  (`text/*`, JSON, YAML, CSV, `.log`, `.md`), into `/workspace/mail-attachments/<msg-id>/`. The
  destination name is computed by the tool, never taken from the MIME `filename`. There is no
  `--force`. See issue #44 for the open question about the matching rule.

### `mail-renderer` — on the host

Drains `/workspace/mail-out/`, renders RFC822, `APPEND`s to `Drafts`. Normally run by
`mail-renderer.timer`; the flags matter mainly for debugging a run by hand.

| Option | Environment variable | Default |
|---|---|---|
| `--mail-out PATH` | `MAIL_RENDERER_MAIL_OUT` | `/home/ha_agent/workspace/mail-out` |
| `--maildir PATH` | `MAIL_RENDERER_MAILDIR` | `/home/ha_agent/mail` |
| `--from-addr ADDR` | `MAIL_RENDERER_FROM` | *required* |
| `--to-addr ADDR` | `MAIL_RENDERER_TO` | *required* |
| `--imap-host HOST` | `MAIL_RENDERER_IMAP_HOST` | *required* |
| `--imap-port PORT` | `MAIL_RENDERER_IMAP_PORT` | `993` |
| `--imap-user USER` | `MAIL_RENDERER_IMAP_USER` | *required* |
| `--imap-password-file PATH` | `MAIL_RENDERER_IMAP_PASSWORD_FILE` | `/home/ha_agent/.mailsync/imap_password` |
| `--drafts-folder NAME` | `MAIL_RENDERER_DRAFTS_FOLDER` | `Drafts` |
| `--max-drafts N` | `MAIL_RENDERER_MAX_DRAFTS_PER_RUN` | `20` |
| `--max-body-bytes N` | `MAIL_RENDERER_MAX_BODY_BYTES` | `262144` |
| `--verbose` | — | Debug logging |

`From:` and `To:` are configuration and are never taken from agent input. Only `Subject`, `Date` and
`In-Reply-To` come from the draft, and only after validation; every other proposed header is
dropped. A recipient the agent proposes appears as visible body text, so sending still requires you
to type an address.

Drained sidecars move to `mail-out/posted/` on success, and to `mail-out/failed/` with an error file
on rejection — a draft that never appeared is diagnosable there.

### Agent draft format

The agent writes `<name>.json` plus `<name>.txt` into `/workspace/mail-out/`:

```json
{
  "subject": "Re: heating schedule",
  "in_reply_to": "<1234@example.test>",
  "proposed_recipients": ["someone@example.test"],
  "body_file": "draft-01.txt"
}
```

Only `subject` is required. `body_file` defaults to the sidecar's stem plus `.txt` and must be a
plain filename inside `mail-out/`. Any other key — `to`, `cc`, `bcc`, `from`, `headers` — is dropped.

---

## Tests

| Command | Where | Covers |
|---|---|---|
| `uv run pytest -q` | host or container | `mail_cli` and `mail_renderer` |
| `containerize/test_container.sh [preflight\|network\|chrome\|all]` | host | Container preflight, network reachability, Chrome integration. Default `all` |
| `start_container.sh --test` | host | Same, via the launcher |
| `tests/run_tests.sh` | inside container | Bash suite: proxy allow/block, secrets, HA API, MQTT, GitHub, Playwright |
| `tests/run_integration.sh` | inside container | Integration subset |

```bash
sudo -iu ha_agent bash -c 'cd ~/tests && ./run_integration.sh'
```

---

## Home Assistant access

The agent uses the HA REST API over HTTP, authenticated with `HA_ACCESS_TOKEN` (injected when
selected in the TUI).

```bash
# Inside the container
curl -s -H "Authorization: Bearer $HA_ACCESS_TOKEN" http://10.4.4.10:8123/api/
curl -s -H "Authorization: Bearer $HA_ACCESS_TOKEN" http://10.4.4.10:8123/api/states

curl -s -X POST -H "Authorization: Bearer $HA_ACCESS_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"entity_id": "light.living_room"}' \
    http://10.4.4.10:8123/api/services/light/turn_on
```

## Prerequisites

- `ha_agent` user configured (see [docs/setup.md](docs/setup.md))
- Secrets present in `/home/ha_agent/workspace/.secrets/`
- Podman network `ha-agent-net` exists
- Tinyproxy running on host port 8888
