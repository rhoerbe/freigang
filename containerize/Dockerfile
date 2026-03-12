FROM node:22-bookworm

# =============================================================================
# BOTTOM TIER: Most stable deps (OS packages, rarely change) - maximize cache hits
# =============================================================================

# GitHub CLI keyring setup (needed before apt-get install gh)
RUN curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
    | dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg && \
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
    | tee /etc/apt/sources.list.d/github-cli.list

# System deps for Playwright + SSH + Git + session recording + GitHub CLI
# Single apt-get update for all packages
RUN apt-get update && apt-get install -y \
    openssh-client \
    git \
    curl \
    bsdutils \
    net-tools \
    iputils-ping \
    jq \
    vim \
    mosquitto-clients \
    gh \
    # Playwright's Chromium dependencies
    libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 \
    libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 \
    libxfixes3 libxrandr2 libgbm1 libpango-1.0-0 \
    libasound2 libatspi2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# =============================================================================
# MIDDLE TIER: Tools updated weekly (yq, Playwright)
# =============================================================================

# Cache bust argument - pass --build-arg WEEKLY_CACHE_BUST=$(date +%Y-%V) to force weekly updates
ARG WEEKLY_CACHE_BUST=default
RUN echo "Weekly cache bust: ${WEEKLY_CACHE_BUST}"

# yq - YAML processor (for HA config files)
RUN curl -fsSL https://github.com/mikefarah/yq/releases/latest/download/yq_linux_amd64 -o /usr/local/bin/yq \
    && chmod +x /usr/local/bin/yq

# Playwright MCP server + browser
RUN npm install -g @playwright/mcp && npx playwright install chromium

# =============================================================================
# TOP TIER: Most frequently changing (Claude Code, local files)
# =============================================================================

# Cache bust argument - pass --build-arg CLAUDE_CACHE_BUST=$(date +%Y-%m-%d) to force daily updates
ARG CLAUDE_CACHE_BUST=default

# Claude Code - native installation (installs to /root/.local/bin/claude)
# Use stable channel for container builds
# Copy binary to /usr/local/bin (not symlink) so it's accessible with --userns=keep-id
RUN echo "Claude cache bust: ${CLAUDE_CACHE_BUST}" && \
    curl -fsSL https://claude.ai/install.sh | bash -s stable \
    && cp /root/.local/bin/claude /usr/local/bin/claude \
    && chmod 755 /usr/local/bin/claude

WORKDIR /workspace

# Set /workspace as home directory for node user (fixes SSH config lookup with --userns=keep-id)
# SSH reads home from /etc/passwd, not $HOME environment variable
RUN usermod -d /workspace node

# Ensure npm cache is writable for rootless podman with --userns=keep-id (used by Playwright MCP)
RUN mkdir -p /workspace/.npm && chmod 777 /workspace/.npm

# MCP config template (copied to user home at runtime via --userns=keep-id)
COPY mcp-config.json /etc/claude/mcp-config.json

# MCP manifest - lists available MCP servers in this container image
# Can be queried by startup script: podman run --rm $IMAGE cat /etc/freigang/mcp-manifest.json
COPY mcp-manifest.json /etc/freigang/mcp-manifest.json

# Entrypoint script
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["claude"]
