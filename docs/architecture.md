## Layer Model
This model defines the purpose and concerns of each layer.

## Control and Orchestration Layer
- Define agents by defining Missions (projects, roles, tasks).
- Assign capabilities, skills and resources using policies.
- Launch agents in interactive and non-interactive mode.

## Identity Layer


## Capability and Isolation Layer
- Use containers to implement Capabilites 
- Agents live in containers that are in between ephemeral and persistent instances. 
  They can but spun up and restarted quickly, and state is manage via attached storage.
- Credentials are short-lived, in the order of hours.

## Operations Layer
- Container Image Generation: provide agents with the runtime that provides the tools and integrations for the defined capabilities.
- Container Execution: Managed by the scope-specific system, such as K8s for enterprises and Podman for single users.
- Monitoring and Audit: Integration into OpenTelemetry API
- Financial metrics and billing data.


