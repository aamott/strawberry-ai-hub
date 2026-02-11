#!/usr/bin/env python3
"""Cross-platform development server script.

This script provides a more reliable development experience than `uvicorn --reload`
on Windows, where the reload mechanism can hang due to process/signal handling issues.

Usage:
    python scripts/dev.py [--host HOST] [--port PORT] [--no-reload]

The script:
- Runs uvicorn without --reload by default for stability
- Can optionally use --reload with workarounds for known issues
- Handles SIGINT/SIGTERM properly on all platforms
- Provides clear shutdown messages
"""

import argparse
import os
import signal
import subprocess
import sys
from pathlib import Path


def get_project_root() -> Path:
    """Get the ai-hub project root directory."""
    return Path(__file__).parent.parent


def run_server(host: str, port: int, reload: bool = False) -> int:
    """Run the uvicorn server.

    Args:
        host: Host to bind to
        port: Port to bind to
        reload: Whether to enable auto-reload (can be problematic on Windows)

    Returns:
        Exit code from the server process
    """
    project_root = get_project_root()

    # Build uvicorn command
    cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "hub.main:app",
        "--host",
        host,
        "--port",
        str(port),
    ]

    if reload:
        cmd.extend(
            [
                "--reload",
                "--reload-dir",
                str(project_root / "src"),
                # Exclude common problematic directories
                "--reload-exclude",
                "*.pyc",
                "--reload-exclude",
                "__pycache__",
                "--reload-exclude",
                "*.db",
            ]
        )

        # On Windows, set environment variable to help with reload issues
        if sys.platform == "win32":
            os.environ.setdefault("WATCHFILES_FORCE_POLLING", "true")
            print(
                "Note: On Windows, --reload may hang."
                " Use Ctrl+C twice or restart manually."
            )

    print(f"Starting Hub server on http://{host}:{port}")
    print(f"Reload: {'enabled' if reload else 'disabled (recommended for Windows)'}")
    print("Press Ctrl+C to stop\n")

    # Run the server
    process = subprocess.Popen(cmd, cwd=project_root)

    def signal_handler(signum, frame):
        """Handle shutdown signals gracefully."""
        print("\nShutting down server...")
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            print("Force killing server...")
            process.kill()
            process.wait()
        print("Server stopped.")
        sys.exit(0)

    # Register signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Wait for process to complete
    return process.wait()


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Run the Strawberry AI Hub development server"
    )
    parser.add_argument(
        "--host", default="127.0.0.1", help="Host to bind to (default: 127.0.0.1)"
    )
    parser.add_argument(
        "--port", type=int, default=8000, help="Port to bind to (default: 8000)"
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Enable auto-reload (can be problematic on Windows)",
    )

    args = parser.parse_args()

    try:
        sys.exit(run_server(args.host, args.port, args.reload))
    except KeyboardInterrupt:
        print("\nServer stopped.")
        sys.exit(0)


if __name__ == "__main__":
    main()
