#!/usr/bin/env python3
"""Self-bootstrapping launcher for the TraderMade MCP server.

This script is intentionally stdlib-only so it can:
1. Create a local virtual environment on first run
2. Install the package and dependencies into that environment
3. Optionally load configuration from a local .env file
4. Exec into the real MCP server entry point

All bootstrap logs go to stderr so stdio-based MCP clients do not see
unexpected output on stdout before the server starts.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Iterable


PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_VENV_DIR = PROJECT_ROOT / "venv"
STATE_FILE_NAME = ".tradermade-bootstrap.json"
MIN_PYTHON = (3, 10)
BUILD_REQUIREMENTS = ["setuptools>=68", "wheel"]

def log(message: str) -> None:
    print(f"[tradermade-bootstrap] {message}", file=sys.stderr)


def fail(message: str, exit_code: int = 1) -> "Never":
    log(message)
    raise SystemExit(exit_code)


def parse_args() -> tuple[argparse.Namespace, list[str]]:
    parser = argparse.ArgumentParser(
        description="Create a local venv if needed, install TraderMade MCP, and run the server."
    )
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse", "streamable-http"],
        help="Transport passed to tradermade_mcp.server",
    )
    parser.add_argument("--api-key", help="Optional TRADERMADE_API_KEY override")
    parser.add_argument("--base-url", help="Optional TRADERMADE_API_BASE_URL override")
    parser.add_argument("--max-tables", type=int, help="Optional TRADERMADE_MAX_TABLES override")
    parser.add_argument("--max-rows", type=int, help="Optional TRADERMADE_MAX_ROWS override")
    parser.add_argument(
        "--venv-dir",
        default=str(DEFAULT_VENV_DIR),
        help="Virtual environment directory to create/use. Default: venv",
    )
    parser.add_argument(
        "--dotenv",
        default=".env",
        help="Optional dotenv file to read before launching the server. Default: .env",
    )
    parser.add_argument(
        "--dotenv-override",
        action="store_true",
        help="Allow dotenv values to override existing process environment variables.",
    )
    parser.add_argument(
        "--force-install",
        action="store_true",
        help="Force reinstall the package into the managed virtual environment.",
    )
    parser.add_argument(
        "--bootstrap-only",
        action="store_true",
        help="Prepare the environment and exit without starting the MCP server.",
    )
    parser.add_argument(
        "--configure-claude",
        action="store_true",
        help=(
            "Write the tradermade entry into Claude Desktop's claude_desktop_config.json. "
            "Use together with --bootstrap-only for a one-step setup."
        ),
    )
    parser.add_argument(
        "--print-server-command",
        action="store_true",
        help="Print the final server command to stderr before exec.",
    )
    return parser.parse_known_args()


def ensure_host_python() -> None:
    if sys.version_info < MIN_PYTHON:
        fail(
            f"Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+ is required; "
            f"current interpreter is {sys.version.split()[0]}"
        )


def get_venv_python(venv_dir: Path) -> Path:
    if os.name == "nt":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def run_checked(command: Iterable[str], *, cwd: Path | None = None) -> None:
    temp_dir = (PROJECT_ROOT / ".bootstrap-tmp").resolve()
    pip_tracker_dir = temp_dir / "pip-build-tracker"
    pip_cache_dir = temp_dir / "pip-cache"
    temp_dir.mkdir(parents=True, exist_ok=True)
    pip_tracker_dir.mkdir(parents=True, exist_ok=True)
    pip_cache_dir.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["TMP"] = str(temp_dir)
    env["TEMP"] = str(temp_dir)
    env["TMPDIR"] = str(temp_dir)
    env["PIP_BUILD_TRACKER"] = str(pip_tracker_dir)
    env["PIP_CACHE_DIR"] = str(pip_cache_dir)
    completed = subprocess.run(
        list(command),
        cwd=str(cwd) if cwd is not None else None,
        env=env,
        stdout=sys.stderr,
        stderr=sys.stderr,
        check=False,
    )
    if completed.returncode != 0:
        fail(f"Command failed with exit code {completed.returncode}: {' '.join(command)}")


def ensure_venv(venv_dir: Path) -> Path:
    venv_python = get_venv_python(venv_dir)
    if venv_python.exists():
        return venv_python
    log(f"Creating virtual environment at {venv_dir}")
    # Use --without-pip to avoid ensurepip hanging on Python 3.14+ / Windows.
    # We bootstrap pip ourselves immediately after.
    run_checked(
        [sys.executable, "-m", "venv", "--without-pip", str(venv_dir)],
        cwd=PROJECT_ROOT,
    )
    if not venv_python.exists():
        fail(f"Virtual environment was created but {venv_python} was not found")
    log("Bootstrapping pip inside the virtual environment")
    run_checked([str(venv_python), "-m", "ensurepip", "--upgrade"], cwd=PROJECT_ROOT)
    return venv_python


def compute_project_fingerprint() -> str:
    digest = hashlib.sha256()
    for relative_path in ("pyproject.toml",):
        path = PROJECT_ROOT / relative_path
        digest.update(relative_path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def get_state_path() -> Path:
    return PROJECT_ROOT / STATE_FILE_NAME


def read_state(venv_dir: Path) -> dict[str, str]:
    state_path = get_state_path()
    if not state_path.exists():
        return {}
    try:
        return json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def write_state(venv_dir: Path, state: dict[str, str]) -> None:
    state_path = get_state_path()
    state_path.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")


def package_is_importable(venv_python: Path) -> bool:
    check = subprocess.run(
        [
            str(venv_python),
            "-c",
            "import mcp, tradermade_mcp; print('ok', end='')",
        ],
        cwd=str(PROJECT_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    return check.returncode == 0 and check.stdout == "ok"


def ensure_install(venv_python: Path, venv_dir: Path, *, force_install: bool) -> None:
    fingerprint = compute_project_fingerprint()
    state = read_state(venv_dir)
    importable = package_is_importable(venv_python)

    if importable and not state and not force_install:
        write_state(
            venv_dir,
            {
                "fingerprint": fingerprint,
                "python": str(venv_python),
            },
        )
        return

    install_needed = force_install or not importable or state.get("fingerprint") != fingerprint
    if not install_needed:
        return

    log("Installing TraderMade MCP into the managed virtual environment")
    run_checked(
    [
        str(venv_python),
        "-m",
        "pip",
        "--disable-pip-version-check",
        "install",
        *BUILD_REQUIREMENTS,
        ],
        cwd=PROJECT_ROOT,
    )
    run_checked(
    [
        str(venv_python),
        "-m",
        "pip",
        "--disable-pip-version-check",
        "install",
        "--no-build-isolation",
        "-e",
        str(PROJECT_ROOT),
    ],
    cwd=PROJECT_ROOT,
    )


def load_dotenv(dotenv_path: Path, *, override: bool) -> None:
    if not dotenv_path.exists():
        return

    for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        if override or key not in os.environ:
            os.environ[key] = value


def apply_launcher_overrides(args: argparse.Namespace) -> None:
    if args.api_key:
        os.environ["TRADERMADE_API_KEY"] = args.api_key
    if args.base_url:
        os.environ["TRADERMADE_API_BASE_URL"] = args.base_url
    if args.max_tables is not None:
        os.environ["TRADERMADE_MAX_TABLES"] = str(args.max_tables)
    if args.max_rows is not None:
        os.environ["TRADERMADE_MAX_ROWS"] = str(args.max_rows)
    if args.transport:
        os.environ["MCP_TRANSPORT"] = args.transport


def build_server_command(venv_python: Path, args: argparse.Namespace, passthrough: list[str]) -> list[str]:
    command = [str(venv_python), "-m", "tradermade_mcp.server"]
    if args.transport:
        command.extend(["--transport", args.transport])
    command.extend(passthrough)
    return command


def get_claude_config_path() -> Path:
    """Return the platform-specific path to claude_desktop_config.json.

    On Windows, Claude Desktop can be installed two ways:
      - Standard installer  → %APPDATA%\\Claude\\claude_desktop_config.json
      - Windows Store (UWP) → %LOCALAPPDATA%\\Packages\\Claude_<id>\\LocalCache\\Roaming\\Claude\\claude_desktop_config.json

    We check the standard path first. If it does not exist, we scan the
    Packages folder for any directory whose name starts with 'Claude_' and
    return the config path inside it.
    """
    if sys.platform == "win32":
        app_data = os.environ.get("APPDATA", "")
        local_app_data = os.environ.get("LOCALAPPDATA", "")

        if not app_data and not local_app_data:
            fail("Neither APPDATA nor LOCALAPPDATA is set; cannot locate Claude Desktop config.")

        # 1. Windows Store (UWP) install takes priority — scan Packages for Claude_* directory.
        #    The Store version writes its config to a virtualised Roaming path that the
        #    standard %APPDATA% location does NOT reflect, so we must find it first.
        if local_app_data:
            packages_dir = Path(local_app_data) / "Packages"
            if packages_dir.is_dir():
                for entry in packages_dir.iterdir():
                    if entry.is_dir() and entry.name.startswith("Claude_"):
                        store_config = entry / "LocalCache" / "Roaming" / "Claude" / "claude_desktop_config.json"
                        log(f"Detected Windows Store Claude install → {store_config}")
                        return store_config

        # 2. Standard installer path
        if app_data:
            return Path(app_data) / "Claude" / "claude_desktop_config.json"

        fail("Could not locate a Claude Desktop installation on this machine.")

    elif sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    else:
        # Linux / other POSIX
        xdg_config = os.environ.get("XDG_CONFIG_HOME", "")
        base = Path(xdg_config) if xdg_config else Path.home() / ".config"
        return base / "Claude" / "claude_desktop_config.json"


def write_claude_config(venv_python: Path, api_key: str) -> None:
    """Merge the tradermade MCP entry into Claude Desktop's config file."""
    config_path = get_claude_config_path()

    # Build the new server entry using the resolved venv python path
    new_entry: dict = {
        "command": str(venv_python),
        "args": ["-m", "tradermade_mcp.server"],
        "env": {"TRADERMADE_API_KEY": api_key},
    }

    # Load existing config or start fresh
    config: dict = {}
    if config_path.exists():
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            fail(f"Could not read existing Claude config at {config_path}: {exc}")

    already_present = (
        config.get("mcpServers", {}).get("tradermade", {}).get("command") == str(venv_python)
        and config.get("mcpServers", {}).get("tradermade", {}).get("env", {}).get("TRADERMADE_API_KEY") == api_key
    )
    if already_present:
        log("Claude Desktop config already up-to-date — no changes written.")
        return

    config.setdefault("mcpServers", {})["tradermade"] = new_entry

    # Ensure the parent directory exists (Claude may not have been launched yet)
    config_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    except OSError as exc:
        fail(f"Could not write Claude config to {config_path}: {exc}")

    log(f"Claude Desktop config written → {config_path}")
    log("Restart Claude Desktop to apply the new server configuration.")


def main() -> None:
    ensure_host_python()
    args, passthrough = parse_args()

    venv_dir = Path(args.venv_dir).expanduser()
    if not venv_dir.is_absolute():
        venv_dir = (PROJECT_ROOT / venv_dir).resolve()

    venv_python = ensure_venv(venv_dir)
    ensure_install(venv_python, venv_dir, force_install=args.force_install)

    dotenv_path = Path(args.dotenv).expanduser()
    if not dotenv_path.is_absolute():
        dotenv_path = (PROJECT_ROOT / dotenv_path).resolve()
    load_dotenv(dotenv_path, override=args.dotenv_override)
    apply_launcher_overrides(args)

    command = build_server_command(venv_python, args, passthrough)
    if args.print_server_command:
        log(f"Launching: {' '.join(command)}")

    if args.bootstrap_only:
        log("Bootstrap complete")
        if args.configure_claude:
            api_key = os.environ.get("TRADERMADE_API_KEY", "")
            if not api_key:
                log(
                    "WARNING: --configure-claude was set but no API key was found. "
                    "Pass --api-key=YOUR_KEY or set TRADERMADE_API_KEY in your environment."
                )
            else:
                write_claude_config(venv_python, api_key)
        return

    env = os.environ.copy()

    if os.name == "nt":
        completed = subprocess.run(
            command,
            cwd=str(PROJECT_ROOT),
            env=env,
            stdin=sys.stdin,
            stdout=sys.stdout,
            stderr=sys.stderr,
            check=False,
        )
        raise SystemExit(completed.returncode)

    os.execve(str(venv_python), command, env)


if __name__ == "__main__":
    main()