# Agent Container Usage

## Start Container

```bash
# As ha_agent user
sudo -iu ha_agent

# Set runtime directory
export XDG_RUNTIME_DIR=/run/user/$(id -u)

# Run container
podman --cgroup-manager=cgroupfs run --rm -it \
    --name claude-ha-agent \
    --userns=keep-id \
    --secret anthropic_api_key,target=/run/secrets/anthropic_api_key \
    --secret github_token,target=/run/secrets/github_token \
    --secret ha_access_token,target=/run/secrets/ha_access_token \
    --network=ha-agent-net \
    -e HTTP_PROXY=http://host.containers.internal:8888 \
    -e HTTPS_PROXY=http://host.containers.internal:8888 \
    -e HOME=/workspace \
    claude-ha-agent \
    bash
```

## Home Assistant Access

The agent uses the HA REST API via HTTP. The `ha_access_token` secret provides authentication.

```bash
# Inside container - example API calls
HA_TOKEN=$(cat /run/secrets/ha_access_token)

# Get HA state
curl -s -H "Authorization: Bearer $HA_TOKEN" http://10.4.4.10:8123/api/

# List all entities
curl -s -H "Authorization: Bearer $HA_TOKEN" http://10.4.4.10:8123/api/states

# Call a service
curl -s -X POST -H "Authorization: Bearer $HA_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"entity_id": "light.living_room"}' \
    http://10.4.4.10:8123/api/services/light/turn_on
```

## Run Integration Tests

```bash
sudo -iu ha_agent bash -c 'cd ~/tests && ./run_integration.sh'
```

## Prerequisites

- `ha_agent` user configured (see `setup.md`)
- Podman secrets created: `anthropic_api_key`, `github_token`, `ha_access_token`
- Podman network exists: `ha-agent-net`
- Tinyproxy running on host port 8888
