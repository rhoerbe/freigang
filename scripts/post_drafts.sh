#!/bin/bash
# Post the agent's pending drafts to the mailbox's Drafts folder, now.
#
# The counterpart to sync_mail.sh: that one pulls mail in, this one pushes
# drafts out. Normally mail-renderer.timer does it every ten minutes; this is
# for when you have just asked the agent for a draft and want to see it in your
# mail client without waiting.
#
# Usage:
#   post_drafts.sh                 # post, wait, report what happened
#   post_drafts.sh --agent NAME    # another agent user (default: ha_agent)
#   post_drafts.sh --no-wait       # fire and forget, return immediately
#   post_drafts.sh --quiet         # no output unless something fails
#
# This is the only upward path in the mail design. The renderer builds each
# message with a closed header allowlist and APPENDs it to Drafts; it never
# sends. Drafts that fail validation are left in mail-out/failed/ with an error
# file, and this script points you at them.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib_agent_systemd.sh
source "$SCRIPT_DIR/lib_agent_systemd.sh"

AGENT_USER="ha_agent"
WAIT=true
QUIET=false
UNIT="mail-renderer.service"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --agent) AGENT_USER="$2"; shift 2 ;;
        --agent=*) AGENT_USER="${1#*=}"; shift ;;
        --no-wait) WAIT=false; shift ;;
        --quiet) QUIET=true; shift ;;
        -h|--help) sed -n '2,18p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "unknown option: $1 (try --help)" >&2; exit 2 ;;
    esac
done

say() { [[ "$QUIET" == true ]] || echo "$@"; }

agent_resolve_user

MAIL_OUT="/home/$AGENT_USER/workspace/mail-out"
FAILED_DIR="$MAIL_OUT/failed"

if ! agent_start_unit "$UNIT"; then
    echo "ERROR: could not start $UNIT for $AGENT_USER." >&2
    echo "       Has the agent_mail role been applied, and does the user have a" >&2
    echo "       lingering systemd session (loginctl enable-linger $AGENT_USER)?" >&2
    exit 1
fi

if [[ "$WAIT" == false ]]; then
    say "draft posting started for $AGENT_USER (not waiting)"
    exit 0
fi

result="$(agent_unit_result "$UNIT")"
# The renderer's own summary line is the useful part: posted/failed/deferred.
summary="$(agent_unit_log "$UNIT" 20 'posted=|configuration refused|IMAP unavailable')"

if [[ "$result" == "success" ]]; then
    say "draft posting finished for $AGENT_USER"
    [[ -n "$summary" ]] && say "$summary"
    # A non-zero failed= is not a unit failure, but it is what the user cares
    # about, so surface where to look rather than leaving a silent gap.
    if [[ "$summary" == *"failed="* && "$summary" != *"failed=0"* ]]; then
        say ""
        say "Some drafts were rejected. Reasons are in $FAILED_DIR:"
        sudo ls -1 "$FAILED_DIR" 2>/dev/null | sed 's/^/  /' || true
    fi
    exit 0
fi

echo "ERROR: $UNIT finished with Result=$result" >&2
agent_unit_log "$UNIT" 15 >&2
exit 1
