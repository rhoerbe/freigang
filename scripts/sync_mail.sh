#!/bin/bash
# Trigger a one-off mail sync for an agent, outside the container.
#
# The container never speaks IMAP (issue #37), so a sync can only be started
# here, on the host. Normally mbsync.timer does it every few minutes; this is
# for the times you do not want to wait -- you just dragged mail into the
# mailbox and want it visible now.
#
# Usage:
#   sync_mail.sh                 # sync, wait, report what changed
#   sync_mail.sh --agent NAME    # another agent user (default: ha_agent)
#   sync_mail.sh --no-wait       # fire and forget, return immediately
#   sync_mail.sh --quiet         # no output unless something fails
#
# Safe to run at any time: the sync is one-way DOWN, so it can only add or
# remove local copies of what the server already has. It never writes upward.
set -euo pipefail

AGENT_USER="ha_agent"
WAIT=true
QUIET=false

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

if ! id "$AGENT_USER" >/dev/null 2>&1; then
    echo "ERROR: no such user: $AGENT_USER" >&2
    exit 1
fi

AGENT_UID="$(id -u "$AGENT_USER")"
MBSYNCRC="/home/$AGENT_USER/.mailsync/mbsyncrc"

# Run as the agent user unless we already are it. systemd --user needs both
# XDG_RUNTIME_DIR and the session bus address; without them systemctl reports
# "Failed to connect to bus" even though the units are perfectly fine.
run_as_agent() {
    if [[ "$(id -un)" == "$AGENT_USER" ]]; then
        env XDG_RUNTIME_DIR="/run/user/$AGENT_UID" \
            DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$AGENT_UID/bus" "$@"
    else
        sudo -u "$AGENT_USER" env XDG_RUNTIME_DIR="/run/user/$AGENT_UID" \
            DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$AGENT_UID/bus" "$@"
    fi
}

start_args=(systemctl --user start mbsync.service)
[[ "$WAIT" == true ]] || start_args=(systemctl --user start --no-block mbsync.service)

if run_as_agent "${start_args[@]}" 2>/dev/null; then
    if [[ "$WAIT" == false ]]; then
        say "mail sync started for $AGENT_USER (not waiting)"
        exit 0
    fi
    result=$(run_as_agent systemctl --user show mbsync.service -p Result --value 2>/dev/null || echo unknown)
    if [[ "$result" == "success" ]]; then
        say "mail sync finished for $AGENT_USER"
        # The Near counters say what actually landed: +added *flag-changed -deleted
        say "$(run_as_agent journalctl --user -u mbsync.service -n 20 --no-pager 2>/dev/null \
                | grep -E 'Channels:|Boxes:' | tail -1 || true)"
        exit 0
    fi
    echo "ERROR: mbsync.service finished with Result=$result" >&2
    run_as_agent journalctl --user -u mbsync.service -n 15 --no-pager >&2 2>/dev/null || true
    exit 1
fi

# No systemd user unit (role not applied, or no lingering session): fall back to
# running mbsync directly, which needs nothing but the config file.
if [[ ! -f "$MBSYNCRC" ]]; then
    echo "ERROR: neither mbsync.service nor $MBSYNCRC is available for $AGENT_USER." >&2
    echo "       Has the agent_mail Ansible role been applied to this host?" >&2
    exit 1
fi

say "systemd unit unavailable; running mbsync directly"
if [[ "$WAIT" == false ]]; then
    setsid sudo -u "$AGENT_USER" mbsync -c "$MBSYNCRC" -a >/dev/null 2>&1 &
    say "mail sync started for $AGENT_USER (not waiting)"
    exit 0
fi
sudo -u "$AGENT_USER" mbsync -c "$MBSYNCRC" -a
