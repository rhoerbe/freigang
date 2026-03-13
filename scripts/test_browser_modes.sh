#!/bin/bash
# Test script for browser automation modes
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "=== Testing Browser Automation Modes ==="
echo

# Test 1: Playwright mode
echo "Test 1: Playwright mode (headless)"
echo "Command: ./start_container.sh --browser=playwright bash -c 'echo BROWSER_MODE=\$BROWSER_MODE && echo ENABLE_VNC=\$ENABLE_VNC'"
./start_container.sh --browser=playwright bash -c 'echo "BROWSER_MODE=$BROWSER_MODE" && echo "ENABLE_VNC=$ENABLE_VNC" && echo "Test passed"' 2>&1 | grep -E "(BROWSER_MODE|ENABLE_VNC|Test passed|Playwright|mode)" || echo "FAILED"
echo

# Test 2: Chrome mode
echo "Test 2: Chrome mode (no VNC)"
echo "Command: ./start_container.sh --browser=chrome bash -c 'echo BROWSER_MODE=\$BROWSER_MODE'"
./start_container.sh --browser=chrome bash -c 'echo "BROWSER_MODE=$BROWSER_MODE" && echo "ENABLE_VNC=$ENABLE_VNC" && echo "Test passed"' 2>&1 | grep -E "(BROWSER_MODE|ENABLE_VNC|Test passed|Chrome|mode)" || echo "FAILED"
echo

# Test 3: None mode
echo "Test 3: No browser mode"
echo "Command: ./start_container.sh --browser=none bash -c 'echo BROWSER_MODE=\$BROWSER_MODE'"
./start_container.sh --browser=none bash -c 'echo "BROWSER_MODE=$BROWSER_MODE" && echo "Test passed"' 2>&1 | grep -E "(BROWSER_MODE|Test passed|mode)" || echo "FAILED"
echo

echo "=== All Tests Complete ==="
