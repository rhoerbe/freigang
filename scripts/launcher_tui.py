#!/usr/bin/env python3
"""Freigang container launcher TUI using textual."""

import json
import os
import sys
from pathlib import Path

from textual import on
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Checkbox, Footer, Header, Label, Select, Static


class SecretStatus(Static):
    """Display secret file status."""

    def __init__(self, name: str, description: str, present: bool) -> None:
        self.secret_name = name
        self.present = present
        icon = "✓" if present else "✗"
        style = "green" if present else "red"
        super().__init__(f"[{style}]{icon}[/] {name}")


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
        padding: 1;
    }

    .section-title {
        text-style: bold;
        margin-bottom: 1;
    }

    .mcp-grid {
        layout: horizontal;
        height: auto;
    }

    .mcp-checkbox {
        width: auto;
        margin-right: 2;
    }

    .secrets-grid {
        layout: horizontal;
        height: auto;
    }

    .secret-item {
        width: auto;
        margin-right: 3;
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

    Select {
        width: 100%;
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
            # Context info
            with Vertical(classes="section"):
                yield Label("Context", classes="section-title")
                yield Static(f"Host: {self.config['hostname']}")
                yield Static(f"Image: {self.config['container_image']}:latest")
                yield Static(f"Repo: {self.config['repo_name']}")

            # Permission Mode
            with Vertical(classes="section"):
                yield Label("Permission Mode", classes="section-title")
                yield Select(
                    [(mode, mode) for mode in self.config["permission_modes"]],
                    value=self.config["default_permission_mode"],
                    id="permission-mode",
                )

            # MCP Servers
            with Vertical(classes="section"):
                yield Label("MCP Servers", classes="section-title")
                with Horizontal(classes="mcp-grid"):
                    for server in self.config["mcp_servers"]:
                        name = server["name"]
                        enabled = name in self.config["default_mcp_servers"]
                        yield Checkbox(
                            server["description"],
                            value=enabled,
                            id=f"mcp-{name}",
                            classes="mcp-checkbox",
                        )

            # Session
            with Vertical(classes="section"):
                yield Label("Session", classes="section-title")
                session_options = [("Start fresh", "new"), ("Continue last", "continue")]
                for sess in self.config.get("sessions", []):
                    session_options.append((f"Resume: {sess['date']}", sess["id"]))
                yield Select(
                    session_options,
                    value="new",
                    id="session",
                )

            # Secrets Status
            with Vertical(classes="section"):
                yield Label("Secrets Status", classes="section-title")
                with Horizontal(classes="secrets-grid"):
                    for secret in self.config["secrets"]:
                        yield SecretStatus(
                            secret["name"],
                            secret["description"],
                            secret["present"],
                        )

            # Buttons
            with Horizontal(id="button-row"):
                yield Button("Start", id="start-button", variant="success")
                yield Button("Exit", id="exit-button", variant="error")

        yield Footer()

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

        # Collect MCP servers
        mcp_servers = []
        for server in self.config["mcp_servers"]:
            checkbox = self.query_one(f"#mcp-{server['name']}", Checkbox)
            if checkbox.value:
                mcp_servers.append(server["name"])

        # Collect session
        session_select = self.query_one("#session", Select)
        session_value = session_select.value

        if session_value == "new":
            session_arg = ""
        elif session_value == "continue":
            session_arg = "--continue"
        else:
            session_arg = f"--resume {session_value}"

        self.result = {
            "action": "start",
            "permission_mode": permission_mode,
            "mcp_servers": mcp_servers,
            "session_arg": session_arg,
        }
        self.exit()


def load_config() -> dict:
    """Load configuration from environment and filesystem."""
    agent_home = os.environ.get("AGENT_HOME", "/home/ha_agent")
    repo_name = os.environ.get("REPO_NAME", "hadmin")
    container_image = os.environ.get("CONTAINER_IMAGE", "claude-ha-agent")

    # Permission modes
    permission_modes_str = os.environ.get(
        "PERMISSION_MODES", "default,acceptEdits,bypassPermissions,plan,dontAsk"
    )
    permission_modes = permission_modes_str.split(",")
    default_permission_mode = os.environ.get("DEFAULT_PERMISSION_MODE", "bypassPermissions")

    # MCP servers from environment (format: "name:package:description,...")
    mcp_servers_str = os.environ.get("AVAILABLE_MCP_SERVERS", "")
    mcp_servers = []
    for entry in mcp_servers_str.split("|"):
        if entry:
            parts = entry.split(":", 2)
            if len(parts) >= 3:
                mcp_servers.append({"name": parts[0], "package": parts[1], "description": parts[2]})

    default_mcp_str = os.environ.get("DEFAULT_MCP_SERVERS", "playwright")
    default_mcp_servers = default_mcp_str.split(",") if default_mcp_str else []

    # Secrets status
    secrets_dir = Path(agent_home) / "workspace" / ".secrets"
    required_secrets_str = os.environ.get("REQUIRED_SECRETS", "")
    optional_secrets_str = os.environ.get("OPTIONAL_SECRETS", "")

    secrets = []
    for entry in (required_secrets_str + "|" + optional_secrets_str).split("|"):
        if entry:
            parts = entry.split(":", 1)
            name = parts[0]
            description = parts[1] if len(parts) > 1 else ""
            present = (secrets_dir / name).exists()
            secrets.append({"name": name, "description": description, "present": present})

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

    return {
        "hostname": hostname,
        "container_image": container_image,
        "repo_name": repo_name,
        "permission_modes": permission_modes,
        "default_permission_mode": default_permission_mode,
        "mcp_servers": mcp_servers,
        "default_mcp_servers": default_mcp_servers,
        "secrets": secrets,
        "sessions": sessions,
    }


def main() -> int:
    config = load_config()
    app = LauncherApp(config)
    app.title = "Freigang Agent Launcher"
    app.run()

    if app.result:
        print(json.dumps(app.result))
        return 0 if app.result.get("action") == "start" else 1
    return 1


if __name__ == "__main__":
    sys.exit(main())
