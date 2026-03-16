#!/usr/bin/env python3
"""Freigang container launcher TUI using textual."""

import json
import os
import sys
from pathlib import Path

import yaml
from textual import on
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Checkbox, Footer, Header, Label, RadioButton, RadioSet, Select, Static


# Fallback MCP servers if manifest not found
DEFAULT_MCP_MANIFEST = {
    "installed": [
        {"name": "playwright", "package": "@playwright/mcp", "description": "Browser automation"}
    ],
    "external": []
}

# All MCP servers off by default on first start (filesystem access is always on via Claude Code itself)
DEFAULT_MCP_ENABLED: list[str] = []


def load_claude_settings(settings_path: Path) -> dict:
    """Load Claude's settings.json, returns empty dict if not found."""
    if settings_path.exists():
        try:
            with open(settings_path) as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {}


def save_claude_settings(settings_path: Path, settings: dict) -> None:
    """Save Claude's settings.json, preserving other settings."""
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    with open(settings_path, "w") as f:
        json.dump(settings, f, indent=2)


def get_enabled_mcp_servers(claude_settings: dict, project_path: str) -> set[str]:
    """Extract enabled MCP server names from Claude's project config."""
    # Format: {"projects": {"<path>": {"mcpServers": {"name": {...}}}}}
    project = claude_settings.get("projects", {}).get(project_path, {})
    return set(project.get("mcpServers", {}).keys())


def update_mcp_in_settings(claude_settings: dict, project_path: str, selected_servers: list[dict], manifest_servers: list[dict]) -> dict:
    """Update Claude's project mcpServers config based on TUI selection.

    Args:
        claude_settings: Current ~/.claude.json content
        project_path: Container project path (e.g., "/workspace/hadmin")
        selected_servers: List of {name, package} dicts for selected servers
        manifest_servers: List of all servers from manifest (to know which we manage)

    Returns:
        Updated ~/.claude.json dict
    """
    import copy
    settings = copy.deepcopy(claude_settings)

    # Ensure projects structure exists
    if "projects" not in settings:
        settings["projects"] = {}
    if project_path not in settings["projects"]:
        settings["projects"][project_path] = {}
    if "mcpServers" not in settings["projects"][project_path]:
        settings["projects"][project_path]["mcpServers"] = {}

    mcp_servers = settings["projects"][project_path]["mcpServers"]

    # Get names of servers we manage (from manifest)
    managed_names = {s["name"] for s in manifest_servers}

    # Remove managed servers that are deselected
    for name in list(mcp_servers.keys()):
        if name in managed_names:
            del mcp_servers[name]

    # Add selected servers (format must match Claude's expected structure)
    for server in selected_servers:
        mcp_servers[server["name"]] = {
            "type": "stdio",
            "command": "npx",
            "args": [server["package"]],
            "env": {}
        }

    return settings


class SecretCheckbox(Checkbox):
    """Checkbox for secret selection with availability indicator."""

    def __init__(self, name: str, present: bool, enabled: bool) -> None:
        # Show availability status in the label
        status = "[green]✓[/]" if present else "[red]✗[/]"
        label = f"{status} {name}"
        # Only enable checkbox if secret file exists
        super().__init__(label, value=enabled and present, disabled=not present, id=f"secret-{name}", classes="mcp-checkbox")


class LauncherApp(App):
    """Freigang container launcher application."""

    CSS = """
    Screen {
        layout: vertical;
    }

    #main-container {
        height: auto;
        padding: 1 2;
    }

    .section {
        height: auto;
        margin-bottom: 1;
        border: solid $primary;
        padding: 0 1;
    }

    .context-line {
        height: 1;
        padding: 0;
    }

    .inline-row {
        layout: horizontal;
        height: auto;
        align: left middle;
    }

    .inline-label {
        width: auto;
        padding-right: 1;
    }

    .inline-select {
        width: 1fr;
        max-width: 40;
    }

    .mcp-grid {
        layout: horizontal;
        height: auto;
    }

    .mcp-checkbox {
        width: auto;
        margin-right: 2;
    }

    .browser-radio-row {
        layout: horizontal;
        height: auto;
        align: left middle;
    }

    .browser-radio-row RadioButton {
        margin-right: 2;
    }

    .browser-vnc-checkbox {
        width: auto;
        margin-left: 3;
    }

    .mcp-servers-label {
        height: 1;
        margin-top: 1;
        padding: 0;
    }

    .secrets-grid {
        layout: horizontal;
        height: auto;
    }

    .secrets-grid Static {
        margin-right: 2;
    }

    #button-row {
        height: auto;
        margin-top: 1;
        align: center middle;
    }

    #button-row Button {
        margin: 0 2;
    }

    #start-button {
        background: $success;
    }

    #exit-button {
        background: $error;
    }
    """

    BINDINGS = [
        ("q", "quit", "Exit"),
        ("enter", "start", "Start"),
    ]

    def __init__(self, config: dict) -> None:
        super().__init__()
        self.config = config
        self.result = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)

        with Vertical(id="main-container"):
            # Context - single compact line
            with Vertical(classes="section"):
                # Show agent identity if available
                agent_prefix = ""
                if self.config.get("agent_id"):
                    agent_name = self.config["agent_id"]
                    agent_desc = self.config.get("agent_desc", "")
                    agent_prefix = f"Agent: [bold]{agent_name}[/] ({agent_desc})  |  "

                context_str = (
                    f"{agent_prefix}"
                    f"Host: [bold]{self.config['hostname']}[/]  |  "
                    f"Image: [bold]{self.config['container_image']}[/]  |  "
                    f"Repo: [bold]{self.config['repo_name']}[/]"
                )
                yield Static(context_str, classes="context-line")

            # Permission Mode + Session on same line
            with Vertical(classes="section"):
                with Horizontal(classes="inline-row"):
                    yield Label("Permission:", classes="inline-label")
                    yield Select(
                        [(mode, mode) for mode in self.config["permission_modes"]],
                        value=self.config["default_permission_mode"],
                        id="permission-mode",
                        classes="inline-select",
                    )
                    yield Label("Session:", classes="inline-label")
                    session_options = [("Start fresh", "new"), ("Continue last", "continue")]
                    for sess in self.config.get("sessions", []):
                        session_options.append((f"Resume: {sess['date']}", sess["id"]))
                    yield Select(
                        session_options,
                        value="new",
                        id="session",
                        classes="inline-select",
                    )

            # Tooling - Browser Automation + MCP Servers (local scope)
            with Vertical(classes="section"):
                yield Label("Tooling:")

                # Browser Automation
                with Horizontal(classes="browser-radio-row"):
                    yield Label("Browser automation:", classes="inline-label")
                    default_mode = self.config.get("default_browser_mode", "none")
                    yield RadioSet(
                        RadioButton("None", value=(default_mode == "none"), id="browser-none"),
                        RadioButton("Playwright", value=(default_mode == "playwright"), id="browser-playwright"),
                        RadioButton("Claude Chrome", value=(default_mode == "chrome"), id="browser-chrome"),
                        id="browser-mode",
                    )
                    yield Checkbox("Enable VNC", value=self.config.get("default_enable_vnc", False), id="enable-vnc", classes="browser-vnc-checkbox")

                # MCP Servers (excluding playwright which is covered by browser automation)
                mcp_servers_to_show = [s for s in self.config["mcp_installed"] if s["name"] != "playwright"]
                if mcp_servers_to_show:
                    yield Label("MCP Servers:", classes="mcp-servers-label")
                    with Horizontal(classes="mcp-grid"):
                        for server in mcp_servers_to_show:
                            name = server["name"]
                            enabled = name in self.config["default_mcp_servers"]
                            yield Checkbox(
                                server["description"],
                                value=enabled,
                                id=f"mcp-{name}",
                                classes="mcp-checkbox",
                            )

            # Secrets (selectable - only available secrets can be enabled)
            with Vertical(classes="section"):
                yield Label("Secrets (pass to container):")
                with Horizontal(classes="mcp-grid"):
                    for secret in self.config["secrets"]:
                        name = secret["name"]
                        present = secret["present"]
                        enabled = name in self.config.get("default_secrets", [])
                        yield SecretCheckbox(name, present, enabled)
                    if not self.config["secrets"]:
                        yield Static("[dim]No secrets configured[/]")

            # Buttons
            with Horizontal(id="button-row"):
                yield Button("Start", id="start-button", variant="success")
                yield Button("Exit", id="exit-button", variant="error")

        yield Footer()

    def on_mount(self) -> None:
        """Focus the Start button so Enter activates it."""
        self.query_one("#start-button", Button).focus()

    @on(RadioSet.Changed, "#browser-mode")
    def handle_browser_mode_change(self, event: RadioSet.Changed) -> None:
        """Auto-deselect VNC when browser mode is None."""
        if event.pressed and event.pressed.id == "browser-none":
            vnc_checkbox = self.query_one("#enable-vnc", Checkbox)
            vnc_checkbox.value = False

    @on(Button.Pressed, "#start-button")
    def handle_start(self) -> None:
        self.collect_and_exit(start=True)

    @on(Button.Pressed, "#exit-button")
    def handle_exit(self) -> None:
        self.collect_and_exit(start=False)

    def action_start(self) -> None:
        self.collect_and_exit(start=True)

    def action_quit(self) -> None:
        self.collect_and_exit(start=False)

    def collect_and_exit(self, start: bool) -> None:
        if not start:
            self.result = {"action": "exit"}
            self.exit()
            return

        # Collect permission mode
        permission_select = self.query_one("#permission-mode", Select)
        permission_mode = permission_select.value

        # Collect MCP servers (installed in container) - include package info for config generation
        # Exclude playwright as it's handled by browser automation radio buttons
        mcp_servers = []
        for server in self.config["mcp_installed"]:
            if server["name"] == "playwright":
                continue  # Skip playwright, handled by browser automation
            checkbox = self.query_one(f"#mcp-{server['name']}", Checkbox)
            if checkbox.value:
                mcp_servers.append({"name": server["name"], "package": server["package"]})

        # Collect secrets
        secrets = []
        for secret in self.config["secrets"]:
            try:
                checkbox = self.query_one(f"#secret-{secret['name']}", Checkbox)
                if checkbox.value:
                    secrets.append(secret["name"])
            except Exception:
                pass

        # Collect session
        session_select = self.query_one("#session", Select)
        session_value = session_select.value

        if session_value == "new":
            session_arg = ""
        elif session_value == "continue":
            session_arg = "--continue"
        else:
            session_arg = f"--resume {session_value}"

        # Collect browser automation settings
        browser_mode_radioset = self.query_one("#browser-mode", RadioSet)
        browser_mode = "none"
        if browser_mode_radioset.pressed_button:
            button_id = browser_mode_radioset.pressed_button.id
            if button_id == "browser-playwright":
                browser_mode = "playwright"
            elif button_id == "browser-chrome":
                browser_mode = "chrome"
            else:
                browser_mode = "none"

        vnc_checkbox = self.query_one("#enable-vnc", Checkbox)
        enable_vnc = vnc_checkbox.value

        # If Playwright browser mode is selected, add playwright MCP server
        if browser_mode == "playwright":
            playwright_server = next((s for s in self.config["mcp_installed"] if s["name"] == "playwright"), None)
            if playwright_server:
                mcp_servers.append({"name": "playwright", "package": playwright_server["package"]})

        self.result = {
            "action": "start",
            "permission_mode": permission_mode,
            "mcp_servers": mcp_servers,
            "secrets": secrets,
            "session_arg": session_arg,
            "browser_mode": browser_mode,
            "enable_vnc": enable_vnc,
        }
        self.exit()


def load_user_preferences(prefs_path: Path) -> dict:
    """Load user preferences from file. Returns empty dict if file doesn't exist."""
    if prefs_path.exists():
        try:
            with open(prefs_path) as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {}


def save_user_preferences(prefs_path: Path, prefs: dict) -> None:
    """Save user preferences to file."""
    prefs_path.parent.mkdir(parents=True, exist_ok=True)
    with open(prefs_path, "w") as f:
        json.dump(prefs, f, indent=2)


def load_config() -> dict:
    """Load configuration from environment, filesystem, and user preferences."""
    agent_home = os.environ.get("AGENT_HOME", "/home/ha_agent")
    repo_name = os.environ.get("REPO_NAME", "hadmin")
    container_image = os.environ.get("CONTAINER_IMAGE", "claude-ha-agent")

    # Load agent identity if using YAML config
    agent_id = os.environ.get("AGENT_ID")
    agent_desc = os.environ.get("AGENT_DESC")
    agent_config_file = os.environ.get("AGENT_CONFIG_FILE")

    # User preferences path
    prefs_path = Path(os.environ.get("LAUNCHER_PREFS_PATH", f"{agent_home}/workspace/{repo_name}/.claude/launcher_preferences.json"))
    user_prefs = load_user_preferences(prefs_path)

    # Permission modes
    permission_modes_str = os.environ.get(
        "PERMISSION_MODES", "default,acceptEdits,bypassPermissions,plan,dontAsk"
    )
    permission_modes = [m.strip() for m in permission_modes_str.split(",") if m.strip()]
    # Use saved preference or fall back to config default
    default_permission_mode = user_prefs.get("permission_mode", os.environ.get("DEFAULT_PERMISSION_MODE", "bypassPermissions"))

    # Load MCP manifest
    manifest_path = os.environ.get("MCP_MANIFEST_PATH", "")
    mcp_manifest = DEFAULT_MCP_MANIFEST.copy()

    if manifest_path and Path(manifest_path).exists():
        try:
            with open(manifest_path) as f:
                mcp_manifest = json.load(f)
        except (json.JSONDecodeError, IOError):
            pass

    mcp_installed = mcp_manifest.get("installed", [])

    # Filter MCP servers by agent config if available
    if agent_config_file and Path(agent_config_file).exists():
        try:
            with open(agent_config_file) as f:
                agent_config = yaml.safe_load(f)

            # Extract allowed MCP servers from agent config
            allowed_mcp_servers = agent_config.get("resources", {}).get("allowed_mcp_servers", [])
            if allowed_mcp_servers:
                # Filter installed servers by allowed list
                mcp_installed = [
                    srv for srv in mcp_installed
                    if srv["name"] in allowed_mcp_servers
                ]
        except (yaml.YAMLError, IOError, KeyError):
            # If config loading fails, use unfiltered list
            pass

    # Claude's main config file - MCP servers go under projects.<path>.mcpServers
    # This is what `claude mcp add -s local` uses - automatically trusted (no approval needed)
    # Inside container: /workspace/.claude.json
    claude_settings_path = Path(agent_home) / "workspace" / ".claude.json"
    # Project path as seen inside container (for the projects key)
    container_project_path = f"/workspace/{repo_name}"
    claude_settings = load_claude_settings(claude_settings_path)

    # Get currently enabled MCP servers from Claude's actual config
    enabled_in_claude = get_enabled_mcp_servers(claude_settings, container_project_path)

    # Determine which installed servers are currently enabled
    # Priority: Claude's settings > saved preferences > defaults
    if enabled_in_claude:
        default_mcp_servers = [s["name"] for s in mcp_installed if s["name"] in enabled_in_claude]
    elif "mcp_servers" in user_prefs:
        default_mcp_servers = user_prefs["mcp_servers"]
    else:
        default_mcp_str = os.environ.get("DEFAULT_MCP_SERVERS", "")
        default_mcp_servers = [m.strip() for m in default_mcp_str.split(",") if m.strip()] if default_mcp_str else DEFAULT_MCP_ENABLED

    # Selectable secrets (shown in TUI for user selection)
    secrets_dir = Path(agent_home) / "workspace" / ".secrets"
    selectable_secrets_str = os.environ.get("SELECTABLE_SECRETS", "github_token:GitHub token|ha_access_token:HA token|mqtt_username:MQTT user|mqtt_password:MQTT pass")

    secrets = []
    for entry in selectable_secrets_str.split("|"):
        entry = entry.strip()
        if entry:
            parts = entry.split(":", 1)
            name = parts[0]
            present = (secrets_dir / name).exists()
            secrets.append({"name": name, "present": present})

    # Default secrets from preferences (only github_token enabled by default on first start)
    default_secrets = user_prefs.get("secrets", ["github_token"])

    # Browser automation settings from preferences
    default_browser_mode = user_prefs.get("browser_mode", "none")
    default_enable_vnc = user_prefs.get("enable_vnc", False)

    # Sessions
    sessions_dir = Path(agent_home) / "workspace" / repo_name / ".claude" / "projects"
    sessions = []
    if sessions_dir.exists():
        for f in sorted(sessions_dir.glob("**/*.jsonl"), key=lambda x: x.stat().st_mtime, reverse=True)[:5]:
            from datetime import datetime
            mtime = datetime.fromtimestamp(f.stat().st_mtime)
            sessions.append({"id": f.stem, "date": mtime.strftime("%Y-%m-%d %H:%M")})

    import socket
    hostname = socket.gethostname()

    config_dict = {
        "hostname": hostname,
        "container_image": container_image,
        "repo_name": repo_name,
        "permission_modes": permission_modes,
        "default_permission_mode": default_permission_mode,
        "mcp_installed": mcp_installed,
        "default_mcp_servers": default_mcp_servers,
        "secrets": secrets,
        "default_secrets": default_secrets,
        "default_browser_mode": default_browser_mode,
        "default_enable_vnc": default_enable_vnc,
        "sessions": sessions,
        "prefs_path": prefs_path,
        "claude_settings_path": claude_settings_path,
        "claude_settings": claude_settings,
        "container_project_path": container_project_path,
    }

    # Add agent identity if available
    if agent_id:
        config_dict["agent_id"] = agent_id
        config_dict["agent_desc"] = agent_desc

    return config_dict


def main() -> int:
    config = load_config()
    app = LauncherApp(config)
    app.title = "Freigang Agent Launcher"
    app.run()

    if app.result:
        # Write JSON to file (env var set by start_container.sh)
        output_file = os.environ.get("TUI_OUTPUT_FILE", "/tmp/launcher_tui_result.json")
        with open(output_file, "w") as f:
            json.dump(app.result, f)

        # Save user preferences and update Claude's settings (only on successful start)
        if app.result.get("action") == "start":
            # Save just server names (not packages) for preferences - packages may change between builds
            mcp_server_names = [s["name"] if isinstance(s, dict) else s for s in app.result.get("mcp_servers", [])]
            prefs = {
                "permission_mode": app.result.get("permission_mode"),
                "mcp_servers": mcp_server_names,
                "secrets": app.result.get("secrets", []),
                "browser_mode": app.result.get("browser_mode", "none"),
                "enable_vnc": app.result.get("enable_vnc", False),
            }
            save_user_preferences(config["prefs_path"], prefs)

            # Update Claude's ~/.claude.json with MCP server configuration
            # Writes to projects.<container_project_path>.mcpServers (local scope)
            selected_servers = app.result.get("mcp_servers", [])
            updated_settings = update_mcp_in_settings(
                config["claude_settings"],
                config["container_project_path"],
                selected_servers,
                config["mcp_installed"]
            )
            save_claude_settings(config["claude_settings_path"], updated_settings)

        return 0 if app.result.get("action") == "start" else 1
    return 1


if __name__ == "__main__":
    sys.exit(main())
