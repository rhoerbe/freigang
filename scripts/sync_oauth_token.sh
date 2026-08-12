#!/bin/bash
# DEPRECATED emergency bridge (see issue #30 and docs/agent-auth-design.md).
#
# Prefer `claude setup-token`, which mints a durable (~1y) token and works on the
# current CLI - it was only briefly broken in Feb 2026. This script instead
# copies the host user's short-lived /login *access token* into the agent secret
# that start_container.sh injects as CLAUDE_CODE_OAUTH_TOKEN. That access token:
#   * expires in ~8h, so you must re-run this whenever the container 401s, and
#   * is inference-only when delivered via env var - it can NEVER do Remote
#     Control (which needs a full-scope /login; see claude-rc / Tier-2).
# Use only as a last resort when you cannot mint a setup-token. It writes the
# legacy secret name, which start_container.sh accepts with a warning.
set -euo pipefail

SRC="${CLAUDE_CREDENTIALS:-$HOME/.claude/.credentials.json}"
AGENT_USER="${AGENT_USER:-ha_agent}"
AGENT_HOME="${AGENT_HOME:-/home/$AGENT_USER}"
DEST="$AGENT_HOME/.secrets/claude_oauth_token"

if [[ ! -f "$SRC" ]]; then
    echo "ERROR: $SRC not found - log in on the host with /login first." >&2
    exit 1
fi

token=$(jq -r '.claudeAiOauth.accessToken // empty' "$SRC")
if [[ -z "$token" ]]; then
    echo "ERROR: no claudeAiOauth.accessToken in $SRC" >&2
    exit 1
fi

exp=$(jq -r '.claudeAiOauth.expiresAt // 0' "$SRC")
now=$(( $(date +%s) * 1000 ))
if (( exp > 0 && exp < now )); then
    echo "WARNING: host access token already expired ($(date -d @$((exp/1000))))." >&2
    echo "         Let your host Claude session refresh (or run /login), then re-run." >&2
fi

printf '%s' "$token" | sudo install -o "$AGENT_USER" -g "$AGENT_USER" -m600 /dev/stdin "$DEST"
echo "Wrote $DEST"
if (( exp > 0 )); then
    echo "Token valid until: $(date -d @$((exp/1000)))"
fi
