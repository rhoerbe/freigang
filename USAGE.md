# Agent Container Usage

## Refresh SSH Certificate

```bash
# As ha_agent user
sudo -iu ha_agent

# Sign the key with local CA (valid 1 week)
ssh-keygen -s ~/.ssh/ca/ca_key -I ha_agent -n ha_agent -V +1w ~/.ssh/id_ed25519.pub

# Verify certificate
ssh-keygen -L -f ~/.ssh/id_ed25519-cert.pub
```

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
    -v ~/.ssh/id_ed25519:/workspace/.ssh/id_ed25519:ro,Z \
    -v ~/.ssh/id_ed25519-cert.pub:/workspace/.ssh/id_ed25519-cert.pub:ro,Z \
    -v ~/.ssh/config:/workspace/.ssh/config:ro,Z \
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

## Run Integration Tests

```bash
sudo -iu ha_agent bash -c 'cd ~/tests && ./run_integration.sh'
```

## Prerequisites

- `ha_agent` user configured (see `setup.md`)
- Podman secrets created: `anthropic_api_key`, `github_token`, `ha_access_token`
- Podman network exists: `ha-agent-net`
- Tinyproxy running on host port 8888
