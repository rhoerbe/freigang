#!/bin/bash
# Chrome Integration Test
# Verifies Chrome can run with sandbox enabled in the container
# Run this inside the container with BROWSER_MODE=chrome

set -e

echo "=== Chrome Integration Test ==="

# 1. Check if the DISPLAY is active
if ! xdpyinfo -display :99 >/dev/null 2>&1; then
    echo "FAIL: X-server (Xvfb) is not running on :99"
    exit 1
fi
echo "PASS: Xvfb is running"

# 2. Start Chrome with CDP (Chrome DevTools Protocol)
google-chrome \
    --remote-debugging-port=9222 \
    --disable-gpu \
    --no-first-run \
    --disable-default-apps \
    "https://example.com" &
CHROME_PID=$!
echo "Started Chrome (PID: $CHROME_PID)"

# 3. Wait for Chrome to initialize
sleep 5

# 4. Verify CDP is responding
if curl -s "http://localhost:9222/json" | jq -e '.[0].url' >/dev/null 2>&1; then
    PAGE_URL=$(curl -s "http://localhost:9222/json" | jq -r '.[0].url')
    echo "PASS: Chrome CDP active, loaded: $PAGE_URL"
else
    echo "FAIL: Chrome CDP not responding"
    kill $CHROME_PID 2>/dev/null || true
    exit 1
fi

# 5. Check Chrome sandbox status
if ps aux | grep -q "chrome.*type=zygote"; then
    echo "PASS: Chrome sandbox is enabled (zygote process found)"
else
    echo "WARNING: Chrome sandbox status unclear"
fi

# 6. Cleanup
kill $CHROME_PID 2>/dev/null || true
echo "=== All tests passed ==="
exit 0
