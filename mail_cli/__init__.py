"""Container-side read-only Maildir CLI for freigang agents.

The container never speaks IMAP; a host-side job syncs a Maildir in
read-only, and this package only ever reads it. See docs/agent-mail.md
(added in a later phase) and GitHub issue #37 for the full design.
"""
