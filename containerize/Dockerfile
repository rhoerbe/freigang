FROM node:22-bookworm

# =============================================================================
# BOTTOM TIER: Most stable deps (OS packages, rarely change) - maximize cache hits
# =============================================================================

# GitHub CLI keyring setup (needed before apt-get install gh)
RUN curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
    | dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg && \
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
    | tee /etc/apt/sources.list.d/github-cli.list

# System deps for Playwright + SSH + Git + session recording + GitHub CLI + Chrome/X11
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
    wget \
    gnupg \
    ca-certificates \
    # X11 and VNC for Chrome GUI support
    xvfb \
    x11vnc \
    dbus-x11 \
    x11-utils \
    # Playwright's Chromium dependencies (shared with Chrome)
    libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 \
    libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 \
    libxfixes3 libxrandr2 libgbm1 libpango-1.0-0 \
    libasound2 libatspi2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Google Chrome Stable installation
RUN wget -q -O - https://dl-ssl.google.com/linux/linux_signing_key.pub | gpg --dearmor > /usr/share/keyrings/google-chrome.gpg && \
    echo "deb [arch=amd64 signed-by=/usr/share/keyrings/google-chrome.gpg] http://dl.google.com/linux/chrome/deb/ stable main" \
    > /etc/apt/sources.list.d/google-chrome.list && \
    apt-get update && apt-get install -y google-chrome-stable --no-install-recommends && \
    rm -rf /var/lib/apt/lists/*

# Force-install Claude Extension for Chrome using enterprise policy
# Extension ID: fcoeoabgfenejglbffodgkkbkcdhcgfn (Claude in Chrome Beta)
RUN mkdir -p /etc/opt/chrome/policies/managed && \
    echo '{ \
        "ExtensionInstallForcelist": [ \
            "fcoeoabgfenejglbffodgkkbkcdhcgfn;https://clients2.google.com/service/update2/crx" \
        ] \
    }' > /etc/opt/chrome/policies/managed/claude_extension.json

# Create machine-id to suppress Chrome errors
RUN dbus-uuidgen > /etc/machine-id

# Chrome seccomp profile for sandbox support in rootless Podman
COPY seccomp/chrome.json /etc/seccomp/chrome.json

# =============================================================================
# MIDDLE TIER: Tools updated weekly (yq, Playwright)
# =============================================================================

# Cache bust argument - pass --build-arg WEEKLY_CACHE_BUST=$(date +%Y-%V) to force weekly updates
ARG WEEKLY_CACHE_BUST=default
RUN echo "Weekly cache bust: ${WEEKLY_CACHE_BUST}"

# yq - YAML processor (for HA config files)
RUN curl -fsSL https://github.com/mikefarah/yq/releases/latest/download/yq_linux_amd64 -o /usr/local/bin/yq \
    && chmod +x /usr/local/bin/yq

# Playwright MCP server + browsers (chromium for Playwright MCP, chrome for system integration)
RUN npm install -g @playwright/mcp && npx playwright install chromium chrome

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
