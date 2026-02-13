#!/bin/bash
# Build claude-ha-agent container image
set -e

cd "$(dirname "$0")"

export XDG_RUNTIME_DIR=/run/user/$(id -u)

podman --cgroup-manager=cgroupfs build -t claude-ha-agent .

echo "Build complete. Image: localhost/claude-ha-agent:latest"
podman --cgroup-manager=cgroupfs images claude-ha-agent
