# Integration Tests for Agent Container

Test harness to verify that allowed operations succeed and blocked operations fail.

## Test Environment

- **Host**: riva (local execution only)
- **Target**: Real HA host (10.4.4.10)
- **Secrets**: Real secrets (provisioned to ha_agent)
- **Network**: ha-agent-net with tinyproxy active

## Test Categories

### 1. Home Assistant REST API

| Test | Command | Expected |
|------|---------|----------|
| HA API authenticated | `curl -H "Authorization: Bearer $TOKEN" http://10.4.4.10:8123/api/` | HTTP 200 |
| HA web UI reachable | `curl http://10.4.4.10:8123` | HTTP 200 |

### 2. Proxy - Allowed Domains

| Test | Command | Expected |
|------|---------|----------|
| GitHub API | `curl -s -o /dev/null -w "%{http_code}" https://api.github.com` | 200 |
| GitHub raw content | `curl -s -o /dev/null -w "%{http_code}" https://raw.githubusercontent.com` | 200 or 400 |
| Anthropic API | `curl -s -o /dev/null -w "%{http_code}" https://api.anthropic.com` | 200 or 404 |
| npmjs | `curl -s -o /dev/null -w "%{http_code}" https://registry.npmjs.org` | 200 |
| HA direct | `curl -s -o /dev/null -w "%{http_code}" http://10.4.4.10:8123` | 200 |

### 3. Proxy - Blocked Domains

| Test | Command | Expected |
|------|---------|----------|
| example.com | `curl -s -o /dev/null -w "%{http_code}" https://example.com` | 000 (proxy denies) |
| google.com | `curl -s -o /dev/null -w "%{http_code}" https://google.com` | 000 (proxy denies) |

### 4. Direct Network - Blocked (bypass proxy)

Note: With rootless podman (slirp4netns), nftables FORWARD chain is bypassed. Security is enforced via proxy FilterDefaultDeny.

| Test | Command | Expected |
|------|---------|----------|
| Direct HTTPS | `curl --max-time 5 --noproxy '*' https://example.com` | SKIP (rootless podman) |
| Direct HTTP | `curl --max-time 5 --noproxy '*' http://example.com` | SKIP (rootless podman) |

### 5. Secrets Availability

| Test | Command | Expected |
|------|---------|----------|
| Anthropic key exists | `test -r /run/secrets/anthropic_api_key` | Exit 0 |
| GitHub token exists | `test -r /run/secrets/github_token` | Exit 0 |
| HA token exists | `test -r /run/secrets/ha_access_token` | Exit 0 |

### 6. GitHub Issues Access

| Test | Command | Expected |
|------|---------|----------|
| List issues | `gh issue list --repo rhoerbe/EU23_admin` | Exit 0, lists issues |
| View issue | `gh issue view 10 --repo rhoerbe/EU23_admin` | Exit 0, shows issue content |

### 7. Playwright

| Test | Command | Expected |
|------|---------|----------|
| Playwright installed | `npx playwright --version` | Exit 0, shows version |

## Test Structure

```
agent_containers/tests/
├── run_integration.sh      # Host: start container, run tests, cleanup
├── run_tests.sh            # Container: main test runner
├── test_ha_api.sh          # HA REST API access tests
├── test_proxy_allowed.sh   # Proxy allow tests
├── test_proxy_blocked.sh   # Proxy deny tests
├── test_network_blocked.sh # Direct network block tests (SKIP with rootless)
├── test_secrets.sh         # Secrets availability tests
├── test_github.sh          # GitHub CLI access tests
└── test_playwright.sh      # Playwright availability tests
```

## Execution

### As ha_agent user
```bash
sudo -iu ha_agent bash -c 'cd ~/tests && ./run_integration.sh'
```

## Exit Codes

- `0` - All tests passed
- `1` - One or more tests failed
- `2` - Test environment error (missing secrets, network not configured)

## Prerequisites

Before running tests:
1. `ha_agent` user configured with secrets
2. Podman network `ha-agent-net` exists
3. tinyproxy running on host
4. Container image built
5. HA host (10.4.4.10) reachable

## Test Output

```
[PASS] HA API: authenticated access (HTTP 200)
[PASS] HA web UI: reachable (HTTP 200)
[PASS] Proxy allows GitHub API (HTTP 200)
[PASS] Proxy blocks example.com (HTTP 000)
...
Results: 17 passed, 0 failed
```
