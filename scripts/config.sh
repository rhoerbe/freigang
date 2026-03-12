# Container configuration
REPO_NAME="hadmin"
CONTAINER_IMAGE="claude-ha-agent"

# Default Claude arguments
DEFAULT_PERMISSION_MODE="bypassPermissions"
CLAUDE_ARGS="--permission-mode $DEFAULT_PERMISSION_MODE"

# Available permission modes for TUI selection
PERMISSION_MODES=(
    "default"
    "acceptEdits"
    "bypassPermissions"
    "plan"
    "dontAsk"
)

# Available MCP servers: "name:package:description"
AVAILABLE_MCP_SERVERS=(
    "playwright:@playwright/mcp:Browser automation and testing"
    "filesystem:@anthropic/mcp-server-filesystem:File system operations"
    "memory:@anthropic/mcp-server-memory:Persistent memory storage"
    "fetch:@anthropic/mcp-server-fetch:HTTP fetch operations"
)

# Default enabled MCP servers
DEFAULT_MCP_SERVERS=("playwright")

# Required secrets (name:description)
REQUIRED_SECRETS=(
    "github_token:GitHub personal access token"
    "ha_access_token:Home Assistant access token"
)

# Optional secrets
OPTIONAL_SECRETS=(
    "anthropic_api_key:Anthropic API key (alternative to OAuth)"
    "mqtt_username:MQTT broker username"
    "mqtt_password:MQTT broker password"
)
