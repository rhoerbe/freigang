FROM node:22-bookworm

# System deps for Playwright + SSH + Git + session recording
RUN apt-get update && apt-get install -y \
    openssh-client \
    git \
    curl \
    bsdutils \
    # Playwright's Chromium dependencies
    libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 \
    libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 \
    libxfixes3 libxrandr2 libgbm1 libpango-1.0-0 \
    libasound2 libatspi2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Claude Code
RUN npm install -g @anthropic-ai/claude-code

# GitHub CLI
RUN curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
    | dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg && \
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
    | tee /etc/apt/sources.list.d/github-cli.list && \
    apt-get update && apt-get install -y gh && rm -rf /var/lib/apt/lists/*

# Playwright MCP server + browser
RUN npx playwright install chromium

WORKDIR /workspace

# MCP config template (copied to user home at runtime via --userns=keep-id)
COPY mcp-config.json /etc/claude/mcp-config.json
