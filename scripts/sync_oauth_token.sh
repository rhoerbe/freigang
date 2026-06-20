#!/bin/bash
# Short-term bridge for container Claude auth (see issue #30).
#
# `claude setup-token` (the durable long-lived token minter) is currently broken
# against Anthropic's new OAuth endpoints. As a stopgap, copy the *host* user's
# current Claude access token into the agent secret that start_container.sh
# injects as CLAUDE_CODE_OAUTH_TOKEN.
#
# Run this as the logged-in host user (the one with a working /login) BEFORE
# launching the container. The access token is valid until its expiry (a few
# hours) regardless of the host session's refresh-token rotation, so re-run this
# whenever the container starts failing with 401. Replace with setup-token once
# that flow works again.
set -euo pipefail

SRC="${CLAUDE_CREDENTIALS:-$HOME/.claude/.credentials.json}"
AGENT_USER="${AGENT_USER:-ha_agent}"
AGENT_HOME="${AGENT_HOME:-/home/$AGENT_USER}"
DEST="$AGENT_HOME/workspace/.secrets/claude_oauth_token"

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
