#!/usr/bin/env python3
"""
Brain Agent Launcher

Main entry point that runs the Flask web configuration UI.
The web UI allows configuring the bot and managing the bot process.

Usage:
    python launcher.py              # Start on default port 5000
    python launcher.py --port 8080  # Start on custom port
"""

import sys
import signal
import argparse
from pathlib import Path

# Ensure the project directory is in the Python path
PROJECT_DIR = Path(__file__).parent
sys.path.insert(0, str(PROJECT_DIR))

from web_config.app import run_server, stop_bot


def signal_handler(signum, frame):
    """Handle shutdown signals gracefully."""
    print("\n[LAUNCHER] Shutting down...")
    stop_bot()
    sys.exit(0)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Brain Agent Launcher")
    parser.add_argument("--port", type=int, default=5000, help="Port to run the web UI on")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="Host to bind to")
    parser.add_argument("--debug", action="store_true", help="Run in debug mode")
    args = parser.parse_args()

    # Register signal handlers for graceful shutdown
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    print("=" * 60)
    print("BRAIN AGENT LAUNCHER")
    print("=" * 60)
    print(f"Web UI: http://{args.host}:{args.port}")
    print(f"Access from browser: http://170.64.142.252:{args.port}")
    print("=" * 60)

    # Run the Flask server
    run_server(host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()
