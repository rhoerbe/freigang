#!/bin/bash
# Shared plumbing for running an agent's systemd --user units from the host.
#
# Sourced by sync_mail.sh (incoming) and post_drafts.sh (outgoing). It exists
# because both need the same non-obvious environment: `systemctl --user` wants
# XDG_RUNTIME_DIR *and* DBUS_SESSION_BUS_ADDRESS, and without the second it
# fails with
#
#   Failed to connect to user scope bus via local transport:
#   $DBUS_SESSION_BUS_ADDRESS and $XDG_RUNTIME_DIR not defined
#
# even though the units are perfectly healthy. Getting that wrong once is a
# puzzle; getting it wrong differently in two scripts is worse, so it lives
# here rather than being copied.

# Populates AGENT_UID for AGENT_USER, or exits with a clear message.
agent_resolve_user() {
    if ! id "$AGENT_USER" >/dev/null 2>&1; then
        echo "ERROR: no such user: $AGENT_USER" >&2
        exit 1
    fi
    AGENT_UID="$(id -u "$AGENT_USER")"
}

# Run a command as the agent user with a usable systemd --user session.
# Adds sudo only when we are not already that user.
run_as_agent() {
    if [[ "$(id -un)" == "$AGENT_USER" ]]; then
        env XDG_RUNTIME_DIR="/run/user/$AGENT_UID" \
            DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$AGENT_UID/bus" "$@"
    else
        sudo -u "$AGENT_USER" env XDG_RUNTIME_DIR="/run/user/$AGENT_UID" \
            DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$AGENT_UID/bus" "$@"
    fi
}

# Start a unit; with WAIT=false return as soon as it is queued.
# Returns non-zero when the unit is unavailable, so callers can fall back.
agent_start_unit() {
    local unit="$1"
    if [[ "${WAIT:-true}" == true ]]; then
        run_as_agent systemctl --user start "$unit" 2>/dev/null
    else
        run_as_agent systemctl --user start --no-block "$unit" 2>/dev/null
    fi
}

# Result= of the last run, e.g. "success" / "exit-code".
agent_unit_result() {
    run_as_agent systemctl --user show "$1" -p Result --value 2>/dev/null || echo unknown
}

# Recent journal lines for a unit, filtered by an optional grep pattern.
agent_unit_log() {
    local unit="$1" lines="${2:-15}" pattern="${3:-}"
    if [[ -n "$pattern" ]]; then
        run_as_agent journalctl --user -u "$unit" -n "$lines" --no-pager 2>/dev/null \
            | grep -E "$pattern" | tail -1 || true
    else
        run_as_agent journalctl --user -u "$unit" -n "$lines" --no-pager 2>/dev/null || true
    fi
}
