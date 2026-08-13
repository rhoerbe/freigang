# Architecture Decision Records

This directory records architectural decisions.

Each ADR is `NNNN-kebab-case-title.md`, titled with the decision itself rather than the topic, and
structured as context, **Decision**, `## Why`, `## Consequences`. ADRs are immutable once merged: a
decision that changes gets a new ADR that supersedes the old one, rather than an edit.

| ADR | Decision |
|-----|----------|
| [0001](0001-engine-deployment-separation.md) | freigang is a value-free collection; deployment values live in a private inventory repo |
| [0002](0002-system-config-outranks-user-config.md) | System-space agent config always outranks user-space |
| [0003](0003-pydantic-schema-and-policy-file-removal.md) | The agent config schema is a pydantic model; the policy file is deleted |
| [0004](0004-multi-agent-by-playbook-loop.md) | Multiple agents come from looping role invocations, not from roles that loop internally |
| [0005](0005-no-autonomous-outward-communication.md) | An agent never communicates outward autonomously |
