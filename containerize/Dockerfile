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

# Capability: install PyPi packages
# If the agent needs a python package, it can create a venv
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    python3-venv \
    --no-install-recommends \
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

# Claude Code - native build, staged for runtime seeding.
# The installer drops a native install in /root/.local; we relocate just the
# version binary to a world-readable image path. At runtime entrypoint.sh
# materializes a proper native install in the user's $HOME/.local (a host bind
# mount the image cannot pre-populate). We deliberately do NOT place a binary in
# /usr/local/bin: a bare claude in npm's global prefix makes `claude doctor`
# report a "leftover npm global installation" and miss the native install.
RUN echo "Claude cache bust: ${CLAUDE_CACHE_BUST}" && \
    curl -fsSL https://claude.ai/install.sh | bash -s latest \
    && mkdir -p /usr/local/share/claude-native \
    && cp -a /root/.local/share/claude/versions /usr/local/share/claude-native/ \
    && chmod -R a+rX /usr/local/share/claude-native \
    && rm -rf /root/.local

# Disable Claude Code's background self-updater inside the container.
# Without this, Claude downloads new versions into $HOME/.local and, combined
# with a stale binary elsewhere on PATH, ends up with two installations. The
# image is the single source of truth; updates flow through image rebuilds
# (CLAUDE_CACHE_BUST in build.sh).
ENV DISABLE_AUTOUPDATER=1

# Put the seeded native install ($HOME/.local/bin, HOME=/workspace) first on PATH.
ENV PATH="/workspace/.local/bin:${PATH}"

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

# Statusline script for Claude Code TUI
COPY agent-statusline.sh /usr/local/bin/agent-statusline.sh
RUN chmod +x /usr/local/bin/agent-statusline.sh

# Entrypoint script
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

# Tier-2 Remote Control helper (see docs/agent-auth-design.md)
COPY claude-rc /usr/local/bin/claude-rc
RUN chmod +x /usr/local/bin/claude-rc

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["claude"]
