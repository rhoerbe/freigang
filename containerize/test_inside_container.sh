#!/bin/bash
# Run this inside the container to debug connectivity issues
set -e

echo "=== Environment ==="
echo "HOME=$HOME"
echo "CLAUDE_CODE_OAUTH_TOKEN=${CLAUDE_CODE_OAUTH_TOKEN:+set (${#CLAUDE_CODE_OAUTH_TOKEN} chars)}"
echo "ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY:+set (${#ANTHROPIC_API_KEY} chars)}"
echo "GH_TOKEN=${GH_TOKEN:+set (${#GH_TOKEN} chars)}"
echo "HTTP_PROXY=$HTTP_PROXY"
echo "HTTPS_PROXY=$HTTPS_PROXY"
echo "NO_PROXY=$NO_PROXY"

echo ""
echo "=== Secrets ==="
ls -la /run/secrets/ 2>/dev/null || echo "No /run/secrets"

echo ""
echo "=== Claude Config ==="
ls -la ~/.claude/ 2>/dev/null || echo "No ~/.claude"
[[ -f ~/.claude/.credentials.json ]] && echo ".credentials.json exists" || echo ".credentials.json MISSING"

echo ""
echo "=== Network: Anthropic (direct, NO_PROXY) ==="
curl -v --max-time 10 https://api.anthropic.com/v1/messages 2>&1 | head -30

echo ""
echo "=== Network: GitHub (via proxy) ==="
curl -sf --max-time 10 https://api.github.com | head -5

echo ""
echo "=== Network: HA ==="
curl -sf --max-time 10 http://10.4.4.10:8123 | head -5

echo ""
echo "=== Claude CLI ==="
which claude
claude --version

echo ""
echo "=== Try claude doctor ==="
claude doctor 2>&1 || true
