"""ReOS - Local-first AI assistant for Linux.

Talking Rock brings AI-powered system management to Linux:
- Natural language terminal commands
- CAIRN: Your attention-aware knowledge companion
- RIVA: Recursive code execution with verification
- Local-first with optional cloud AI providers

Usage:
    reos                Start the RPC server (default)
    reos --help         Show this help message
    reos-shell          Natural language terminal integration

Environment Variables:
    REOS_HOST           Server host (default: 127.0.0.1)
    REOS_PORT           Server port (default: 8010)
    REOS_OLLAMA_URL     Ollama API URL (default: http://127.0.0.1:11434)
    REOS_OLLAMA_MODEL   Default Ollama model to use
    REOS_LOG_LEVEL      Logging level (default: INFO)
"""

from __future__ import annotations

import argparse
import sys

import uvicorn

from .logging_setup import configure_logging
from .settings import settings


def main() -> None:
    """Main entry point for ReOS server."""
    parser = argparse.ArgumentParser(
        prog="reos",
        description="ReOS - Local-first AI assistant for Linux",
        epilog="""
Examples:
  reos                     Start the RPC server on default port
  reos --port 8020         Start on custom port
  reos --no-reload         Disable auto-reload (production mode)

For natural language shell integration, use reos-shell:
  reos-shell "what files are here"
  reos-shell --help
        """,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--host",
        default=settings.host,
        help=f"Server host (default: {settings.host})",
    )
    parser.add_argument(
        "--port", "-p",
        type=int,
        default=settings.port,
        help=f"Server port (default: {settings.port})",
    )
    parser.add_argument(
        "--no-reload",
        action="store_true",
        help="Disable auto-reload (for production)",
    )
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default=settings.log_level,
        help=f"Logging level (default: {settings.log_level})",
    )
    parser.add_argument(
        "--version", "-V",
        action="version",
        version="%(prog)s 0.0.0a0 (Talking Rock)",
    )

    args = parser.parse_args()

    configure_logging()

    print(f"Starting ReOS server on {args.host}:{args.port}")
    print("Press Ctrl+C to stop\n")

    uvicorn.run(
        "reos.app:app",
        host=args.host,
        port=args.port,
        reload=not args.no_reload,
        log_level=args.log_level.lower(),
    )


if __name__ == "__main__":
    main()
